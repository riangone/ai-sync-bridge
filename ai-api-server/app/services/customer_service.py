"""Customer Service (Scoped) - demo/prod dual mode はここで分岐する"""
from app.config import Settings
from app.services.demo_data import DemoDataStore


class CustomerService:
    def __init__(self, settings: Settings, store: DemoDataStore):
        self.settings = settings
        self.store = store  # demo_mode=false の場合はここを実DBリポジトリに差し替える

    def list(self) -> list[dict]:
        if self.settings.demo_mode:
            return self.store.list_customers()
        raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")

    def get(self, cid: int) -> dict | None:
        if self.settings.demo_mode:
            return self.store.get_customer(cid)
        raise NotImplementedError

    def create(self, data: dict) -> dict:
        if self.settings.demo_mode:
            return self.store.create_customer(data)
        raise NotImplementedError

    def update(self, cid: int, data: dict) -> dict | None:
        if self.settings.demo_mode:
            return self.store.update_customer(cid, data)
        raise NotImplementedError

    def delete(self, cid: int) -> bool:
        if self.settings.demo_mode:
            return self.store.delete_customer(cid)
        raise NotImplementedError
