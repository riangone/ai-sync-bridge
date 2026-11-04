"""
ファイルコネクタ: CSV / TSV / 固定長テキスト(レガシー夜間バッチの出力等)。

エンティティ options:
  path     : ファイルパス
  format   : csv | tsv | fixed   (既定 csv)
  encoding : 既定 cp932 (Shift_JIS の Windows 拡張。日本の業務系出力の事実上の標準)
  header   : csv/tsv の先頭行をヘッダとして扱うか(既定 true)。false の場合 columns に列名を列挙
  columns  : fixed の場合 [{name, start, length}] を「バイト位置」で指定(全角=2バイトの帳票仕様に合わせる)
  skip_lines: 先頭の読み飛ばし行数(帳票タイトル等)

差分方式: ファイル指紋(sha256)が前回と同一なら何もしない(unchanged)。変わっていれば全件を
snapshot として返し、行単位の内容ハッシュ比較(SyncEngine)で実際の変更行だけ再埋め込みする。
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
from pathlib import Path

from app.bridge.connectors.base import Connector, FetchResult
from app.bridge.models import EntitySpec


def _parse_fixed(raw: bytes, columns: list[dict], encoding: str, skip: int) -> list[dict]:
    rows = []
    for i, line in enumerate(raw.splitlines()):
        if i < skip or not line.strip():
            continue
        row = {}
        for c in columns:
            s, n = int(c["start"]), int(c["length"])
            row[c["name"]] = line[s : s + n].decode(encoding, errors="replace").strip().strip("　")
        rows.append(row)
    return rows


def _parse_delimited(text: str, delim: str, header: bool, columns: list | None, skip: int) -> list[dict]:
    lines = text.splitlines()[skip:]
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)
    data = [r for r in reader if any(x.strip() for x in r)]
    if not data:
        return []
    if header:
        names, data = [h.strip().lstrip("﻿") for h in data[0]], data[1:]
    else:
        names = [c["name"] if isinstance(c, dict) else str(c) for c in (columns or [])]
        if not names:
            raise ValueError("header: false の場合は columns が必要です")
    return [{n: (r[i].strip() if i < len(r) else "") for i, n in enumerate(names)} for r in data]


class FileConnector(Connector):
    type_name = "file"

    def _path(self, entity: EntitySpec) -> Path:
        p = Path(entity.options.get("path") or self.config.get("path", ""))
        base = self.config.get("base_dir")
        return (Path(base) / p) if base and not p.is_absolute() else p

    def _run(self, entity: EntitySpec, cursor: dict | None) -> FetchResult:
        path = self._path(entity)
        raw = path.read_bytes()
        fp = hashlib.sha256(raw).hexdigest()
        new_cursor = {"sha256": fp, "size": len(raw)}
        if cursor and cursor.get("sha256") == fp:
            return FetchResult(rows=[], cursor=new_cursor, snapshot=False, unchanged=True)

        opt = entity.options
        enc = opt.get("encoding", self.config.get("encoding", "cp932"))
        fmt = opt.get("format", "csv")
        skip = int(opt.get("skip_lines", 0))
        if fmt == "fixed":
            rows = _parse_fixed(raw, opt["columns"], enc, skip)
        elif fmt in ("csv", "tsv"):
            text = raw.decode(enc, errors="replace")
            rows = _parse_delimited(text, "\t" if fmt == "tsv" else ",", opt.get("header", True), opt.get("columns"), skip)
        else:
            raise ValueError(f"unsupported file format: {fmt}")
        return FetchResult(rows=rows, cursor=new_cursor, snapshot=True)

    async def fetch(self, entity: EntitySpec, cursor: dict | None) -> FetchResult:
        return await asyncio.to_thread(self._run, entity, cursor)

    def describe(self) -> dict:
        return {**super().describe(), "base_dir": self.config.get("base_dir")}
