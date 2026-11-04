"""
公開応答に載せてよいエラー文言の一元管理。

上流のエラー文面(内部 URL、モデル名、クレジット状況など)と使用中のプロバイダ名はクライアントに
返さず、サーバーログだけに残す。業務上の入力エラー(未対応の項目名など)はこの対象ではない。
"""
import logging

from fastapi import HTTPException

log = logging.getLogger("uvicorn.error")

AI_UNAVAILABLE = "AIサービスが一時的に利用できません。しばらくしてから再度お試しください。"
AI_RATE_LIMITED = "AI機能の利用回数の上限に達しました。しばらくしてからお試しください。"
LEGACY_UNAVAILABLE = "基幹システムに接続できません。しばらくしてから再度お試しください。"
STEP_FAILED = "ステップの実行に失敗しました。"


def public_provider(name: str) -> str:
    """応答に載せるプロバイダ表記。デモ応答か実AIかだけを区別する。"""
    return "mock" if name == "mock" else "live"


def log_upstream(what: str, exc: BaseException) -> None:
    log.warning("%s: %s", what, str(exc) or repr(exc))


def legacy_unavailable(exc: BaseException) -> HTTPException:
    log_upstream("legacy system error", exc)
    return HTTPException(502, LEGACY_UNAVAILABLE)
