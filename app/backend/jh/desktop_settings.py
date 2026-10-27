"""Local desktop settings.

Selected with DJANGO_SETTINGS_MODULE=jh.desktop_settings. The server deploy
keeps using jh.settings and PostgreSQL. This module only swaps in SQLite and
pins the process to loopback so a double-clicked Mac app needs no database
server.
"""
import os
from pathlib import Path

_data = Path(os.environ.get(
    "JH_DATA_DIR",
    Path.home() / "Library" / "Application Support" / "JunhuaPm",
))
_data.mkdir(parents=True, exist_ok=True)
(_data / "files").mkdir(exist_ok=True)
(_data / "logs").mkdir(exist_ok=True)

os.environ.setdefault("FILE_STORAGE", "local")
os.environ.setdefault("FILE_ROOT", str(_data / "files"))
os.environ.setdefault("ERROR_LOG_FILE", str(_data / "logs" / "error.log"))
os.environ.setdefault("BACKUP_DIR", str(_data / "backups"))
os.environ.setdefault("JOBS_INLINE", "1")
os.environ.setdefault("DJANGO_DEBUG", "0")
# testserver: seed_demo uses Django's APIClient, whose default host is testserver.
os.environ.setdefault("ALLOWED_HOSTS", "127.0.0.1,localhost,testserver")
os.environ.setdefault("COOKIE_SECURE", "0")

from jh.settings import *  # noqa: E402,F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("JH_SQLITE", str(_data / "jh.sqlite3")),
        "OPTIONS": {"timeout": 30},
    }
}
DEBUG = False
ALLOWED_HOSTS = [h.strip() for h in os.environ.get(
    "ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",") if h.strip()]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
JOBS_INLINE = True
FILE_STORAGE = "local"
FILE_ROOT = Path(os.environ["FILE_ROOT"])
JH_FRONTEND_DIST = os.environ.get("JH_FRONTEND_DIST", "")
JH_DATA_DIR = _data
