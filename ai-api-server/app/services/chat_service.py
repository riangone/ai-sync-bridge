"""Chat Service (Scoped) - 会話履歴は Singleton(DemoDataStore) に保持させる"""
from app.services.ai_client import AiProvider
from app.services.demo_data import DemoDataStore


class ChatService:
    def __init__(self, ai: AiProvider, store: DemoDataStore):
        self.ai = ai
        self.store = store

    async def send(self, session_id: str, message: str) -> tuple[str, int]:
        history = self.store.get_history(session_id)
        self.store.append_history(session_id, "user", message)
        reply = await self.ai.complete(message, history=history)
        self.store.append_history(session_id, "assistant", reply)
        return reply, len(self.store.get_history(session_id))
