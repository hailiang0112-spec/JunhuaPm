#!/bin/bash
# check 模块（FLOW-09/10/11）浏览器 E2E 完整重跑：建库 → 迁移 → 造数 → 起服务 → 跑 E2E → 停服务
# 用法：bash run.sh            （全流程）
#       KEEP=1 bash run.sh     （跑完不停服务，便于排查）
MOD=check BPORT=8104 FPORT=5204
cd "$(dirname "$0")"
source ../_lib/env.sh
setup_db                                   # 1. 新建 jh_e2e_$MOD（app_owner 迁移）
manage_rt seed_base | tail -1              # 2. 基础造数（账号、模板、项目；检查点状态由 seed.py 从零构造）
start_services                             # 3. gunicorn（app_runtime）+ vite preview（dist）
python3 seed.py | tail -1                  # 4. 模块造数（真实 HTTP 接口）
SEED_JSON=$OUT/seed.json manage_rt shell < advance_time.py | tail -1   # 4b. 时间推进：唯一的 ORM 前置（待放行起点前拨 25 小时）
set +e
python3 e2e.py 2>&1 | tee "$LOGS/e2e.out"  # 5. 浏览器 E2E（结果 result.json，截图 shots/）
code=${PIPESTATUS[0]}
echo "E2E 退出码 $code"
[ -z "${KEEP:-}" ] && stop_services
exit $code
