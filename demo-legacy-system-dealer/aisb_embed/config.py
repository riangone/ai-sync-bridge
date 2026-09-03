"""
aisb_embed の有効/無効設定。

optional な埋め込み機能なので、状態は本体(data.py/main.py)には一切持たせず、
このパッケージ内で完結させる。優先順位:

  1. 環境変数 AISB_EMBED_ENABLED (0/false/no/off で無効・それ以外/未設定なら次へ)
     -> デプロイ時に強制的に固定したい場合用。設定されていれば管理画面からの
        トグルより常に優先される(管理画面にもその旨を表示する)。
  2. state.json (このディレクトリ直下、gitignore対象)
     -> /aisb-embed/admin の「有効化/無効化」ボタンがここを書き換える。
        再起動しても状態が保持される。
  3. どちらも無ければデフォルトで有効。
"""
import json
import os
from pathlib import Path

_STATE_FILE = Path(__file__).parent / "state.json"
_ENV_VAR = "AISB_EMBED_ENABLED"


def env_override() -> bool | None:
    raw = os.environ.get(_ENV_VAR)
    if raw is None:
        return None
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _read_file_state() -> bool | None:
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        return bool(data.get("enabled"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def is_enabled() -> bool:
    env = env_override()
    if env is not None:
        return env
    file_state = _read_file_state()
    return True if file_state is None else file_state


def set_enabled(value: bool) -> None:
    """管理画面からのトグル用。env変数が設定されている間はここで書いても
    is_enabled() の返り値には反映されない(env優先)が、値自体は保存しておく。"""
    _STATE_FILE.write_text(
        json.dumps({"enabled": bool(value)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
