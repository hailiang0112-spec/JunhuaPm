"""RULE-05 压测脚本（NFR-002 / NFR-009）。

1. 20 个并发用户混合访问：总览、检查点列表、工作项详情、待办，统计 P95；
2. 按 10Mbps 上行限速上传 10MB 照片，统计耗时；
3. 导出含 1000 张照片的证据包，统计耗时。

用法：python perf/load_test.py --base http://127.0.0.1:8090 --project <压测项目ID> --seconds 60
"""
import argparse
import http.cookiejar
import json
import os
import random
import statistics
import threading
import time
import urllib.request

PW = "Jh123456"


class Client:
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def csrf(self):
        return next((c.value for c in self.jar if c.name == "csrftoken"), "")

    def req(self, method, path, body=None, headers=None, data=None):
        h = {"X-CSRFToken": self.csrf(), **(headers or {})}
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        with self.op.open(r, timeout=600) as resp:
            return resp.status, resp.read()

    def login(self, phone):
        self.req("GET", "/api/auth/csrf")
        self.req("POST", "/api/auth/login", {"phone": phone, "password": PW})


def mixed(args):
    lat, errors = [], []
    lock = threading.Lock()
    stop = time.time() + args.seconds
    pid = args.project
    setup = Client(args.base)
    setup.login("13700000001")
    wis = [x["id"] for x in json.loads(setup.req("GET", f"/api/projects/{pid}/work-items")[1])["items"]]
    paths = [f"/api/projects/{pid}/overview", f"/api/projects/{pid}/checkpoints", "/api/todos", "/api/todos/count"]

    def user(i):
        c = Client(args.base)
        c.login(f"1370000{i:04d}")
        rnd = random.Random(i)
        while time.time() < stop:
            path = rnd.choice(paths + ["wi"])
            if path == "wi":
                path = f"/api/projects/{pid}/work-items/{rnd.choice(wis)}/detail"
            t = time.perf_counter()
            try:
                c.req("GET", path)
                ok = True
            except Exception as e:  # noqa: BLE001 — 记录失败请求
                ok = False
                with lock:
                    errors.append(f"{path}: {e}")
            dt = time.perf_counter() - t
            with lock:
                if ok:
                    lat.append((path.split("/")[-1] if "detail" not in path else "detail", dt))

    t0 = time.time()
    ths = [threading.Thread(target=user, args=(i,)) for i in range(20)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    all_l = sorted(x[1] for x in lat)
    p95 = all_l[int(len(all_l) * 0.95) - 1]
    per = {}
    for k, v in lat:
        per.setdefault(k, []).append(v)
    return {"window": f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t0))} 起 {args.seconds}s",
            "users": 20, "samples": len(all_l), "errors": len(errors), "p95_s": round(p95, 3),
            "median_s": round(statistics.median(all_l), 3),
            "per_endpoint_p95_s": {k: round(sorted(v)[int(len(v) * 0.95) - 1], 3) for k, v in per.items()},
            "errorSamples": errors[:5]}


def throttled_upload(args):
    """10MB 照片按 10Mbps 限速分块发送（multipart 流式），统计从开始发送到服务端返回的总耗时。"""
    import http.client
    from urllib.parse import urlparse

    c = Client(args.base)
    c.login("13700000002")
    u = urlparse(args.base)
    payload = os.urandom(10 * 1024 * 1024)
    boundary = "----jhperf"
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"现场大图.jpg\"\r\n"
            "Content-Type: image/jpeg\r\n\r\n").encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    body = head + b"\xff\xd8\xff\xe0" + payload + tail
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=120)
    cookie = "; ".join(f"{x.name}={x.value}" for x in c.jar)
    t = time.perf_counter()
    conn.putrequest("POST", f"/api/projects/{args.project}/files")
    conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
    conn.putheader("Content-Length", str(len(body)))
    conn.putheader("Cookie", cookie)
    conn.putheader("X-CSRFToken", c.csrf())
    conn.endheaders()
    rate = 10_000_000 / 8  # 10Mbps
    chunk = 64 * 1024
    for i in range(0, len(body), chunk):
        conn.send(body[i:i + chunk])
        target = t + (i + chunk) / rate
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
    resp = conn.getresponse()
    status = resp.status
    resp.read()
    return {"size_mb": round(len(body) / 1024 / 1024, 2), "uplink": "10Mbps", "status": status,
            "seconds": round(time.perf_counter() - t, 2)}


def evidence_export(args):
    c = Client(args.base)
    c.login("13800000000")  # 公司管理员
    t = time.perf_counter()
    _, raw = c.req("POST", f"/api/projects/{args.project}/evidence-exports", {"from": args.export_from, "to": args.export_to})
    job = json.loads(raw)
    while job.get("status") not in ("完成", "失败"):
        time.sleep(2)
        job = json.loads(c.req("GET", f"/api/projects/{args.project}/evidence-exports/{job['id']}")[1])
    _, data = c.req("GET", f"/api/projects/{args.project}/evidence-exports/{job['id']}/download")
    return {"status": job["status"], "records": job.get("result", {}).get("count"),
            "photos": job.get("result", {}).get("photoCount"), "zip_mb": round(len(data) / 1024 / 1024, 1),
            "seconds": round(time.perf_counter() - t, 1)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8090")
    ap.add_argument("--project", type=int, required=True)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--export-from", default="")
    ap.add_argument("--export-to", default="")
    ap.add_argument("--only", default="mixed,upload,export")
    a = ap.parse_args()
    out = {}
    if "mixed" in a.only:
        out["mixed"] = mixed(a)
    if "upload" in a.only:
        out["upload"] = throttled_upload(a)
    if "export" in a.only:
        out["export"] = evidence_export(a)
    print(json.dumps(out, ensure_ascii=False, indent=2))
