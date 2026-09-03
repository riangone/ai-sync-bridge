"""
Workflow Automation Engine (Singleton) — マルチステップ・パイプライン版
README 5.4.10「ワークフローエンジン（WorkflowEngineService相当）」の再実装。

旧実装(単一条件式ルール→通知)は仕様の一部(トリガー4種/アクション9種/ステップ間の
変数伝播/nextOnSuccess・nextOnFailure分岐)しかカバーしていなかったため、本ファイルで
定義(トリガー+複数ステップ)と実行(ステップをOrder順に辿るインタプリタ)を分離した
設計に置き換える。

DIライフサイクル注意点: 旧実装から引き続き Singleton。ワークフロー定義と実行履歴を
プロセス全体で共有する必要があるため、Scoped で毎回 new すると定義が消える
(vector_index.py の差分同期と同種の設計上の罠なので、ここでも同じ Singleton
原則を踏襲した)。

実際のステップ実行(OCR/検索/レポート生成/AIチャット等)は他の Scoped サービス群に
委譲する必要があるため、実行そのものは WorkflowEngine ではなく WorkflowStepRunner
(deps.py で毎リクエスト組み立てる)に担わせ、WorkflowEngine.execute() は
「定義の解決 + フロー制御(順序/分岐/変数伝播) + 履歴記録」だけに専念させている。
"""
import re
from datetime import datetime
from threading import Lock
from typing import Any

from app.services.demo_data import DemoDataStore

_VAR_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
_FULL_VAR_RE = re.compile(r"^\{\{\s*([\w.]+)\s*\}\}$")  # 文字列全体が単一の変数参照のみのケース

_CONDITION_OPERATORS = {"equals", "contains", "not_empty", "empty"}


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return str(value)


