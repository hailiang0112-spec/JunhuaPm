"""运维：文件清单核对、全项目完整性校验、备份与异地同步（技术方案 §7.6，NFR-005）。"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from core.models import Project, StoredFile
from core.services import ledger


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _s3(endpoint, key, secret):
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=key, aws_secret_access_key=secret,
                        config=Config(request_checksum_calculation="when_required"))


def _s3_list(client, bucket, prefix=""):
    out = {}
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            out[o["Key"]] = o["Size"]
    return out


def storage_listing(file_root=None):
    """存储端现有对象 {key: size}。"""
    if settings.FILE_STORAGE == "s3" and file_root is None:
        return _s3_list(_s3(settings.S3_ENDPOINT, settings.S3_ACCESS_KEY, settings.S3_SECRET_KEY), settings.S3_BUCKET)
    root = Path(file_root or settings.FILE_ROOT)
    out = {}
    if root.exists():
        for p in root.rglob("*"):
            if p.is_file():
                out[p.relative_to(root).as_posix()] = p.stat().st_size
    return out


def file_manifest_check(file_root=None):
    """库里登记的文件 vs 存储端：统计「库里有、存储里没有」与「大小不一致」。"""
    listing = storage_listing(file_root)
    missing, mismatch, total = [], [], 0
    for key, size, thumb in StoredFile.objects.values_list("storage_key", "size", "thumb_key").iterator():
        total += 1
        if key not in listing:
            missing.append(key)
        elif listing[key] != size:
            mismatch.append(key)
        if thumb and thumb not in listing:
            missing.append(thumb)
    return {"total": total, "missing": len(missing), "sizeMismatch": len(mismatch),
            "missingKeys": missing[:50], "mismatchKeys": mismatch[:50]}


def verify_all_projects():
    out = []
    for p in Project.objects.order_by("id"):
        r = ledger.verify(p.id)
        out.append({"projectId": p.id, "name": p.name, "result": "完整" if r["ok"] else "异常", "count": r["count"],
                    "firstBad": r["first_bad"]})
    return out


def latest_data_time():
    """库内最后一次写入的时间（操作日志与摘要链取最大值），用于核对恢复后的数据时间点。"""
    with connection.cursor() as cur:
        cur.execute("SELECT GREATEST((SELECT MAX(at) FROM core_auditlog), (SELECT MAX(created_at) FROM core_ledgerentry))")
        return cur.fetchone()[0]


def pg_dump(dest):
    db = settings.DATABASES["default"]
    env = dict(os.environ, PGPASSWORD=db["PASSWORD"])
    subprocess.run(["pg_dump", "-Fc", "-h", db["HOST"], "-p", str(db["PORT"]), "-U", db["USER"], "-d", db["NAME"],
                    "-f", str(dest)], check=True, env=env)


def _snapshot_local_files(day_dir, prev_dir):
    """本地存储模式：把文件目录做成当日快照；与上一份快照相同的文件用硬链接（同 rsync --link-dest）。"""
    src = Path(settings.FILE_ROOT)
    dst = day_dir / "files"
    copied = linked = 0
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        target = dst / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        old = prev_dir / "files" / rel if prev_dir else None
        if old and old.exists() and old.stat().st_size == p.stat().st_size:
            os.link(old, target)
            linked += 1
        else:
            shutil.copy2(p, target)
            copied += 1
    return {"copied": copied, "linked": linked}


class Offsite:
    """异地位置：dir（公司提供的另一台服务器 / NAS 挂载到本机的目录）或 s3（另一个存储桶）。只增不改。"""

    def __init__(self):
        self.kind = settings.OFFSITE_TARGET
        if self.kind == "s3":
            self.client = _s3(settings.OFFSITE_S3_ENDPOINT, settings.OFFSITE_S3_ACCESS_KEY, settings.OFFSITE_S3_SECRET_KEY)
            self.bucket = settings.OFFSITE_S3_BUCKET
        elif self.kind == "dir":
            self.root = Path(settings.OFFSITE_DIR)
            if not self.root.is_dir():
                raise RuntimeError(f"异地目录不可用：{self.root}")
        else:
            raise RuntimeError("未配置异地位置 OFFSITE_TARGET")

    def listing(self, prefix):
        if self.kind == "s3":
            return _s3_list(self.client, self.bucket, prefix)
        base = self.root / prefix
        if not base.exists():
            return {}
        return {p.relative_to(self.root).as_posix(): p.stat().st_size for p in base.rglob("*") if p.is_file()}

    def put(self, key, path):
        if self.kind == "s3":
            self.client.upload_file(str(path), self.bucket, key)
        else:
            t = self.root / key
            t.parent.mkdir(parents=True, exist_ok=True)
            tmp = t.with_name(t.name + ".part")
            shutil.copyfile(path, tmp)
            os.replace(tmp, t)

    def sha256(self, key):
        if self.kind == "s3":
            h = hashlib.sha256()
            for chunk in self.client.get_object(Bucket=self.bucket, Key=key)["Body"].iter_chunks(1024 * 1024):
                h.update(chunk)
            return h.hexdigest()
        return sha256_file(self.root / key)

    def delete_prefix(self, prefix):
        if self.kind == "s3":
            for k in _s3_list(self.client, self.bucket, prefix):
                self.client.delete_object(Bucket=self.bucket, Key=k)
        else:
            shutil.rmtree(self.root / prefix, ignore_errors=True)


def sync_offsite(day, day_dir):
    """把当日数据库备份、核对报告和（本地模式的）文件同步到异地，并重新列出、比对本次上传对象的 SHA-256。"""
    off = Offsite()
    uploads = {}  # 异地键 -> 本地路径
    for name in ("jh.dump", "manifest.json"):
        uploads[f"backups/{day}/{name}"] = day_dir / name
    existing = off.listing("files/")
    files_dir = day_dir / "files"
    if files_dir.exists():
        for p in files_dir.rglob("*"):
            if p.is_file():
                key = "files/" + p.relative_to(files_dir).as_posix()
                if existing.get(key) != p.stat().st_size:
                    uploads[key] = p
    for key, path in uploads.items():
        off.put(key, path)
    listed = {**off.listing(f"backups/{day}/"), **off.listing("files/")}
    bad = [k for k, p in uploads.items() if listed.get(k) != p.stat().st_size or off.sha256(k) != sha256_file(p)]
    # 异地副本同样保留 30 天（只清理按日期的数据库备份；文件按内容哈希命名、只增不删，与生产文件一致）
    cutoff = (timezone.localdate() - datetime.timedelta(days=settings.BACKUP_KEEP_DAYS)).isoformat()
    for k in {k.split("/")[1] for k in off.listing("backups/")}:
        if k < cutoff:
            off.delete_prefix(f"backups/{k}/")
    return {"target": off.kind, "uploaded": len(uploads), "verifyFailed": bad[:50], "ok": not bad}


def cert_days_left():
    if not settings.CERT_FILE or not Path(settings.CERT_FILE).exists():
        return None
    import ssl
    info = ssl._ssl._test_decode_cert(settings.CERT_FILE)  # noqa: SLF001 — 标准库内置的证书解析，无需额外依赖
    end = datetime.datetime.strptime(info["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=datetime.timezone.utc)
    return (end - timezone.now()).days


def yesterday_error_count():
    path = settings.ERROR_LOG_SUMMARY_FILE
    if not path or not Path(path).exists():
        return None
    y = (timezone.localdate() - datetime.timedelta(days=1)).isoformat()
    with open(path, encoding="utf-8", errors="replace") as f:
        return sum(1 for line in f if line.startswith(y) and " ERROR " in line)


def run_backup(log):
    """每日备份：pg_dump → SHA-256 → 文件清单核对 → 本地快照 / S3 上传 → 异地同步 → 保留 30 天。返回报告。"""
    day = timezone.localdate().isoformat()
    root = Path(settings.BACKUP_DIR)
    day_dir = root / day
    day_dir.mkdir(parents=True, exist_ok=True)
    report = {"date": day, "startedAt": timezone.localtime().isoformat(), "storage": settings.FILE_STORAGE}

    dump = day_dir / "jh.dump"
    pg_dump(dump)
    report["dump"] = {"file": "jh.dump", "size": dump.stat().st_size, "sha256": sha256_file(dump)}
    t = latest_data_time()
    report["dataTime"] = timezone.localtime(t).isoformat() if t else None
    report["manifestCheck"] = file_manifest_check()
    if report["manifestCheck"]["missing"] or report["manifestCheck"]["sizeMismatch"]:
        log.error("文件清单核对异常：缺失 %s，大小不一致 %s", report["manifestCheck"]["missing"],
                  report["manifestCheck"]["sizeMismatch"])
    report["certDaysLeft"] = cert_days_left()
    if report["certDaysLeft"] is not None and report["certDaysLeft"] < 15:
        log.warning("HTTPS 证书剩余 %s 天，请尽快续签", report["certDaysLeft"])
    report["errorsYesterday"] = yesterday_error_count()
    (day_dir / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if settings.FILE_STORAGE == "local":
        prev = sorted(d for d in root.iterdir() if d.is_dir() and d.name < day)
        report["snapshot"] = _snapshot_local_files(day_dir, prev[-1] if prev else None)
    else:
        client = _s3(settings.S3_ENDPOINT, settings.S3_ACCESS_KEY, settings.S3_SECRET_KEY)
        for name in ("jh.dump", "manifest.json"):
            client.upload_file(str(day_dir / name), settings.S3_BUCKET, f"backups/{day}/{name}")
        report["uploadedToBucket"] = True
        cutoff = (timezone.localdate() - datetime.timedelta(days=settings.BACKUP_KEEP_DAYS)).isoformat()
        for k in _s3_list(client, settings.S3_BUCKET, "backups/"):
            if k.split("/")[1] < cutoff:
                client.delete_object(Bucket=settings.S3_BUCKET, Key=k)

    report["offsite_synced"] = False
    if settings.OFFSITE_TARGET:
        try:
            report["offsite"] = sync_offsite(day, day_dir)
            report["offsite_synced"] = report["offsite"]["ok"]
            if not report["offsite_synced"]:
                log.error("异地同步失败：校验不一致 %s", report["offsite"]["verifyFailed"])
        except Exception as e:  # noqa: BLE001 — 记 ERROR 并写入报告，次日任务重试补齐
            report["offsite"] = {"ok": False, "error": str(e)}
            log.error("异地同步失败：%s", e)
    elif settings.FILE_STORAGE == "local":
        log.error("本地存储模式未配置异地备份位置（OFFSITE_TARGET），不满足 NFR-005")

    cutoff = (timezone.localdate() - datetime.timedelta(days=settings.BACKUP_KEEP_DAYS)).isoformat()
    report["expired"] = [d.name for d in root.iterdir() if d.is_dir() and d.name < cutoff]
    for name in report["expired"]:
        shutil.rmtree(root / name)
    report["finishedAt"] = timezone.localtime().isoformat()
    (day_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
