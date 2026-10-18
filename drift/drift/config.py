"""User settings, stored as JSON in %APPDATA%\\Drift\\settings.json."""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

MODIFIERS = ("shift", "ctrl", "alt")


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = base / "Drift"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    path = base / "Drift"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    # Modifier held during a drag to open the convert wheel.
    trigger_modifier: str = "shift"
    # Extra modifier (together with the trigger) that opens the tools wheel.
    tools_modifier: str = "ctrl"
    wheel_diameter: int = 340
    # Debug: tint the invisible probe window so you can see where it is.
    debug_show_probe: bool = False
    # Filled in by later phases.
    output_folder: str = ""
    jpeg_quality: int = 85
    start_on_boot: bool = False

    @classmethod
    def load(cls) -> "Settings":
        path = config_dir() / "settings.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            log.warning("Could not read %s (%s); using defaults", path, exc)
            return cls()
        known = {f.name for f in fields(cls)}
        settings = cls(**{k: v for k, v in data.items() if k in known})
        if settings.trigger_modifier not in MODIFIERS:
            settings.trigger_modifier = "shift"
        if settings.tools_modifier not in MODIFIERS or settings.tools_modifier == settings.trigger_modifier:
            settings.tools_modifier = "ctrl" if settings.trigger_modifier != "ctrl" else "alt"
        return settings

    def save(self) -> None:
        path = config_dir() / "settings.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)
