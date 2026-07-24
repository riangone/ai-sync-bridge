"""
Workflow Automation Engine (Singleton)
実装ロードマップ Phase3 ②: 顧客/受注データに対して条件付きルールを評価し、
承認要求・フォローアップ通知等をイベントとして記録する軽量ルールエンジン。

DIライフサイクル注意点: deps.py の DI 表で「ワークフローエンジン=Singleton」と
定義済み。ルール定義と発火履歴(重複発火防止セット含む)をプロセス全体で共有する
必要があるため、Scoped で毎回 new すると同じイベントが再送されてしまう
(vector_index.py の差分同期と同種の設計上の罠なので、ここでも同じ Singleton
原則を踏襲した)。
"""
from datetime import datetime
from threading import Lock

from app.services.demo_data import DemoDataStore

_OPERATORS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: str(a) == str(b),
    "!=": lambda a, b: str(a) != str(b),
    "contains": lambda a, b: str(b).lower() in str(a).lower(),
}


def _coerce(field_value, rule_value: str):
    """数値比較演算子(>, <, ...)を使う場合は両辺を float に揃え、失敗したら文字列のまま比較する。"""
    try:
        return float(field_value), float(rule_value)
    except (TypeError, ValueError):
        return field_value, rule_value


class WorkflowEngine:
    def __init__(self) -> None:
        self._lock = Lock()
        self._next_rule_id = 1
        self._next_event_id = 1
        self.rules: dict[int, dict] = {}
        self.history: list[dict] = []
        self._triggered: set[tuple[int, int]] = set()  # (rule_id, entity_id) の重複発火防止
        self._seed_default_rules()

    def _seed_default_rules(self) -> None:
        defaults = [
            {
                "name": "大口注文承認アラート",
                "entity": "order",
                "field": "amount",
                "operator": ">",
                "value": "1000000",
                "action": "flag_approval",
                "message_template": "受注「{item}」({amount}円) は承認が必要です",
            },
            {
                "name": "休止顧客フォローアップ",
                "entity": "customer",
                "field": "status",
                "operator": "==",
                "value": "休止",
                "action": "notify",
                "message_template": "顧客「{name}」は休止状態です。フォローアップを検討してください",
            },
        ]
        for d in defaults:
            self.add_rule(d)

    def add_rule(self, data: dict) -> dict:
        with self._lock:
            rid = self._next_rule_id
            self._next_rule_id += 1
            rule = {**data, "id": rid, "enabled": data.get("enabled", True)}
            self.rules[rid] = rule
            return rule

    def list_rules(self) -> list[dict]:
        return list(self.rules.values())

    def delete_rule(self, rule_id: int) -> bool:
        with self._lock:
            removed = self.rules.pop(rule_id, None) is not None
            if removed:
                self._triggered = {t for t in self._triggered if t[0] != rule_id}
            return removed

    def _match(self, rule: dict, entity: dict) -> bool:
        if entity.get(rule["field"]) is None:
            return False
        op = _OPERATORS.get(rule["operator"])
        if not op:
            return False
        a, b = _coerce(entity.get(rule["field"]), rule["value"])
        try:
            return op(a, b)
        except TypeError:
            return False

    def evaluate(self, store: DemoDataStore) -> list[dict]:
        """全ルール x 全エンティティを評価し、新規に条件を満たしたイベントのみ返す。"""
        new_events: list[dict] = []
        with self._lock:
            entities_by_type = {
                "customer": store.list_customers(),
                "order": store.list_orders(),
            }
            for rule in self.rules.values():
                if not rule.get("enabled", True):
                    continue
                for entity in entities_by_type.get(rule["entity"], []):
                    key = (rule["id"], entity["id"])
                    if key in self._triggered or not self._match(rule, entity):
                        continue
                    self._triggered.add(key)
                    message = rule["message_template"].format(**entity)
                    event = {
                        "id": self._next_event_id,
                        "rule_id": rule["id"],
                        "rule_name": rule["name"],
                        "entity": rule["entity"],
                        "entity_id": entity["id"],
                        "action": rule["action"],
                        "message": message,
                        "triggered_at": datetime.utcnow(),
                    }
                    self._next_event_id += 1
                    self.history.append(event)
                    new_events.append(event)
        return new_events

    def get_history(self, limit: int = 50) -> list[dict]:
        return list(reversed(self.history))[:limit]

    def reset(self) -> None:
        """Admin: デモデータリセットに追従して発火履歴/重複発火防止セットを初期化する。
        (ルール定義自体は保持する。エンティティIDが振り直された後も同じルールを
        再利用したいため。)
        """
        with self._lock:
            self.history.clear()
            self._triggered.clear()
            self._next_event_id = 1
