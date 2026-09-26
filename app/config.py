import contextlib
import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Carrega um arquivo .env simples (CHAVE=valor) sem sobrescrever o ambiente."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "sim", "yes", "on")


def _secret_key(data_dir: str) -> str:
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = Path(data_dir) / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    path.write_text(key, encoding="utf-8")
    # No Windows o chmod não restringe a leitura; ali a proteção vem das
    # permissões da pasta de dados.
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return key


def load_config(app, test_config=None) -> None:
    _load_dotenv(BASE_DIR / ".env")
    test_config = dict(test_config or {})

    data_dir = test_config.get("DATA_DIR") or os.environ.get("CHAMADOS_DATA_DIR") or str(BASE_DIR / "data")
    data_dir = os.path.abspath(data_dir)
    os.makedirs(data_dir, exist_ok=True)

    config = {
        "DATA_DIR": data_dir,
        "UPLOAD_DIR": os.path.join(data_dir, "anexos"),
        "SQLALCHEMY_DATABASE_URI": os.environ.get("DATABASE_URL")
        or "sqlite:///" + os.path.join(data_dir, "chamados.db"),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "MAX_CONTENT_LENGTH": int(os.environ.get("MAX_UPLOAD_MB", "20")) * 1024 * 1024,
        "BASE_URL": os.environ.get("BASE_URL", "").rstrip("/"),
        "PROXY_FIX": _env_bool("PROXY_FIX"),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": _env_bool("SESSION_COOKIE_SECURE"),
        "REMEMBER_COOKIE_HTTPONLY": True,
        "REMEMBER_COOKIE_DURATION": timedelta(days=14),
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=12),
        "WTF_CSRF_TIME_LIMIT": None,
        "PER_PAGE": 25,
    }
    config.update(test_config)
    if "SECRET_KEY" not in config:
        config["SECRET_KEY"] = _secret_key(data_dir)
    app.config.update(config)
