"""造数用 HTTP 客户端：登录真实后端（gunicorn，运行账号 app_runtime），带 CSRF 与会话。"""
import io
import os
import uuid

import requests

API = os.environ.get("API", "http://127.0.0.1:8000/api")
PHONES = {"admin": "13800000000", "owner": "13800000001", "owner2": "13800000002", "member": "13800000003",
          "pm": "13800000004", "dm": "13800000005", "qc": "13800000006", "budget": "13800000007"}


class Client:
    def __init__(self, who, password="Jh123456"):
        self.who = who
        self.s = requests.Session()
        self.s.get(API + "/auth/csrf")
        r = self.s.post(API + "/auth/login", json={"phone": PHONES.get(who, who), "password": password},
                        headers={"X-CSRFToken": self.s.cookies["csrftoken"]})
        assert r.status_code == 200, (who, r.status_code, r.text)

    def _h(self, extra=None):
        h = {"X-CSRFToken": self.s.cookies.get("csrftoken", "")}
        h.update(extra or {})
        return h

    def req(self, method, path, json=None, files=None, data=None, ok=(200, 201), headers=None):
        r = self.s.request(method, API + path, json=json, files=files, data=data, headers=self._h(headers))
        if ok and r.status_code not in ok:
            raise AssertionError(f"{self.who} {method} {path} → {r.status_code} {r.text[:400]}")
        ct = r.headers.get("Content-Type", "")
        return r.json() if ct.startswith("application/json") and r.content else r

    def get(self, path, **kw): return self.req("GET", path, **kw)
    def post(self, path, json=None, **kw): return self.req("POST", path, json=json if json is not None else {}, **kw)
    def patch(self, path, json, **kw): return self.req("PATCH", path, json=json, **kw)
    def put(self, path, json, **kw): return self.req("PUT", path, json=json, **kw)
    def delete(self, path, **kw): return self.req("DELETE", path, **kw)

    def upload(self, path, name, content, mime, field="file", extra=None, **kw):
        return self.req("POST", path, files={field: (name, content, mime)}, data=extra or {}, **kw)


def idem():
    return uuid.uuid4().hex


def jpeg(color=(170, 150, 120), label="", size=(640, 480)):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", size, color)
    if label:
        try:
            f = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 36)
        except OSError:
            f = ImageFont.load_default()
        ImageDraw.Draw(im).text((24, 24), label, font=f, fill="white")
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return b.getvalue()


def pdf(label="图纸", size=(1600, 1120)):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", size, "white")
    g = ImageDraw.Draw(im)
    g.rectangle((80, 80, size[0] - 80, size[1] - 160), outline="#374151", width=10)
    g.line((size[0] // 2, 80, size[0] // 2, size[1] - 160), fill="#374151", width=6)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 40)
    except OSError:
        f = ImageFont.load_default()
    g.text((80, size[1] - 120), label, font=f, fill="#111827")
    b = io.BytesIO()
    im.save(b, "PDF", resolution=150)
    return b.getvalue()


def project_id(c, prefix="君华新城"):
    return next(p["id"] for p in c.get("/projects")["items"] if p["name"].startswith(prefix))
