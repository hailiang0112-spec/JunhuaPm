#!/bin/bash
# acct 模块（FLOW-01/02/03/14/21）浏览器 E2E 完整重跑：建库 → 迁移 → 造数 → 起服务 → 跑 E2E → 停服务
# 用法：bash run.sh            （全流程）
#       KEEP=1 bash run.sh     （跑完不停服务，便于排查）
MOD=acct BPORT=8101 FPORT=5201
cd "$(dirname "$0")"
source ../_lib/env.sh
setup_db                                   # 1. 新建 jh_e2e_$MOD（app_owner 迁移）
manage_rt seed_demo | tail -1              # 2. 公共演示造数（seed_base + 真实接口造砌墙阶段现场）
start_services                             # 3. gunicorn（app_runtime）+ vite preview（dist）
python3 seed.py | tail -1                  # 4. 模块造数（真实 HTTP 接口）
set +e
python3 e2e.py 2>&1 | tee "$LOGS/e2e.out"  # 5. 浏览器 E2E（结果 result.json，截图 shots/）
code=${PIPESTATUS[0]}
echo "E2E 退出码 $code"
[ -z "${KEEP:-}" ] && stop_services
exit $code
