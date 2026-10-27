#!/bin/sh
# web：迁移用 app_owner（拥有表），运行用 app_runtime（关键记录表只有 SELECT/INSERT）。
# worker：后台任务（证据包导出）。backup：每日 02:30 备份（pg_dump 用 app_owner）。其他参数原样执行，例如 python manage.py verify_restore。
set -e
case "$1" in
  web)
    DB_USER="$MIGRATE_DB_USER" DB_PASSWORD="$MIGRATE_DB_PASSWORD" python manage.py migrate --noinput
    DB_USER="$MIGRATE_DB_USER" DB_PASSWORD="$MIGRATE_DB_PASSWORD" python manage.py check_grants
    if [ "${SEED_BASE:-0}" = "1" ]; then python manage.py seed_base; fi
    exec gunicorn jh.wsgi:application --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-3}" --threads 4 \
      --worker-class gthread --timeout 300 --access-logfile - ;;
  worker)
    # 迁移由 web 容器执行；等迁移全部完成后再开始领取任务，避免启动时表还不存在
    until python manage.py migrate --check >/dev/null 2>&1; do echo "等待数据库迁移完成…"; sleep 3; done
    exec python manage.py run_jobs ;;
  backup)
    exec python manage.py backup_cron ;;
  *)
    exec "$@" ;;
esac
