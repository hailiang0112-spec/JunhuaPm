# 部署与试用

只需要 Docker（含 Docker Compose）和 Git，本机不用装 Python 或 Node.js。

## 本机试用（约 20 分钟）

1. 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/) 并启动；安装 [Git](https://git-scm.com/downloads)。
2. 取代码并准备配置：
   ```
   git clone https://github.com/hailiang0112-spec/JunhuaPm.git
   cd JunhuaPm/app/deploy
   cp .env.example .env
   ```
3. 用记事本打开 `.env`，本机试用按下表修改（其余保持不变）：

   | 配置项 | 本机试用填写 |
   | :--- | :--- |
   | `POSTGRES_PASSWORD`、`APP_OWNER_PASSWORD`、`APP_RUNTIME_PASSWORD` | 各填一个字母加数字的密码 |
   | `DJANGO_SECRET_KEY` | 一串随机字符（30 位以上） |
   | `ALLOWED_HOSTS` | `*` |
   | `CSRF_TRUSTED_ORIGINS` | `http://localhost:8080` |
   | `COOKIE_SECURE` | `0` |
   | `HTTP_PORT` | `8080` |
   | `FILE_STORAGE` | `local` |
   | `SEED_BASE` | `1` |

4. 构建并启动（首次构建需要联网下载依赖，约 5–10 分钟）：
   ```
   docker compose build
   docker compose up -d
   docker compose exec web python manage.py seed_demo
   ```
5. 浏览器打开 <http://localhost:8080>，用演示账号登录（密码均为 `Jh123456`）：

   | 手机号 | 姓名 | 身份 |
   | :--- | :--- | :--- |
   | 13800000001 | 刘先生 | 业主 |
   | 13800000004 | 张工 | 项目经理 |
   | 13800000006 | 王工 | 质检 |
   | 13800000005 | 李工 | 设计经理 |
   | 13800000007 | 赵会计 | 预算专员 |
   | 13800000003 | 钱工 | 业主方成员（放行代理人） |
   | 13800000000 | 周经理 | 公司管理员 |

停止：`docker compose down`（数据保留）；清空数据重来：`docker compose down -v`。

## 正式部署（公司云服务器）

- 服务器建议 4 vCPU / 8 GiB、数据盘 ≥ 100GB，装好 Docker 后按上面第 2–4 步执行，但 `.env` 按真实环境填写：
  - `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` 填正式域名，`COOKIE_SECURE=1`，`HTTP_PORT=80`，Nginx 前配置 HTTPS 证书；
  - 文件存储推荐 `FILE_STORAGE=s3` 并填写对象存储；若用 `local`，必须配置异地备份 `OFFSITE_TARGET`；
  - `SEED_BASE=0`，不要执行 `seed_demo`；由公司管理员账号新建项目并邀请真实成员（首个管理员账号可在 web 容器里用 `python manage.py shell` 创建）。
- 每日 02:30 自动备份；恢复演练：`./restore_drill.sh <备份目录>`（见 `output/tests/运维演练记录-RULE-06.md`）。

## Mac 免安装桌面版

不需要 Docker。Apple 芯片 Mac 可下载双击运行的 `JunhuaPm.app`（内置本地数据库与演示账号）。下载、第一次打开和数据位置见 [desktop/使用说明.md](../../desktop/使用说明.md)。公司服务器部署仍用上面的 Docker。

## 常见问题

- **Windows 上 `docker compose build` 报 `entrypoint.sh: not found`**：仓库已用 `.gitattributes` 固定 `.sh` 为 LF 换行；若仍出现，执行 `git config --global core.autocrlf input` 后重新克隆。
- **网络受限、构建时下载依赖失败**：在能联网的机器上执行 `./build.sh`（需要 Python 3.13 与 Node.js 22），会预先下载依赖并构建前端，之后镜像构建不再联网。
