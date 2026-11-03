"""
SQL(RDBMS)コネクタ。DB-API 2.0 で SELECT のみを発行する。

  dsn: "sqlite:///path/to.db"            … 標準ライブラリ sqlite3
       "odbc:DRIVER={...};SERVER=...;..."  … pyodbc (SQL Server 2008 / Oracle / Access 等を ODBC で一括対応)

エンティティ options:
  table     : 対象テーブル(識別子のみ許可)  または
  query     : 任意の SELECT 文(ビュー相当。ウォーターマーク併用時は外側で WHERE を付ける)
  watermark : 単調増加列(更新日時/rowversion/連番)。指定時は差分取得(snapshot=False)。
              未指定時は毎回全件(snapshot=True、削除も検出)。
  full_every: watermark 使用時、N回に1回は全件取得して削除を検出する(既定 0=しない)

注意: watermark 方式は「物理削除」を検出できない。論理削除列(DeleteFlg 等)を text/acl に
含めるか、full_every を設定すること。
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
from datetime import date, datetime
from decimal import Decimal

from app.bridge.connectors.base import Connector, FetchResult
from app.bridge.models import EntitySpec

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]*(\.[A-Za-z_][A-Za-z0-9_$#]*)?$")


def _plain(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()  # rowversion(timestamp) 等
    return v


class SqlConnector(Connector):
    type_name = "sql"

    def _connect(self):
        dsn: str = self.config["dsn"]
        if dsn.startswith("sqlite:///"):
            conn = sqlite3.connect(f"file:{dsn[len('sqlite:///'):]}?mode=ro", uri=True)
            return conn
        if dsn.startswith("odbc:"):
            import pyodbc  # 遅延 import: 使わない環境にネイティブ依存を強制しない

            conn = pyodbc.connect(dsn[len("odbc:"):], readonly=True, timeout=int(self.config.get("timeout", 30)))
            if enc := self.config.get("encoding"):  # 例: cp932 (古い SQL Server の varchar)
                conn.setdecoding(pyodbc.SQL_CHAR, encoding=enc)
            return conn
        raise ValueError(f"unsupported dsn scheme: {dsn.split(':', 1)[0]}")

    def _base_query(self, entity: EntitySpec) -> str:
        if q := entity.options.get("query"):
            if not re.match(r"^\s*(select|with)\b", q, re.I) or ";" in q.strip().rstrip(";"):
                raise ValueError(f"{entity.name}: query は単一の SELECT 文のみ許可されます")
            return f"SELECT * FROM ({q.strip().rstrip(';')}) aisb_q"
        table = entity.options.get("table", entity.name)
        if not _IDENT.match(table):
            raise ValueError(f"{entity.name}: 不正なテーブル名 {table!r}")
        return f"SELECT * FROM {table}"

    def _run(self, entity: EntitySpec, cursor: dict | None) -> FetchResult:
        wm = entity.options.get("watermark")
        if wm and not _IDENT.match(wm):
            raise ValueError(f"{entity.name}: 不正なウォーターマーク列 {wm!r}")
        full_every = int(entity.options.get("full_every", 0))
        runs = int((cursor or {}).get("runs", 0)) + 1
        do_full = (not wm) or cursor is None or "wm" not in cursor or (full_every and runs % full_every == 0)

        sql = self._base_query(entity)
        args: tuple = ()
        if wm and not do_full:
            # ">=" にする: 同一ウォーターマーク値の行が前回取得後にコミットされても取りこぼさない。
            # 境界行は再取得されるが、SyncEngine の内容ハッシュ比較で再埋め込みはされない。
            sql += f" WHERE {wm} >= ?"
            args = (cursor["wm"],)
        if wm:
            sql += f" ORDER BY {wm}"

        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, args)
            cols = [d[0] for d in cur.description]
            rows = [{c: _plain(v) for c, v in zip(cols, rec)} for rec in cur.fetchall()]
        finally:
            conn.close()

        new_cursor: dict = {"runs": runs}
        if wm:
            prev = (cursor or {}).get("wm")
            new_cursor["wm"] = rows[-1][wm] if rows else prev
        return FetchResult(rows=rows, cursor=new_cursor, snapshot=bool(do_full))

    async def fetch(self, entity: EntitySpec, cursor: dict | None) -> FetchResult:
        # DB-API はブロッキングなのでスレッドに逃がす
        return await asyncio.to_thread(self._run, entity, cursor)

    def describe(self) -> dict:
        scheme = self.config.get("dsn", "").split(":", 1)[0]
        return {**super().describe(), "dsn_scheme": scheme}  # 接続文字列(資格情報)は出さない