def resolve_template(value: Any, context: dict) -> Any:
    """設定値の中の {{step_1_output}} 形式の変数をコンテキストの値で展開する。
    文字列全体が単一の変数参照だけの場合(例: "fields": "{{step_1_output}}")は
    元の型(dict/list等)を保ったまま差し替える。文中に埋め込まれている場合
    (例: "{{step_1_output}} 件見つかりました")は文字列化して埋め込む。
    dict/list は再帰的に解決し、文字列以外(数値/bool)はそのまま素通しする。
    """
    if isinstance(value, str):
        full = _FULL_VAR_RE.match(value)
        if full:
            return context.get(full.group(1), value)

        def _repl(m: "re.Match[str]") -> str:
            key = m.group(1)
            if key not in context:
                return m.group(0)
            return _stringify(context[key])

        return _VAR_RE.sub(_repl, value)
    if isinstance(value, dict):
        return {k: resolve_template(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_template(v, context) for v in value]
    return value


class WorkflowEngine:
    def __init__(self) -> None:
        self._lock = Lock()
        self._next_workflow_seq = 1
        self._next_execution_id = 1
        self.workflows: dict[str, dict] = {}
        self.execution_history: list[dict] = []
        self._seed_default_workflows()

    # ------------------------------------------------------------------
    # デモシード: README 5.4.10「シードデータ: 起動時に4種類のデモワークフローを自動投入」
    # ------------------------------------------------------------------
    def _seed_default_workflows(self) -> None:
        defaults = [
            {
                "id": "wf_demo_stock_alert",
                "name": "在庫アラート通知",
                "description": "30分間隔で在庫レポートを生成し、在庫切れがあればプッシュ通知する",
                "trigger": {"type": "schedule", "config": {"intervalMinutes": "30"}},
                "steps": [
                    {"order": 1, "name": "在庫レポート生成", "action_type": "report",
                     "config": {"reportType": "stock"}},
                    {"order": 2, "name": "在庫切れチェック", "action_type": "condition",
                     "config": {"variable": "step_1_output", "operator": "contains", "value": "shortage"}},
                    {"order": 3, "name": "アラート通知", "action_type": "push",
                     "config": {"title": "在庫アラート", "message": "発注点を下回っている商品があります", "severity": "high"}},
                ],
            },
            {
                "id": "wf_demo_ocr_auto_input",
                "name": "帳票OCR→自動入力",
                "description": "受注入力画面遷移時にOCRを実行し、抽出結果を自動入力→完了通知する",
                "trigger": {"type": "screen_navigation", "config": {"screenType": "order_entry"}},
                "steps": [
                    {"order": 1, "name": "帳票OCR", "action_type": "ocr",
                     "config": {"screenType": "order_entry"}},
                    {"order": 2, "name": "自動入力", "action_type": "auto_input",
                     "config": {"screenType": "order_entry", "fields": "{{step_1_output}}"}},
                    {"order": 3, "name": "完了通知", "action_type": "push",
                     "config": {"title": "自動入力完了", "message": "OCR結果を受注入力画面に反映しました", "severity": "info"}},
                ],
            },
            {
                "id": "wf_demo_credit_check",
                "name": "与信超過チェック",
                "description": "新規受注時に与信リスク分析を行い、リスクが高ければ警告通知する",
                "trigger": {"type": "data_update", "config": {"table": "order"}},
                "steps": [
                    {"order": 1, "name": "与信リスク分析", "action_type": "report",
                     "config": {"reportType": "credit_risk"}},
                    {"order": 2, "name": "リスク判定", "action_type": "condition",
                     "config": {"variable": "step_1_output", "operator": "contains", "value": "警戒"}},
                    {"order": 3, "name": "警告通知", "action_type": "push",
                     "config": {"title": "与信超過の恐れ", "message": "与信リスクが高い顧客があります", "severity": "high"}},
                ],
            },
            {
                "id": "wf_demo_daily_report",
                "name": "日次業務レポート",
                "description": "毎日8時に在庫/受注/与信レポートを集約し、AIサマリーを生成して通知する",
                "trigger": {"type": "schedule", "config": {"hour": "8"}},
                "steps": [
                    {"order": 1, "name": "在庫レポート", "action_type": "report", "config": {"reportType": "stock"}},
                    {"order": 2, "name": "受注レポート", "action_type": "report", "config": {"reportType": "order"}},
                    {"order": 3, "name": "与信レポート", "action_type": "report", "config": {"reportType": "credit_risk"}},
                    {"order": 4, "name": "AIサマリー生成", "action_type": "chat",
                     "config": {
                         "systemPrompt": "あなたは基幹システムの日次業務レポートを要約するアシスタントです。",
                         "message": "在庫: {{step_1_output}} / 受注: {{step_2_output}} / 与信: {{step_3_output}} "
                                     "の3つの集計結果を、業務担当者向けに3行程度で要約してください。",
                     }},
                    {"order": 5, "name": "日報通知", "action_type": "push",
                     "config": {"title": "日次業務レポート", "message": "{{step_4_output}}", "severity": "info"}},
                ],
            },
        ]
        for d in defaults:
            self._insert_workflow(d)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def _insert_workflow(self, data: dict) -> dict:
        now = datetime.utcnow()
        steps = sorted(data.get("steps", []), key=lambda s: s["order"])
        wf = {
            "id": data["id"],
            "name": data["name"],
            "description": data.get("description"),
            "enabled": data.get("enabled", True),
            "trigger": data.get("trigger", {"type": "manual", "config": {}}),
            "steps": steps,
            "created_at": now,
            "updated_at": now,
        }
        self.workflows[wf["id"]] = wf
        return wf

    def add_workflow(self, data: dict) -> dict:
        with self._lock:
            wid = f"wf_{self._next_workflow_seq}"
            self._next_workflow_seq += 1
            return self._insert_workflow({**data, "id": wid})

    def list_workflows(self) -> list[dict]:
        return list(self.workflows.values())

    def get_workflow(self, workflow_id: str) -> dict | None:
        return self.workflows.get(workflow_id)

    def update_workflow(self, workflow_id: str, data: dict) -> dict | None:
        with self._lock:
            wf = self.workflows.get(workflow_id)
            if wf is None:
                return None
            for field in ("name", "description", "enabled", "trigger"):
                if field in data and data[field] is not None:
                    wf[field] = data[field]
            if data.get("steps") is not None:
                wf["steps"] = sorted(data["steps"], key=lambda s: s["order"])
            wf["updated_at"] = datetime.utcnow()
            return wf

    def toggle_workflow(self, workflow_id: str) -> dict | None:
        with self._lock:
            wf = self.workflows.get(workflow_id)
            if wf is None:
                return None
            wf["enabled"] = not wf["enabled"]
            wf["updated_at"] = datetime.utcnow()
            return wf

    def delete_workflow(self, workflow_id: str) -> bool:
        with self._lock:
            return self.workflows.pop(workflow_id, None) is not None

    # ------------------------------------------------------------------
    # トリガー評価: README「POST /api/workflow/evaluate-triggers
    # currentScreenType?, changedTable? → matchedWorkflows[]」
    # (schedule トリガーはHTTPリクエスト駆動のこの関数では評価できないため対象外。
    #  cron/スケジューラは本サーバーの責務外とし、/{id}/execute の手動・外部呼び出しで代替する)
    # ------------------------------------------------------------------
    def evaluate_triggers(self, current_screen_type: str | None, changed_table: str | None) -> list[dict]:
        matched = []
        for wf in self.workflows.values():
            if not wf.get("enabled", True):
                continue
            trigger = wf.get("trigger", {})
            ttype = trigger.get("type")
            cfg = trigger.get("config", {})
            if ttype == "screen_navigation" and current_screen_type and cfg.get("screenType") == current_screen_type:
                matched.append(wf)
            elif ttype == "data_update" and changed_table and cfg.get("table") == changed_table:
                matched.append(wf)
        return matched

    # ------------------------------------------------------------------
    # 実行: README「実行フロー」節のインタプリタ
    # ------------------------------------------------------------------
    @staticmethod
    def _next_order_after(order_sequence: list[int], current: int) -> int | None:
        for o in order_sequence:
            if o > current:
                return o
        return None

    def _resolve_next(self, directive: Any, current: int, order_sequence: list[int], ok: bool) -> int | None:
        if directive is None:
            # 明示指定が無い場合のデフォルト: 成功時は次のステップへ、失敗時はそこで打ち切る
            directive = "next" if ok else "end"
        if directive == "end":
            return None
        if directive == "next":
            return self._next_order_after(order_sequence, current)
        try:
            target = int(directive)
        except (TypeError, ValueError):
            return None
        return target if target in order_sequence else None

    async def execute(self, workflow_id: str, initial_context: dict | None, runner: "WorkflowStepRunnerProtocol") -> dict:
        wf = self.workflows.get(workflow_id)
        if wf is None:
            raise KeyError(f"workflow_id={workflow_id} が見つかりません")

        steps_by_order = {s["order"]: s for s in wf["steps"]}
        order_sequence = sorted(steps_by_order)
        context: dict = dict(initial_context or {})
        step_results: list[dict] = []
        started_at = datetime.utcnow()
        any_failed = False
        current_order = order_sequence[0] if order_sequence else None
        visited: set[int] = set()

        while current_order is not None:
            if current_order in visited:
                # nextOnSuccess/nextOnFailure の数値ジャンプによる無限ループを防ぐ安全弁
                break
            visited.add(current_order)
            step = steps_by_order[current_order]
            resolved_config = resolve_template(step.get("config", {}), context)
            try:
                output, ok = await runner.run(step["action_type"], resolved_config, context)
                error = None
            except Exception as exc:  # ステップ内の例外はワークフロー全体を落とさず失敗として記録する
                output, ok, error = None, False, str(exc)

            context[f"step_{current_order}_output"] = output
            step_results.append({
                "order": current_order,
                "name": step.get("name", ""),
                "action_type": step["action_type"],
                "status": "success" if ok else "failed",
                "output": output,
                "error": error,
            })
            if not ok:
                any_failed = True

            next_key = "next_on_success" if ok else "next_on_failure"
            current_order = self._resolve_next(step.get(next_key), current_order, order_sequence, ok)

        finished_at = datetime.utcnow()
        with self._lock:
            execution = {
                "id": self._next_execution_id,
                "workflow_id": workflow_id,
                "workflow_name": wf["name"],
                "trigger_type": wf.get("trigger", {}).get("type", "manual"),
                "status": "failed" if any_failed else "completed",
                "started_at": started_at,
                "finished_at": finished_at,
                "steps": step_results,
                "context": context,
            }
            self._next_execution_id += 1
            self.execution_history.append(execution)
        return execution

    def get_execution_history(self, limit: int = 50) -> list[dict]:
        return list(reversed(self.execution_history))[:limit]

    def reset(self) -> None:
        """Admin: デモデータリセットに追従して実行履歴のみ初期化する。
        (ワークフロー定義自体は保持する。定義はエンティティIDを直接参照しないため、
        顧客/受注データが再シードされても定義を壊す要因にはならない。)
        """
        with self._lock:
            self.execution_history.clear()
            self._next_execution_id = 1


class WorkflowStepRunnerProtocol:
    """型ヒント用のプロトコル。実体は deps.py が組み立てる WorkflowStepRunner。"""

    async def run(self, action_type: str, config: dict, context: dict) -> tuple[Any, bool]: ...
