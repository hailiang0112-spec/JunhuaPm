"""Serve the built frontend from the same origin as the API.

The desktop window loads http://127.0.0.1:<port>/ so session cookies and CSRF
stay same-origin. Unknown paths fall through to index.html for the client router.
"""
import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse

_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".map": "application/json",
    ".html": "text/html; charset=utf-8",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


def _dist():
    raw = getattr(settings, "JH_FRONTEND_DIST", "") or ""
    if not raw:
        return None
    return Path(raw).resolve()


def spa(request, asset_path=""):
    dist = _dist()
    if dist is None or not dist.is_dir():
        return HttpResponse("前端资源缺失", status=500, content_type="text/plain; charset=utf-8")
    rel = asset_path.lstrip("/")
    if rel:
        candidate = (dist / rel).resolve()
        if dist == candidate or dist in candidate.parents:
            if candidate.is_file():
                suffix = candidate.suffix.lower()
                content_type = _TYPES.get(suffix) or mimetypes.guess_type(candidate.name)[0]
                resp = FileResponse(candidate.open("rb"), content_type=content_type)
                if rel.startswith("assets/"):
                    resp["Cache-Control"] = "public, max-age=2592000, immutable"
                return resp
        if Path(rel).suffix:
            raise Http404()
    index = dist / "index.html"
    if not index.is_file():
        return HttpResponse("前端资源缺失", status=500, content_type="text/plain; charset=utf-8")
    resp = FileResponse(index.open("rb"), content_type="text/html; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    return resp
