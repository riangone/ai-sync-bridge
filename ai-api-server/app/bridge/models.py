from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocAcl:
    """文書単位のアクセス制御メタデータ。None/空 = その軸では制限しない。"""
    tenant: str | None = None
    roles: tuple[str, ...] = ()
    depts: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {"tenant": self.tenant, "roles": list(self.roles), "depts": list(self.depts)}

    @classmethod
    def from_json(cls, d: dict | None) -> "DocAcl":
        d = d or {}
        return cls(d.get("tenant"), tuple(d.get("roles") or ()), tuple(d.get("depts") or ()))

    @property
    def is_public(self) -> bool:
        return self.tenant is None and not self.roles and not self.depts


def _resolve(spec: Any, row: dict) -> Any:
    """"$Field" は行の値参照、それ以外は定数。"""
    if isinstance(spec, str) and spec.startswith("$"):
        return row.get(spec[1:])
    return spec


def _as_tuple(v: Any) -> tuple[str, ...]:
    if v is None or v == "":
        return ()
    if isinstance(v, (list, tuple, set)):
        return tuple(str(x) for x in v if x not in (None, ""))
    return (str(v),)


@dataclass(frozen=True)
class EntitySpec:
    """同期対象エンティティの宣言(プロファイルYAMLから生成)。"""
    name: str
    pk: str
    text_fields: tuple[str, ...]
    title_field: str | None = None
    acl: dict = field(default_factory=dict)          # {tenant, roles, depts}: 定数 or "$Field"
    options: dict = field(default_factory=dict)      # コネクタ固有(table/query/watermark/path...)
    label: str | None = None                         # 利用者の呼び方(例: "従業員 社員")。検索とAIの文脈に使う

    def pk_of(self, row: dict) -> str:
        v = row.get(self.pk)
        if v is None or v == "":
            raise ValueError(f"{self.name}: 主キー {self.pk} が空の行があります")
        return str(v)

    def render_text(self, row: dict) -> str:
        fields = " ".join(f"{f}:{row[f]}" for f in self.text_fields if row.get(f) not in (None, ""))
        return f"Type:{self.label} {fields}" if self.label else fields

    def fingerprint(self) -> str:
        """文書の中身と権限を決める設定のハッシュ。変わったら全行を読み直す必要がある。"""
        payload = json.dumps({"pk": self.pk, "text": self.text_fields, "title": self.title_field,
                              "label": self.label, "acl": self.acl},
                             ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def title_of(self, row: dict) -> str:
        if self.title_field and row.get(self.title_field) not in (None, ""):
            return str(row[self.title_field])
        return f"{self.name}#{self.pk_of(row)}"

    def acl_of(self, row: dict) -> DocAcl:
        t = _resolve(self.acl.get("tenant"), row)
        return DocAcl(
            tenant=None if t in (None, "") else str(t),
            roles=_as_tuple(_resolve(self.acl.get("roles"), row)),
            depts=_as_tuple(_resolve(self.acl.get("depts"), row)),
        )


def content_hash(text: str, title: str, acl: DocAcl) -> str:
    """再埋め込み要否と監査の両方に使う内容ハッシュ。ACLが変わっただけでも
    変更として扱う(権限変更も監査対象であるべきため)。"""
    payload = json.dumps({"t": text, "h": title, "a": acl.to_json()}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
