"""Python Playwright E2E 记分器：检查项计数、控制台错误、375 页面级横向滚动、截图，结果写 result.json。"""
import json
import os
import re
import sys
import time
import traceback

from playwright.sync_api import sync_playwright

WEB = os.environ.get("WEB", "http://127.0.0.1:5173")
PWD = "Jh123456"
PHONES = {"admin": "13800000000", "owner": "13800000001", "owner2": "13800000002", "member": "13800000003",
          "pm": "13800000004", "dm": "13800000005", "qc": "13800000006", "budget": "13800000007"}


class Run:
    def __init__(self, out_dir, expected_http=()):
        self.out = out_dir
        self.shots = os.path.join(out_dir, "shots")
        os.makedirs(self.shots, exist_ok=True)
        self.checks = []          # (flow, name, ok, detail)
        self.console = []         # 未预期的控制台错误
        self.expected_console = []  # 明确预期的业务 4xx 网络日志
        self.hscroll = []         # (label, width, scrollWidth, clientWidth)
        self.expected_http = [re.compile(x) for x in expected_http]
        self.flow = ""
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch()
        self.t0 = time.time()

    # —— 记分 ——
    def check(self, name, cond, detail=""):
        ok = bool(cond)
        self.checks.append({"flow": self.flow, "name": name, "ok": ok, "detail": str(detail)[:300]})
        print(("PASS " if ok else "FAIL ") + f"[{self.flow}] {name}" + (f" · {str(detail)[:200]}" if detail and not ok else ""), flush=True)
        return ok

    def step(self, name, fn):
        """执行一个步骤；抛异常记为 1 个失败检查项并继续后续步骤。"""
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - 失败作为检查项记录
            self.check(f"{name}（步骤异常）", False, f"{type(e).__name__}: {(str(e).splitlines() or [""])[0][:240]}")
            traceback.print_exc(limit=2)

    # —— 浏览器 ——
    def ctx(self, who, width=1440, login="ui", password=PWD, expect=(), **kw):
        ctx = self.browser.new_context(viewport={"width": width, "height": 900 if width > 500 else 812},
                                       timezone_id="Asia/Shanghai", locale="zh-CN", accept_downloads=True, **kw)
        page = ctx.new_page()
        tag = f"{who}@{width}"
        self._watch(page, tag, [re.compile(x) for x in expect])
        if login == "ui":
            page.goto(WEB + "/login")
            page.fill("#phone", PHONES.get(who, who))
            page.fill("#pwd", password)
            page.click("button[type=submit]")
            page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
            page.wait_for_load_state("networkidle")
        return ctx, page

    def _watch(self, page, tag, extra=()):
        def on_console(m):
            if m.type != "error":
                return
            txt = m.text
            if "Failed to load resource" in txt and any(p.search(txt) or p.search(m.location.get("url", "")) for p in list(self.expected_http) + list(extra)):
                self.expected_console.append(f"[{tag}] {m.location.get('url', '')} {txt}")
                return
            self.console.append(f"[{tag}] {page.url} {txt} {m.location.get('url', '')}")
        page.on("console", on_console)
        page.on("pageerror", lambda e: self.console.append(f"[{tag}] {page.url} pageerror {e}"))

    def hs(self, page, label, width=None):
        w = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        width = width or page.viewport_size["width"]
        rec = {"label": label, "width": width, "scrollWidth": w[0], "clientWidth": w[1], "overflow": w[0] > w[1]}
        self.hscroll.append(rec)
        return not rec["overflow"]

    def shot(self, page, name, full=True):
        page.wait_for_timeout(300)
        p = os.path.join(self.shots, f"{name}.png")
        page.screenshot(path=p, full_page=full)
        return p

    def toast(self, page, text, timeout=8000):
        try:
            page.locator(".toast", has_text=text).first.wait_for(timeout=timeout)
            return True
        except Exception:
            return False

    def finish(self, extra=None):
        self.browser.close()
        self.pw.stop()
        passed = sum(c["ok"] for c in self.checks)
        res = {"passed": passed, "total": len(self.checks), "failed": [c for c in self.checks if not c["ok"]],
               "byFlow": {}, "consoleErrors": self.console, "expectedBusiness4xx": self.expected_console,
               "hscroll375": [h for h in self.hscroll if h["width"] <= 400],
               "hscrollOverflow": [h for h in self.hscroll if h["overflow"]],
               "seconds": round(time.time() - self.t0, 1), "checks": self.checks}
        for c in self.checks:
            f = res["byFlow"].setdefault(c["flow"], {"passed": 0, "total": 0})
            f["total"] += 1
            f["passed"] += c["ok"]
        if extra:
            res.update(extra)
        with open(os.path.join(self.out, "result.json"), "w") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
        print(f"\n检查项 {passed}/{len(self.checks)} 通过；未预期控制台错误 {len(self.console)}；"
              f"375 页面级横向滚动 {sum(h['overflow'] for h in res['hscroll375'])}/{len(res['hscroll375'])} 处")
        for e in self.console:
            print("  CONSOLE", e[:300])
        for h in res["hscrollOverflow"]:
            print("  HSCROLL", h)
        sys.exit(0 if passed == len(self.checks) and not self.console and not any(h["overflow"] for h in res["hscroll375"]) else 1)
