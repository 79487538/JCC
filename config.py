import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"


def load_env_file(path: Path = ENV_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


_ENV_FILE_VALUES = load_env_file()


def get_config_value(key: str, default: str) -> str:
    return os.getenv(key) or _ENV_FILE_VALUES.get(key) or default


def get_bool_config(key: str, default: bool) -> bool:
    raw_value = get_config_value(key, str(default).lower()).strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


SERVER_HOST = get_config_value("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(get_config_value("SERVER_PORT", "8000"))
API_BASE_URL = get_config_value("API_BASE_URL", f"http://{SERVER_HOST}:{SERVER_PORT}")
AI_PROVIDER = get_config_value("AI_PROVIDER", "deepseek").lower()
ENABLE_AI = get_bool_config("ENABLE_AI", False)
