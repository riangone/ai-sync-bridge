"""
Notification Center (Singleton)
実装ロードマップ Phase4 ③: ワークフローエンジン等が生成したイベントや管理操作の結果を
「通知」として一箇所に集約する。Chrome拡張の通知パネル・未読バッジはここを参照する。

DIライフサイクル注意点: Singleton。既読/未読状態をプロセス全体で共有する必要があるため、
Scoped で毎回 new すると「既読にしたはずの通知がまた未読で出てくる」バグになる
(vector_index.py / workflow_service.py と同種のDIライフサイクルの罠を踏襲)。
"""
from datetime import datetime
from threading import Lock

_LEVELS = {"info", "warning", "critical"}


class NotificationCenter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._next_id = 1
        self.notifications: list[dict] = []

    def push(
        self,
        *,
        title: str,
        message: str,
        source: str = "system",
        level: str = "info",
        ref_type: str | None = None,
        ref_id: int | None = None,
    ) -> dict:
        if level not in _LEVELS:
            level = "info"
        with self._lock:
            record = {
                "id": self._next_id,
                "source": source,
                "level": level,
                "title": title,
                "message": message,
                "ref_type": ref_type,
                "ref_id": ref_id,
                "read": False,
                "created_at": datetime.utcnow(),
            }
            self._next_id += 1
            self.notifications.append(record)
            return record

    def list(self, unread_only: bool = False, limit: int = 100) -> list[dict]:
        items = [n for n in reversed(self.notifications) if not unread_only or not n["read"]]
        return items[:limit]

    def unread_count(self) -> int:
        return sum(1 for n in self.notifications if not n["read"])

    def mark_read(self, notification_id: int) -> bool:
        with self._lock:
            for n in self.notifications:
                if n["id"] == notification_id:
                    n["read"] = True
                    return True
            return False

    def mark_all_read(self) -> int:
        with self._lock:
            count = 0
            for n in self.notifications:
                if not n["read"]:
                    n["read"] = True
                    count += 1
            return count
