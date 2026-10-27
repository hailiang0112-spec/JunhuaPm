# 开发约定（并行开发代理必读）

产品：君华装修项目管理平台。上游契约都在 `../output/`：
- `requirements.md`（rev2，验收条件 AC 原文就是文案与行为的唯一依据）
- `tests/TDD验收契约.md`（每条 FLOW、RULE、DESIGN 的通过标准）
- `技术方案.md`（数据模型、接口分组、状态迁移、异常文案）
- `pages/PAGE-*.html`（高保真原型）与 `pages/PAGE-*.md`（页面规格）
- `DESIGN.md`

## 目录
- `backend/`：Django 5.2 + DRF，单 app `core`
  - `core/models/`：全部数据模型，**由负责人维护**
  - `core/api/<模块>.py`：各模块接口，每个文件导出 `urlpatterns`，`core/urls.py` 已经全部 include
  - `core/services/`：业务服务，包括 `ledger.py`（摘要链）、`audit.py`（操作日志）、`storage.py`（文件）、`projects.py`（建项目 / 工序规则）、`shared.py`（跨模块共用：不一致生成问题、变更单草稿、检查点派生标签）
  - `core/perms.py`：权限点 → 角色集合，**由负责人维护**
  - `core/errors.py`：统一错误体，提供 `fail()`、`validation([(field, msg)])`、`forbidden()`、`ApiError`
  - `core/api/base.py`：`ProjectView`（自动项目隔离与角色）、`paginate()`、`iso()`、`d()`
  - `core/tests/`：pytest，夹具见 `conftest.py`（`project`、`users`、`client_for("pm")` 等）
- `frontend/`：React 19 + Vite + TS，不用 UI 组件库，直接复用 `src/styles/`（tokens.css、app.css、shell.css）
  - `src/pages/PAGE-Fxx-xx.tsx`：每页一个文件（路由已在 `src/routes.tsx` 注册，**不要改路由文件**）
  - `src/layout/Shell.tsx`：外壳（`<Shell title sub actions crumb>`），以及 `<Card>`
  - `src/ui/index.tsx`：`Icon`、`Seal`（印章）、`Modal`、`ConfirmDialog`（不可撤回操作的二次确认摘要）、`useToast`、`Loading`、`Empty`、`ErrorState`、`Pager`、`Field`、`copyText`、`useApiError`、`money`
  - `src/api.ts`：`api(path, {method, body, form})`、`uploadFile(pid, file)`、`idemKey()`、`ApiError`（含 `fieldMap()`）
  - `src/session.tsx`：`useSession()`（me）、`useProject(pid)`（project、`can(权限点)`、`has(角色)`）

## 运行（每个代理用自己的数据库和端口，互不干扰）
```bash
cd backend && . .venv/bin/activate
export DB_NAME=jh_<你的代号> TEST_DB_NAME=jh_test_<你的代号>
DB_USER=app_owner DB_PASSWORD=app_owner_pw createdb -h 127.0.0.1 -U app_owner $DB_NAME   # 第一次（PGPASSWORD=app_owner_pw）
DB_USER=app_owner DB_PASSWORD=app_owner_pw python manage.py migrate
DB_USER=app_runtime DB_PASSWORD=app_runtime_pw python manage.py seed_base        # 演示账号，密码均为 Jh123456
DB_USER=app_runtime DB_PASSWORD=app_runtime_pw python manage.py runserver 127.0.0.1:<你的后端端口>
DB_USER=app_owner DB_PASSWORD=app_owner_pw python -m pytest core/tests/test_<模块>.py
cd ../frontend && API_PORT=<你的后端端口> WEB_PORT=<你的前端端口> npx vite --host 127.0.0.1
npx tsc -b      # 类型检查必须通过
```
- 演示账号：
  - 13800000000 周经理（公司管理员）
  - 13800000001 刘先生（业主）
  - 13800000002 刘太太（业主）
  - 13800000003 钱工（业主方成员）
  - 13800000004 张工（项目经理）
  - 13800000005 李工（设计经理）
  - 13800000006 王工（质检）
  - 13800000007 赵会计（预算专员）
