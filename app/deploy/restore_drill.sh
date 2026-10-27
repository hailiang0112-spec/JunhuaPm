#!/bin/sh
# 恢复演练（技术方案 §7.6，NFR-005）：在临时 Postgres 容器里恢复最近一次备份，执行完整性校验与文件清单核对。
# 用法：deploy/restore_drill.sh <备份根目录>
#   本地存储模式必须传异地副本目录（含 backups/<日期>/ 与 files/），模拟本服务器整体损毁。
#   对象存储模式传本机备份目录（含 <日期>/jh.dump），文件核对直接查对象存储。
set -e
SRC=$(cd "$1" && pwd)
cd "$(dirname "$0")"
[ -f .env ] && . ./.env
if [ -d "$SRC/backups" ]; then DAY_DIR=$(ls -d "$SRC"/backups/*/ | sort | tail -1); FILES="$SRC/files"; else DAY_DIR=$(ls -d "$SRC"/*/ | sort | tail -1); FILES=""; fi
DAY_DIR=${DAY_DIR%/}
echo "使用备份：$DAY_DIR"
WANT=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['dump']['sha256'])" "$DAY_DIR/manifest.json")
GOT=$(sha256sum "$DAY_DIR/jh.dump" | cut -d' ' -f1)
[ "$WANT" = "$GOT" ] || { echo "备份文件 SHA-256 不一致"; exit 1; }
echo "备份文件 SHA-256 一致：$GOT"

NET=jh-drill-$$; PG=jh-drill-pg-$$
docker network create $NET >/dev/null
trap 'docker rm -f $PG >/dev/null 2>&1; docker network rm $NET >/dev/null 2>&1' EXIT
docker run -d --name $PG --network $NET -e POSTGRES_PASSWORD=drill -e APP_OWNER_PASSWORD=drill_owner \
  -e APP_RUNTIME_PASSWORD=drill_runtime -v "$(pwd)/initdb:/docker-entrypoint-initdb.d:ro" postgres:18 >/dev/null
until docker exec $PG pg_isready -U postgres -d jh >/dev/null 2>&1 && docker exec $PG psql -U postgres -d jh -c 'select 1' >/dev/null 2>&1; do sleep 1; done
docker cp "$DAY_DIR/jh.dump" $PG:/tmp/jh.dump
docker exec $PG pg_restore -U postgres -d jh --no-owner --role=app_owner /tmp/jh.dump
# 恢复后重新执行授权（GRANT 随转储恢复；再跑一次迁移与授权自检确认运行账号权限正确）
IMG=$(docker compose images -q web 2>/dev/null | head -1)
[ -n "$IMG" ] || IMG=deploy-web
RUN="docker run --rm --network $NET -e DB_HOST=$PG -e DB_NAME=jh -e DB_USER=app_owner -e DB_PASSWORD=drill_owner \
  -e FILE_STORAGE=${FILE_STORAGE:-local} -e S3_ENDPOINT=$S3_ENDPOINT -e S3_BUCKET=$S3_BUCKET -e S3_ACCESS_KEY=$S3_ACCESS_KEY \
  -e S3_SECRET_KEY=$S3_SECRET_KEY -v $DAY_DIR:/drill/day:ro"
[ -n "$FILES" ] && RUN="$RUN -v $FILES:/drill/files:ro"
$RUN $IMG python manage.py check_grants
if [ -n "$FILES" ]; then
  $RUN $IMG python manage.py verify_restore --file-root /drill/files --report /drill/day/manifest.json
else
  $RUN $IMG python manage.py verify_restore --report /drill/day/manifest.json
fi
