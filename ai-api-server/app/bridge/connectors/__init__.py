from app.bridge.connectors.base import Connector, FetchResult
from app.bridge.connectors.file import FileConnector
from app.bridge.connectors.http_list import HttpListConnector
from app.bridge.connectors.sql import SqlConnector

CONNECTOR_TYPES: dict[str, type[Connector]] = {
    c.type_name: c for c in (HttpListConnector, SqlConnector, FileConnector)
}


def build_connector(name: str, type_name: str, config: dict) -> Connector:
    try:
        cls = CONNECTOR_TYPES[type_name]
    except KeyError:
        raise ValueError(f"unknown connector type: {type_name} (available: {sorted(CONNECTOR_TYPES)})") from None
    return cls(name, config)


__all__ = ["Connector", "FetchResult", "build_connector", "CONNECTOR_TYPES"]
