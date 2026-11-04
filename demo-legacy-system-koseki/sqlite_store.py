"""
sqlite_store.py
================
dict / list のドロップイン代替として使える永続化コンテナ。

背景: main.py 側は `db.customers[cid] = {...}` のような素朴な dict 操作しか
行わない設計（7.1章 方式B の発展）になっている。そのため、生成時に素の {} / []
の代わりにこのクラスを差し込むだけで、呼び出し側(main.py)をほぼ無改造のまま
プロセス再起動をまたいだ永続化に対応できる。

方式: 1コンテナ = 1テーブル。カラムは (key, value) のKVS構造とし、value は
JSON文字列でシリアライズする。エンティティごとに列定義の異なる正規化テーブルを
13種類設計するのは本デモの目的（レガシー側は無改造/AI連携の実証）に対して
過剰なため、あえてJSONブロブ方式を採用している。

重要: このファイルは demo-legacy-system / demo-legacy-system-dealer /
ai-api-server の3箇所にコピーして使う（aisb_embed と同じ方式）。パッケージを
共有すると3システムの独立性が損なわれる（1箇所の変更が全システムに波及する）
ため、意図的に非DRYを選択している。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime


class _JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (datetime, date)):
            return {"__dt__": o.isoformat()}
        return super().default(o)


def _json_object_hook(obj: dict):
    if "__dt__" in obj:
        return datetime.fromisoformat(obj["__dt__"])
    return obj


def _dumps(value) -> str:
    return json.dumps(value, cls=_JSONEncoder, ensure_ascii=False)


def _loads(text: str):
    return json.loads(text, object_hook=_json_object_hook)


class PersistentDict(dict):
    """dict を継承しているため get/values/keys/items/len/in/for はそのまま動く。
    書き込み系(__setitem__/__delitem__/pop/clear)だけ SQLite へ write-through する。
    起動時に既存レコードがあれば読み込む(=再起動をまたいだ永続化)。
    空なら呼び出し元がシード生成→__setitem__ 経由で書き込む想定。
    """

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock, table: str):
        super().__init__()
        self._conn = conn
        self._lock = lock
        self._table = table
        with self._lock:
            # key列: 一意性/検索用の文字列表現。key_json列: 元のキーの型(int/str)を
            # 保持したままロードし直すためのJSON表現(ai-api-serverはintキー、
            # legacyシステムは"C0001"のようなstrキーを使うため、型を失うと
            # get(cid) 等のルックアップがキー型不一致で全滅する)。
            self._conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{table}" '
                f'(key TEXT PRIMARY KEY, key_json TEXT NOT NULL, value TEXT NOT NULL)'
            )
            self._conn.commit()
            for key_json, value in self._conn.execute(f'SELECT key_json, value FROM "{table}"'):
                dict.__setitem__(self, json.loads(key_json), _loads(value))

    def __setitem__(self, key, value):
        dict.__setitem__(self, key, value)
        with self._lock:
            self._conn.execute(
                f'INSERT OR REPLACE INTO "{self._table}" (key, key_json, value) VALUES (?, ?, ?)',
                (str(key), json.dumps(key), _dumps(value)),
            )
            self._conn.commit()

    def __delitem__(self, key):
        dict.__delitem__(self, key)
        with self._lock:
            self._conn.execute(f'DELETE FROM "{self._table}" WHERE key = ?', (str(key),))
            self._conn.commit()

    def pop(self, key, *default):
        value = dict.pop(self, key, *default)
        with self._lock:
            self._conn.execute(f'DELETE FROM "{self._table}" WHERE key = ?', (str(key),))
            self._conn.commit()
        return value

    def clear(self):
        dict.clear(self)
        with self._lock:
            self._conn.execute(f'DELETE FROM "{self._table}"')
            self._conn.commit()


class PersistentList(list):
    """追記専用コンテナ。個別要素が事後更新されないログ系データ
    (InventoryTransaction等)にのみ使う。"""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock, table: str):
        super().__init__()
        self._conn = conn
        self._lock = lock
        self._table = table
        with self._lock:
            self._conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{table}" (seq INTEGER PRIMARY KEY, value TEXT NOT NULL)'
            )
            self._conn.commit()
            for _, value in self._conn.execute(f'SELECT seq, value FROM "{table}" ORDER BY seq'):
                list.append(self, _loads(value))

    def append(self, value):
        list.append(self, value)
        with self._lock:
            self._conn.execute(
                f'INSERT INTO "{self._table}" (value) VALUES (?)',
                (_dumps(value),),
            )
            self._conn.commit()

    def clear(self):
        list.clear(self)
        with self._lock:
            self._conn.execute(f'DELETE FROM "{self._table}"')
            self._conn.commit()


def open_db(path: str) -> tuple[sqlite3.Connection, threading.Lock]:
    """1プロセス1接続。SQLiteはマルチスレッド書き込みに弱いため、Lockで直列化する
    (デモ規模のアクセス量ではボトルネックにならない)。"""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn, threading.Lock()
