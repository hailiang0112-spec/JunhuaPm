#!/bin/bash
# FLOW 浏览器 E2E 公共环境：建库 → 迁移 → 起服务 / 停服务。被各模块 run.sh source。
# 用法（在 run.sh 中）：MOD=acct BPORT=8101 FPORT=5201; source ../_lib/env.sh
set -euo pipefail
ROOT=/home/user/君华别墅装修项目管理平台
APP=$ROOT/app
FLOWS=$ROOT/output/tests/e2e/flows
LIB=$FLOWS/_lib
export DB_NAME=jh_e2e_$MOD
export FILE_ROOT=/home/user/jh_e2e_${MOD}_files
export DB_HOST=127.0.0.1
export DJANGO_DEBUG=0 ALLOWED_HOSTS='*'
export API=http://127.0.0.1:$BPORT/api WEB=http://127.0.0.1:$FPORT
OUT=$FLOWS/$MOD
LOGS=$OUT/logs
mkdir -p "$LOGS"

free_port() {  # 端口被旧进程占用就结束它
  local pids; pids=$(lsof -t -iTCP:"$1" -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$pids" ]; then echo "端口 $1 被 $pids 占用，结束旧进程"; kill $pids 2>/dev/null || true; sleep 2; fi
}

setup_db() {  # 新建干净数据库；app_owner 迁移
  free_port "$BPORT"; free_port "$FPORT"
  PGPASSWORD=app_owner_pw dropdb -h 127.0.0.1 -U app_owner --if-exists "$DB_NAME"
  PGPASSWORD=app_owner_pw createdb -h 127.0.0.1 -U app_owner "$DB_NAME"
  rm -rf "$FILE_ROOT"; mkdir -p "$FILE_ROOT"
  (cd "$APP/backend" && . .venv/bin/activate && DB_USER=app_owner DB_PASSWORD=app_owner_pw python manage.py migrate -v 0)
  echo "已建库 $DB_NAME 并迁移"
}

manage_rt() {  # 以运行账号 app_runtime 执行 manage.py（造数）
  (cd "$APP/backend" && . .venv/bin/activate && DB_USER=app_runtime DB_PASSWORD=app_runtime_pw python manage.py "$@")
}

start_services() {  # gunicorn（app_runtime）+ vite preview（生产构建 dist）
  free_port "$BPORT"; free_port "$FPORT"
  (cd "$APP/backend" && . .venv/bin/activate && DB_USER=app_runtime DB_PASSWORD=app_runtime_pw \
    setsid nohup gunicorn jh.wsgi:application --bind 127.0.0.1:$BPORT --workers 2 --threads 4 --worker-class gthread \
    --timeout 300 --pid "$LOGS/gunicorn.pid" > "$LOGS/backend.log" 2>&1 < /dev/null &)
  (cd "$APP/frontend" && API_PORT=$BPORT setsid nohup npx vite preview --host 127.0.0.1 --port $FPORT --strictPort \
    > "$LOGS/frontend.log" 2>&1 < /dev/null &)
  for i in $(seq 1 60); do
    if curl -sf -o /dev/null "$WEB/api/auth/csrf" && curl -sf -o /dev/null "$WEB/login"; then echo "服务就绪 后端 $BPORT 前端 $FPORT"; return 0; fi
    sleep 1
  done
  echo "服务启动超时"; tail -20 "$LOGS/backend.log" "$LOGS/frontend.log"; return 1
}

stop_services() {
  free_port "$BPORT"; free_port "$FPORT"
  echo "已停止 $BPORT / $FPORT"
}

# —— 排查用：造数后快照、恢复到快照（run.sh 不调用）
SNAP=/tmp/claude-0/-home-user/31f894a9-a54f-5777-8ee2-8adeb0ee0cf3/scratchpad/e2e_snap
snapshot() { mkdir -p $SNAP; PGPASSWORD=app_owner_pw pg_dump -Fc -h 127.0.0.1 -U app_owner "$DB_NAME" -f $SNAP/$MOD.dump; rm -rf $SNAP/${MOD}_files; cp -a "$FILE_ROOT" $SNAP/${MOD}_files; cp "$OUT/seed.json" $SNAP/$MOD.seed.json 2>/dev/null || true; echo 快照完成; }
restore() {
  free_port "$BPORT"
  PGPASSWORD=app_owner_pw dropdb -h 127.0.0.1 -U app_owner --if-exists "$DB_NAME"
  PGPASSWORD=app_owner_pw createdb -h 127.0.0.1 -U app_owner "$DB_NAME"
  PGPASSWORD=app_owner_pw pg_restore -h 127.0.0.1 -U app_owner -d "$DB_NAME" $SNAP/$MOD.dump
  rm -rf "$FILE_ROOT"; cp -a $SNAP/${MOD}_files "$FILE_ROOT"; cp $SNAP/$MOD.seed.json "$OUT/seed.json" 2>/dev/null || true
  echo 已恢复快照
}