- 运行时一律用 `app_runtime` 账号。这个账号对关键记录表只有 SELECT / INSERT，任何 UPDATE / DELETE 都会报权限错误，这是有意设计的。

## 后端规则
1. **项目内接口**一律继承 `ProjectView`，URL 形如 `projects/<int:project_id>/…`。按 ID 取对象要用 `self.obj(Model, pk)`，它会带上项目条件，防止越权读取。
2. **权限**：用 `self.require("权限点")`，权限点表在 `core/perms.py`。不要自己判断角色字符串；确实缺权限点时写在最终报告里。
3. **关键记录**（模型类带 `KEY_RECORD = True`）只能新增，不能修改或删除。创建后在**同一个事务**里调用 `ledger.append(project_id, obj)`。不要给关键记录写 PUT / PATCH / DELETE 路由；必须在同一路径上同时提供 GET 和 POST 时，用 `http_method_names = ["get", "post"]`。
4. **投影表**（Baseline、Checkpoint、ChangeOrder、Issue 等）可以更新，更新前先 `select_for_update()` 锁行再校验状态；重复操作返回 409，并带上原记录的「谁、何时」。
5. **操作日志**：所有写操作调用 `audit.log(actor, action, object_type, id, label, before, after, project=...)`。
6. **错误文案**原样使用 AC 和技术方案 §4.6 中的文字。表单校验用 `validation([...])`，一次返回全部字段错误。
7. **响应**：JSON 键用 camelCase；日期 `YYYY-MM-DD`，时间用 `iso()`（`+08:00`）；文件用 `storage.file_dict(f)` 表示。
8. **不要修改** `core/models/`、`core/perms.py`、`core/urls.py`、`core/api/base.py`、`core/services/{ledger,audit,storage,shared,projects}.py`、`jh/settings.py`、`conftest.py`、`src/routes.tsx`、`src/main.tsx`、`src/layout/Shell.tsx`、`src/ui/index.tsx`、`src/api.ts`、`src/session.tsx`、`src/styles/{tokens,app,shell}.css`。确实需要改时，在最终报告里写清改什么、为什么，由负责人统一处理。
   - 例外：确实缺一个字段时，可以新建迁移文件 `core/migrations/0100_<你的代号>_<说明>.py`（依赖 `0002_runtime_grants`），同时修改对应模型字段，并在报告中写明。
9. **测试**：在 `core/tests/test_<你的代号>.py` 中，按 TDD 契约中分配给你的 FLOW / RULE 行编写 API 级 pytest。期望值来自契约里的已知业务数据，不能用被测函数算出期望值。

## 前端规则
1. 每页对照 `../output/pages/PAGE-Fxx-xx.html` 实现。
   - 页面特有样式从原型 `<style>` 中拷到 `src/styles/pages/PAGE-Fxx-xx.css`，在页面里 import。这些样式只用 `var(--xxx)`，不写 Hex。
   - 结构、组件、文案、交互、视觉、手机适配六类锚点，以 TDD 契约 §4 中该页的 DESIGN 行为准。
2. 原型里的「演示身份」「原型状态」切换控件是原型专用的，**不做**。真实角色来自 `useProject(pid).can(权限点)`：没有权限的按钮直接隐藏，不置灰。
3. 数据一律来自真实接口，用 `@tanstack/react-query` 的 `useQuery` / `useMutation`，写操作成功后 invalidate 相关 query。不允许 mock，也不允许写死业务数据。
4. 不可撤回的操作（签认、放行、驳回、作废、标记已覆盖、标记已付等）用 `ConfirmDialog` 展示摘要，成功后弹 toast；涉及印章的状态加 `just` 动画。
5. 状态一律用 `<Seal>`，每张卡片或每行最多一个。主按钮每屏最多一个。
6. 手机 375 宽时页面不能出现横向滚动，大表格放在 `.scroll-x` 里。核对、放行、签认这几个手机主流程的按钮用 `.btn.block`（44px 高）。
7. 链接跳转用 `react-router` 的 `<Link>` 或 `useNavigate`，路径见 `src/routes.tsx`。

