"""Runtime configuration loaded from environment variables and an optional .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    """Load a minimal ``KEY=VALUE`` .env file without overriding the process env."""

    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _first_env_file() -> Path | None:
    for candidate in (Path.cwd() / ".env", PACKAGE_ROOT / ".env"):
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class Settings:
    """Resolved settings for one SpecAnchor run."""

    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    project_root: Path
    state_dir: Path
    minimax_api_key: str
    minimax_base_url: str
    minimax_model: str
    minimax_reasoning_effort: str

    @classmethod
    def load(cls, *, env_file: Path | None = None) -> "Settings":
        chosen = env_file if env_file is not None else _first_env_file()
        if chosen is not None:
            load_env_file(chosen)

        def env(name: str, default: str = "") -> str:
            return os.environ.get(name, default)

        def path_env(name: str, default: Path) -> Path:
            raw = env(name)
            path = Path(raw) if raw else default
            return path.resolve() if path.is_absolute() else (PACKAGE_ROOT / path).resolve()

        return cls(
            db_host=env("SPECANCHOR_DB_HOST", "127.0.0.1"),
            db_port=int(env("SPECANCHOR_DB_PORT", "2881")),
            db_user=env("SPECANCHOR_DB_USER", "root"),
            db_password=env("SPECANCHOR_DB_PASSWORD", ""),
            db_name=env("SPECANCHOR_DB_NAME", "specanchor"),
            project_root=path_env("SPECANCHOR_PROJECT_ROOT", PACKAGE_ROOT / "sample_project"),
            state_dir=path_env("SPECANCHOR_STATE_DIR", PACKAGE_ROOT / ".state"),
            minimax_api_key=env("MINIMAX_API_KEY", ""),
            minimax_base_url=env("MINIMAX_BASE_URL", "https://api.minimax.cn/v1").rstrip("/"),
            minimax_model=env("MINIMAX_MODEL", "MiniMax-M3.1-Flash"),
            minimax_reasoning_effort=env("MINIMAX_REASONING_EFFORT", "high"),
        )

    @property
    def powercontext_db(self) -> Path:
        return self.state_dir / "powercontext.db"

    def public_summary(self) -> dict[str, object]:
        return {
            "db": f"{self.db_host}:{self.db_port}/{self.db_name}",
            "project_root": str(self.project_root),
            "state_dir": str(self.state_dir),
            "minimax_base_url": self.minimax_base_url,
            "minimax_model": self.minimax_model,
            "minimax_key_configured": bool(self.minimax_api_key),
        }
