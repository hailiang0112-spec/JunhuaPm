"""Start the desktop backend: migrate, seed demo data, serve UI and API on 127.0.0.1.

Prints a single line `JH_READY <port>` when the server is accepting connections.
The Electron shell waits for that line. Data lives under JH_DATA_DIR
(the app sets this to ~/Library/Application Support/JunhuaPm).
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _cmdline(pid):
    proc = Path(f"/proc/{pid}/cmdline")
    try:
        return proc.read_bytes().replace(b"\x00", b" ").decode(errors="replace")
    except OSError:
        pass
    try:
        return subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
    except (OSError, subprocess.CalledProcessError):
        return ""


def _take_pidfile(data: Path):
    """If a previous desktop backend is still running, stop it so SQLite is free."""
    pidfile = data / "backend.pid"
    if pidfile.exists():
        try:
            old = int(pidfile.read_text().strip())
        except ValueError:
            old = 0
        if old and old != os.getpid():
            cmd = _cmdline(old)
            if "jh.desktop_serve" in cmd or "desktop_serve" in cmd:
                try:
                    os.kill(old, signal.SIGTERM)
                except OSError:
                    pass
                for _ in range(20):
                    try:
                        os.kill(old, 0)
                    except OSError:
                        break
                    time.sleep(0.1)
    pidfile.write_text(str(os.getpid()))


def _secret(data: Path) -> str:
    path = data / "secret.key"
    if path.exists():
        text = path.read_text().strip()
        if text:
            return text
    import secrets
    text = secrets.token_urlsafe(48)
    path.write_text(text + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return text


def configure_env():
    data = Path(os.environ.get(
        "JH_DATA_DIR",
        Path.home() / "Library" / "Application Support" / "JunhuaPm",
    ))
    data.mkdir(parents=True, exist_ok=True)
    (data / "files").mkdir(exist_ok=True)
    (data / "logs").mkdir(exist_ok=True)
    os.environ["JH_DATA_DIR"] = str(data)
    os.environ["JH_DESKTOP"] = "1"
    os.environ["DJANGO_SETTINGS_MODULE"] = "jh.desktop_settings"
    os.environ["DJANGO_SECRET_KEY"] = _secret(data)
    os.environ.setdefault("DJANGO_DEBUG", "0")
    os.environ.setdefault("FILE_STORAGE", "local")
    os.environ.setdefault("FILE_ROOT", str(data / "files"))
    os.environ.setdefault("ERROR_LOG_FILE", str(data / "logs" / "error.log"))
    os.environ.setdefault("JOBS_INLINE", "1")
    _take_pidfile(data)
    return data


def _enable_sqlite_wal():
    from django.db.backends.signals import connection_created

    def _pragmas(sender, connection, **kwargs):
        if connection.vendor != "sqlite":
            return
        with connection.cursor() as cur:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.fetchone()
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=30000")

    connection_created.connect(_pragmas)


def main():
    configure_env()
    import django
    django.setup()
    _enable_sqlite_wal()
    from django.conf import settings
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=1)
    seed = os.environ.get("JH_SEED", "demo")
    if seed not in ("0", "off", "no"):
        call_command("seed_base")
        if seed not in ("base",):
            try:
                call_command("seed_demo")
            except Exception as exc:  # noqa: BLE001 — base accounts still let the app open
                print(f"JH_SEED_DEMO_WARN {exc}", flush=True)

    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

    from jh.wsgi import application

    class Server(ThreadingMixIn, WSGIServer):
        daemon_threads = True
        allow_reuse_address = True

    class Handler(WSGIRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    httpd = make_server("127.0.0.1", 0, application, server_class=Server, handler_class=Handler)
    port = httpd.server_address[1]
    settings.CSRF_TRUSTED_ORIGINS = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]
    print(f"JH_READY {port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — the shell shows this line in the error dialog
        print(f"JH_FAIL {exc}", flush=True)
        raise