## 跨模块接口约定（大家按这个对接，不要各做一套）
- **检查点**（证据链 C2 负责）
  - `GET /api/projects/{pid}/work-items/{wid}/checkpoints` → `{items:[{id,code,point,isConcealed,status,labels[],drawingVersionId,pageNo,x,y,latestCheck}]}`
  - `POST` 同一路径，body `{point,isConcealed,x,y,pageNo}`。图纸版本取基线引用的签认版。基线待签认时返回 409「基线待业主签认，需业主退回后才能修改」；基线已签认或待重签时直接生效（AC-F06-16）
- **图纸**（证据链 C1 负责）
  - `GET /api/projects/{pid}/drawing-versions/{id}` → `{id,setId,setName,versionNo,status,changeNote,pages:[{pageNo,imageUrl,width,height}],file,cadFile,signedBy,signedAt,isCurrentSigned}`
  - `GET /api/projects/{pid}/drawing-sets` → `{items:[{id,name,currentSignedVersion,versions:[…]}]}`
- **变更单**（D 负责）
  - `GET /api/projects/{pid}/change-orders?status=已生效` → `{items:[{id,code,title,status,…}]}`
  - 从问题或补充事项生成草稿统一调用 `core/services/shared.create_change_draft(...)`
- **问题**：核对结论为不一致时调用 `shared.create_issue_from_check(check, actor)`（C2 调用）。问题的其余接口由 D 负责
- **派生标签**：不得覆盖 / 超时 / 未放行先覆盖，一律用 `shared.checkpoint_labels(cp, project)`
- **待办**（A 负责）：`GET /api/todos` 与 `GET /api/todos/count`（`{total, checkpoints}`），由各模型状态派生
- **工作项**（结构与计划 B 负责）
  - `GET /api/projects/{pid}/work-items?phase=&floor=&room=` → `{items:[{id,name,phaseId,floorId,roomId,floorName,roomName,description,acceptanceCriteria,cost,plannedFinish,actualFinish,ownerName,qcUserId,qcUserName,drawingVersionId,weight,progress,isDisabled,baselineStatus,checkpointSeal,attachmentCount}]}`
  - `POST /api/projects/{pid}/work-items`：新建，未填说明或标准时按工序规则补齐（`projects.apply_rule`）
  - `PATCH /api/projects/{pid}/work-items/{id}`：基线锁定规则在这里统一执行。锁定字段 = drawingVersionId、description、acceptanceCriteria、cost、qcUserId、plannedFinish
    - 基线「已签认 / 待重签」时改锁定字段 → 409 `BASELINE_LOCKED`「已签认，请发起变更单或等待新版图纸重签」
    - 「待签认」时任何修改 → 409 `BASELINE_PENDING_SIGN`「基线待业主签认，需业主退回后才能修改」
    - 以上两种情况，progress、actualFinish 照常保存
    - 房间不属于楼层 → 400「房间与楼层不匹配」
  - `POST /api/projects/{pid}/work-items/{id}/disable`、`DELETE /api/projects/{pid}/work-items/{id}`（已有关联记录时返回 409「已有记录，只能停用」）
- **基线**（证据链 C1 负责）：提交、签认（批量）、退回、待重签、重签。工作项详情页（PAGE-F05-01）调用上面的工作项接口编辑草稿字段
- **变更单生效**（D 负责）：签认后为每个受影响工作项追加 `BaselineRevision(kind="change_order")`，入链，并把 `baseline.current_revision` / `signed_revision` 指向新修订
