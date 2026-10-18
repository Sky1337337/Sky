from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from threading import Event, Lock

APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "settings.json"
LOG_DIR = APP_DIR / "logs"
SCREENSHOT_DIR = APP_DIR / "screenshots"
LOG_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR.mkdir(exist_ok=True)

@dataclass
class Settings:
    appearance: str = "dark"
    chrome_debug_port: int = 9222
    action_delay: float = 0.20
    auto_save: bool = True
    result_folder: str = str(APP_DIR / "results")

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})
        except Exception:
            return cls()

    def save(self) -> None:
        SETTINGS_FILE.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

class RuntimeState:
    def __init__(self) -> None:
        self.stop_event = Event()
        self.pause_event = Event()
        self.lock = Lock()
        self.running = False

    def reset(self) -> None:
        self.stop_event.clear()
        self.pause_event.clear()
        self.running = False

runtime = RuntimeState()
settings = Settings.load()
