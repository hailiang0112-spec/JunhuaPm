# 运维演练记录 · RULE-06 备份与恢复（NFR-005）

- 演练时间：2026-10-27 14:35–14:40（北京时间）
- 执行人：主开发 Agent（刘老师项目）
- 依据：技术方案 §7.6；脚本 `app/backend/core/management/commands/backup_run.py`、`verify_restore.py`、`app/deploy/restore_drill.sh`

## 一、本地存储模式（Docker Compose 全栈，异地位置 = 挂载目录）

| 步骤 | 命令 | 结果 |
| :--- | :--- | :--- |
| 1. 造数 | `docker compose exec -T web python manage.py seed_demo` | 演示项目 1，47 条关键记录，23 个文件 |
| 2. 每日备份 | `docker compose exec -T backup python manage.py backup_run` | 退出码 0；`jh.dump` 328295 字节，SHA-256 已记录；文件清单 total=23 missing=0 sizeMismatch=0；快照复制 32 个对象；`offsite_synced=true`，异地上传 34 个对象，校验失败 0 |
| 3. 保留 30 天 | 预置本地与异地各一份 `2026-09-20` 过期备份后再次执行 `backup_run` | `expired=['2026-09-20']`；本地与异地目录只剩 `2026-10-27` |
| 4. 从异地副本恢复 | `deploy/restore_drill.sh /home/user/jh_smoke/offsite` | 退出码 0；备份文件 SHA-256 与清单一致；临时 Postgres 18 容器恢复；授权自检通过（16 张关键记录表仅 SELECT/INSERT）；项目 1 完整性校验「完整」（47 条）；文件清单 missing=0；数据时间点与备份差 0.0 小时 |

## 二、对象存储模式（S3 兼容对象存储 RustFS，异地位置 = 另一存储桶）

| 步骤 | 命令 | 结果 |
| :--- | :--- | :--- |
| 1. 造数 | `FILE_STORAGE=s3 … manage.py seed_demo`（文件写入桶 `jh-files`） | 23 个文件对象 |
| 2. 每日备份 | `FILE_STORAGE=s3 OFFSITE_TARGET=s3 … manage.py backup_run` | 退出码 0；`uploadedToBucket=true`（`backups/2026-10-27/`）；文件清单 missing=0；`offsite_synced=true`（桶 `jh-offsite`，校验失败 0） |
| 3. 从异地桶恢复 | 下载 `jh-offsite/backups/2026-10-27/jh.dump` → `pg_restore` 到空库 `jh_s3_restore` → `check_grants` → `verify_restore --report manifest.json` | SHA-256 一致；授权自检通过；完整性校验「完整」；文件清单 missing=0；数据时间点差 0.0 小时；退出码 0 |

## 说明
- 对象存储演练使用开源 S3 兼容服务 RustFS 本地实例（协议与生产对象存储一致）；云厂商对象存储确定后，需在上线前用正式桶再跑一遍第二部分。
- 异地位置的两种实现：`dir`（公司提供的另一台服务器或 NAS，挂载到本机目录）与 `s3`（另一个存储桶）。原方案中的 ssh + rsync 改为挂载目录，原因是镜像离线构建、不引入 rsync/ssh 依赖；效果等价（只增不改、逐对象 SHA-256 校验）。
