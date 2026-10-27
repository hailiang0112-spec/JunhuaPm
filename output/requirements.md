# 君华装修项目管理平台 Requirements Contract

## Metadata

- work_type: feature
- workflow_mode: standard
- revision: 2
- scope: 全量交付
- source_prd: PRD详细版.md
- status: active

> scope「全量交付」为用户确认的本次完整交付（原型 v1.20 全部能力 + 证据链，见 proposal-v1.md §8）。

## External capability configuration

| Capability | Credential owner | Configuration actor | Surface | Scope | Lifecycle | Stage | Requirement IDs |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 对象存储（照片、图纸与资料文件） | 装修公司 | 公司管理员 | deployment-secret | system | 部署时由公司提供凭据写入部署配置；更换或轮换凭据时重新部署；界面不展示凭据 | 全量交付 | REQ-F04-01, REQ-F06-02, REQ-F12-01, REQ-F17-03 |

## Capability prerequisites

| Prerequisite | Status | Owner | Evidence or deadline | Fallback | Stage | Requirement IDs |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 对象存储服务（公有云） | committed | 装修公司（公司管理员） | 用户 2026-10-27 确认由公司采购（D-9）；截止：首次上线部署前 | 使用服务器本地磁盘存储文件并纳入每日备份 | 全量交付 | REQ-F04-01, REQ-F06-02, REQ-F12-01, REQ-F17-03 |
| HTTPS 证书（云厂商免费证书） | committed | 装修公司（公司管理员） | 用户 2026-10-27 确认；截止：首次上线部署前 | 备案与证书完成前仅以临时访问地址供项目成员内测 | 全量交付 | REQ-F02-02 |
| 异地备份位置（本地存储模式时） | committed | 装修公司（公司管理员） | 用户 2026-10-27 确认；截止：本地存储模式上线前 | 尽快启用对象存储，退出本地存储模式 | 全量交付 | REQ-F12-01 |
| 公有云服务器、域名与 ICP 备案 | committed | 装修公司（公司管理员） | 用户 2026-10-27 确认由公司负责（D-9）；截止：首次上线部署前 | 备案完成前以临时访问地址供项目成员内测 | 全量交付 | REQ-F02-01, REQ-F02-02 |

## Feature F01 · 公司、项目与成员角色

### US-F01-01 · 公司管理员按模板开设工地并分配成员角色

- Role: 公司管理员
- Goal: 从公司模板创建项目并邀请成员担任角色
- Value: 每个工地开工前各方职责与权限明确
- Stage: 全量交付
- Status: active

### US-F01-02 · 业主委托代理人代为放行

- Role: 业主
- Goal: 指定一位业主方代理人在本人无法及时处理时放行检查点
- Value: 不在现场时放行不卡工期，且仍由业主方把关
- Stage: 全量交付
- Status: active

### REQ-F01-01 · 从公司模板创建项目

- Story: US-F01-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F01-01 · 提交完整信息后创建项目并复制模板

- Parent: REQ-F01-01
- Priority: P0
- EARS:

```text
WHEN 公司管理员提交项目名称、项目地址、计划开工日期、计划交房日期并选择一个公司模板
THE SYSTEM SHALL 创建该项目，复制所选模板的工段、楼层、房间、工作项和工序说明，并将项目状态设为「筹备」
```

### AC-F01-02 · 必填项缺失或日期颠倒时拒绝创建

- Parent: REQ-F01-01
- Priority: P0
- EARS:

```text
WHEN 公司管理员提交的项目缺少项目名称、计划开工日期或计划交房日期之一，或计划交房日期早于计划开工日期
THE SYSTEM SHALL 拒绝创建项目，在对应字段旁显示具体原因，且不产生任何项目记录
```

### REQ-F01-02 · 按项目分配角色，一人可兼多角色

- Story: US-F01-01
- Stage: 全量交付
- Revision: 2
- Status: active

### AC-F01-03 · 角色权限只在被分配的项目内生效

- Parent: REQ-F01-02
- Priority: P0
- EARS:

```text
WHEN 公司管理员为某成员在项目 A 分配「业主、业主方成员、项目经理、设计经理、质检、预算专员」中的一个或多个角色
THE SYSTEM SHALL 该成员仅在项目 A 内获得所分配角色的全部操作权限，在其他项目中不获得这些权限
```

### AC-F01-04 · 项目列表按成员身份过滤

- Parent: REQ-F01-02
- Priority: P0
- EARS:

```text
WHEN 任一成员登录后打开项目列表
THE SYSTEM SHALL 公司管理员看到公司全部项目；其他成员只看到自己在其中至少有一个角色的项目
```

### REQ-F01-03 · 项目数据隔离

- Story: US-F01-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F01-05 · 访问未受邀项目被拒绝

- Parent: REQ-F01-03
- Priority: P0
- EARS:

```text
WHEN 成员通过页面或接口请求读取或修改一个自己没有任何角色的项目中的数据
THE SYSTEM SHALL 拒绝该请求并显示「无权访问该项目」，响应中不包含该项目的任何业务数据
```

### REQ-F01-04 · 移除成员但保留其历史记录

- Story: US-F01-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F01-06 · 移除后立即失去访问且历史署名保留

- Parent: REQ-F01-04
- Priority: P1
- EARS:

```text
WHEN 公司管理员将某成员从项目中移除
THE SYSTEM SHALL 该成员下一次请求起无法访问该项目，其在该项目中已产生的签认、核对、放行、变更、问题和留言记录保留原署名且内容不变
```

### REQ-F01-05 · 业主指定业主代理人

- Story: US-F01-02
- Stage: 全量交付
- Revision: 2
- Status: active

### AC-F01-07 · 代理人只获得放行权限

- Parent: REQ-F01-05
- Priority: P0
- EARS:

```text
WHEN 业主在本项目中将一名已加入项目的成员指定为业主代理人
THE SYSTEM SHALL 该成员获得放行检查点的权限，且不获得签认基线、签认图纸版本和签认变更单的权限
```

### AC-F01-08 · 每个项目最多一名代理人

- Parent: REQ-F01-05
- Priority: P1
- EARS:

```text
WHEN 业主在已有业主代理人的项目中指定另一名成员为代理人
THE SYSTEM SHALL 撤销原代理人的放行权限并将新成员设为唯一的业主代理人，同时留痕记录变更人与时间
```

### AC-F01-09 · 撤销代理立即生效

- Parent: REQ-F01-05
- Priority: P0
- EARS:

```text
WHEN 业主撤销业主代理人
THE SYSTEM SHALL 原代理人从下一次请求起不能放行检查点，其已完成的放行记录保持不变且标注为「代理放行」
```

### REQ-F01-06 · 一个项目可有多名业主

- Story: US-F01-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F01-10 · 任一业主均可签认与放行

- Parent: REQ-F01-06
- Priority: P1
- EARS:

```text
WHEN 项目内有两名或以上成员被分配业主角色，其中一人签认或放行
THE SYSTEM SHALL 该签认或放行即时生效，记录署名为实际操作的业主本人，其他业主的对应待办同时消失
```

### REQ-F01-07 · 项目状态流转

- Story: US-F01-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F01-11 · 项目经理推进项目状态

- Parent: REQ-F01-07
- Priority: P1
- EARS:

```text
WHEN 项目经理将项目状态由「筹备」改为「施工中」，或由「施工中」改为「已交房」并填写实际交房日期
THE SYSTEM SHALL 保存新状态并留痕；「已交房」必须填写实际交房日期，否则拒绝保存
```

### AC-F01-12 · 业主方成员只读，被指定为代理人后才能放行

- Parent: REQ-F01-05
- Priority: P0
- EARS:

```text
WHEN 公司管理员、项目经理或业主邀请一名成员以「业主方成员」角色加入项目
THE SYSTEM SHALL 该成员可以只读查看本项目，不能执行任何签认、核对、定价或编辑操作，且仅在被业主指定为业主代理人后获得放行权限
```

### AC-F01-13 · 公司管理员对项目只读

- Parent: REQ-F01-02
- Priority: P0
- EARS:

```text
WHEN 公司管理员在一个自己没有被分配项目角色的项目中尝试签认、核对、放行或定价
THE SYSTEM SHALL 拒绝该操作；公司管理员对该项目的业务数据只读，管理操作（成员、角色、邀请、重置密码）不受影响；项目状态仍只由项目经理推进（AC-F01-11）
```

## Feature F02 · 账号与登录

### US-F02-01 · 受邀成员通过邀请链接加入项目

- Role: 项目经理
- Goal: 用邀请链接把各方拉进项目
- Value: 不依赖外部通道即可开通账号
- Stage: 全量交付
- Status: active

### US-F02-02 · 成员用手机号和密码登录

- Role: 业主
- Goal: 用手机号和密码安全登录
- Value: 只有本人能以自己的身份签认和放行
- Stage: 全量交付
- Status: active

### REQ-F02-01 · 生成并使用邀请链接

- Story: US-F02-01
- Stage: 全量交付
- Revision: 2
- Status: active

### AC-F02-01 · 生成绑定项目、角色、手机号的邀请链接

- Parent: REQ-F02-01
- Priority: P0
- EARS:

```text
WHEN 公司管理员（任意项目）或项目经理（本项目）填写被邀请人手机号与角色并生成邀请
THE SYSTEM SHALL 生成一条仅可使用一次、7 天内有效的邀请链接，并提供一键复制
```

### AC-F02-02 · 通过有效邀请设置密码后加入

- Parent: REQ-F02-01
- Priority: P0
- EARS:

```text
WHEN 被邀请人打开 7 天内未使用过的邀请链接，填写与邀请一致的手机号、本人姓名并设置符合规则的密码；若该手机号已有账号，则改为输入原密码
THE SYSTEM SHALL 为新手机号创建账号并以所填姓名作为签认署名（已有账号校验原密码后直接关联，不重置密码），并在对应项目授予邀请中的角色
```

### AC-F02-03 · 过期或已用邀请被拒绝

- Parent: REQ-F02-01
- Priority: P0
- EARS:

```text
WHEN 被邀请人打开已过期、已使用或已被撤销的邀请链接
THE SYSTEM SHALL 显示「邀请已失效，请联系邀请人重新发送」，不创建账号也不授予任何角色
```

### AC-F02-04 · 项目经理不能邀请公司管理员

- Parent: REQ-F02-01
- Priority: P1
- EARS:

```text
WHEN 项目经理尝试生成角色为公司管理员的邀请
THE SYSTEM SHALL 拒绝生成并提示「只有公司管理员可以设置该角色」
```

### AC-F02-09 · 业主只能邀请业主方成员

- Parent: REQ-F02-01
- Priority: P1
- EARS:

```text
WHEN 业主在本项目中生成邀请
THE SYSTEM SHALL 只允许选择「业主方成员」角色，其他角色选项不显示
```

### REQ-F02-02 · 手机号密码登录与锁定

- Story: US-F02-02
- Stage: 全量交付
- Revision: 2
- Status: active

### AC-F02-05 · 正确凭据登录成功

- Parent: REQ-F02-02
- Priority: P0
- EARS:

```text
WHEN 成员输入已注册手机号和正确密码
THE SYSTEM SHALL 登录成功并进入「我的待办」首页（同屏列出本人有角色的工地），登录状态在 7 天内无操作后失效
```

### AC-F02-06 · 连续输错 5 次锁定 15 分钟

- Parent: REQ-F02-02
- Priority: P0
- EARS:

```text
WHEN 同一手机号在 15 分钟内连续 5 次输入错误密码
THE SYSTEM SHALL 锁定该账号 15 分钟，期间拒绝登录并显示剩余锁定时间
```

### REQ-F02-03 · 管理员重置密码

- Story: US-F02-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F02-07 · 重置后首次登录必须改密码

- Parent: REQ-F02-03
- Priority: P0
- EARS:

```text
WHEN 公司管理员为某成员重置密码
THE SYSTEM SHALL 生成一次性临时密码，该成员用临时密码登录后必须先设置新密码才能进行其他操作，且重置动作留痕
```

### REQ-F02-04 · 成员修改自己的密码

- Story: US-F02-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F02-08 · 校验原密码后修改

- Parent: REQ-F02-04
- Priority: P1
- EARS:

```text
WHEN 已登录成员提交正确的原密码和符合规则的新密码
THE SYSTEM SHALL 更新密码并使该账号在其他设备上的登录状态全部失效
```

## Feature F03 · 项目结构与模板

### US-F03-01 · 公司管理员维护公司模板

- Role: 公司管理员
- Goal: 维护工段、楼层、房间、工作项、工序说明与检查点模板
- Value: 新工地不用从零录入上百项工作
- Stage: 全量交付
- Status: active

### US-F03-02 · 项目经理调整本项目结构与计划

- Role: 项目经理
- Goal: 在复制来的结构上增删改楼层、房间、工段和工作项，并整批导入导出
- Value: 项目结构与真实房屋和施工计划一致
- Stage: 全量交付
- Status: active

### REQ-F03-01 · 维护公司模板

- Story: US-F03-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F03-01 · 模板修改不影响已创建项目

- Parent: REQ-F03-01
- Priority: P1
- EARS:

```text
WHEN 公司管理员修改公司模板中的工段、楼层、房间、工作项或工序说明后保存
THE SYSTEM SHALL 仅之后新建的项目使用修改后的模板，已创建项目的结构与内容保持不变
```

### REQ-F03-02 · 编辑项目结构

- Story: US-F03-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F03-02 · 增删改楼层、房间、工段

- Parent: REQ-F03-02
- Priority: P0
- EARS:

```text
WHEN 项目经理在项目中新增、改名或删除一个没有任何关联记录的楼层、房间或工段
THE SYSTEM SHALL 保存修改，并在楼层 × 阶段矩阵、房间 × 阶段矩阵和筛选项中即时反映
```

### AC-F03-03 · 有记录的结构只能停用

- Parent: REQ-F03-02
- Priority: P0
- EARS:

```text
WHEN 项目经理删除一个已关联签认、核对、问题或资料记录的楼层、房间、工段或工作项
THE SYSTEM SHALL 拒绝删除并提示「已有记录，只能停用」；停用后该项不再出现在新增选项中，历史记录保持可查
```

### REQ-F03-03 · 工作项字段与阶段进度

- Story: US-F03-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F03-04 · 工作项保存必须归属楼层与匹配的房间

- Parent: REQ-F03-03
- Priority: P0
- EARS:

```text
WHEN 项目经理保存一个工作项，其所属房间不属于所选楼层
THE SYSTEM SHALL 拒绝保存并提示「房间与楼层不匹配」
```

### AC-F03-05 · 阶段进度按权重加权

- Parent: REQ-F03-03
- Priority: P0
- EARS:

```text
WHEN 某工段内工作项的权重为 w1..wn、完成度为 p1..pn（权重为 1–5 的整数，完成度为 0–100 的整数）
THE SYSTEM SHALL 显示该工段进度为 Σ(wi×pi)÷Σwi，保留 1 位小数；工段内没有工作项时显示 0%
```

### AC-F03-06 · 阶段状态自动推导

- Parent: REQ-F03-03
- Priority: P0
- EARS:

```text
WHEN 某工段的加权进度为 0、介于 0 与 99.95 之间、或不低于 99.95
THE SYSTEM SHALL 将该工段状态分别显示为「未开始」「进行中」「已完成」，不允许手工修改
```

### REQ-F03-04 · Excel 导入计划

- Story: US-F03-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F03-07 · 下载模板与导出当前计划

- Parent: REQ-F03-04
- Priority: P1
- EARS:

```text
WHEN 项目经理点击下载空白模板或导出当前计划
THE SYSTEM SHALL 生成 .xlsx 文件，包含施工阶段、工作事项、补充事项、填写说明和取值五张工作表，数值列为数字格式，日期列为文本格式
```

### AC-F03-08 · 按表头识别并逐行校验

- Parent: REQ-F03-04
- Priority: P0
- EARS:

```text
WHEN 项目经理上传 .xlsx 或 .csv 计划文件，其中存在阶段名不可识别、楼层与房间不匹配、日期无法识别、权重或完成度越界的行
THE SYSTEM SHALL 列出每个错误所在的工作表与行号，且在全部错误修正前不允许执行导入
```

### AC-F03-09 · 导入不覆盖已签认基线

- Parent: REQ-F03-04
- Priority: P0
- EARS:

```text
WHEN 校验通过的导入文件中包含对已签认基线工作项的字段修改
THE SYSTEM SHALL 仅新增文件中的新工作项并更新未签认工作项，对已签认工作项不做任何修改，并在结果中逐项列出「已签认，需走变更单」
```

### REQ-F03-05 · 工序说明库自动补齐

- Story: US-F03-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F03-10 · 名称匹配时补齐工作说明与验收标准

- Parent: REQ-F03-05
- Priority: P1
- EARS:

```text
WHEN 新建或导入的工作项未填写工作说明或验收标准，且其名称命中工序说明库中的规则
THE SYSTEM SHALL 按规则库顺序以首个命中规则补齐空缺的工作说明与验收标准，已填写的字段不被覆盖
```

## Feature F04 · 图纸版本管理

### US-F04-01 · 设计经理发布新版图纸并说明改了什么

- Role: 设计经理
- Goal: 上传新版图纸、写明改动并标出受影响工作项
- Value: 现场只按最新签认版施工，改图有据可查
- Stage: 全量交付
- Status: active

### US-F04-02 · 业主签认图纸版本

- Role: 业主
- Goal: 逐版签认图纸
- Value: 改图不再只签最终版
- Stage: 全量交付
- Status: active

### REQ-F04-01 · 上传图纸版本

- Story: US-F04-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F04-01 · 上传成功生成新版本号

- Parent: REQ-F04-01
- Priority: P0
- EARS:

```text
WHEN 设计经理在某图纸分册（如「水电点位图」）下上传 PDF、JPG 或 PNG 图纸文件（单个不超过 50MB，可另附 CAD 文件）并填写改动说明
THE SYSTEM SHALL 生成该分册的新版本，版本号为上一版加 1，状态为「待业主签认」，此前版本保持只读可查
```

### AC-F04-02 · 缺少改动说明时拒绝发布

- Parent: REQ-F04-01
- Priority: P0
- EARS:

```text
WHEN 设计经理上传第 2 版及以后的图纸但未填写改动说明
THE SYSTEM SHALL 拒绝发布并提示「请说明本版改了什么」
```

### AC-F04-03 · 非图纸格式不能作为钉点底图

- Parent: REQ-F04-01
- Priority: P1
- EARS:

```text
WHEN 设计经理只上传 CAD 文件而未上传 PDF 或图片
THE SYSTEM SHALL 拒绝发布并提示「请同时上传 PDF 或图片版，CAD 仅作为附件」
```

### REQ-F04-02 · 版本历史不可删改

- Story: US-F04-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F04-04 · 已发布版本不可删除或替换

- Parent: REQ-F04-02
- Priority: P0
- EARS:

```text
WHEN 任何角色（含公司管理员）尝试删除或替换一个已发布的图纸版本
THE SYSTEM SHALL 拒绝该操作，版本文件与改动说明保持不变
```

### AC-F04-05 · 任意两版并排查看

- Parent: REQ-F04-02
- Priority: P1
- EARS:

```text
WHEN 成员在某图纸分册中选择两个版本进行对比
THE SYSTEM SHALL 并排显示两个版本的图纸及两版之间所有版本的改动说明
```

### REQ-F04-03 · 业主签认图纸版本

- Story: US-F04-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F04-06 · 签认后成为当前签认版

- Parent: REQ-F04-03
- Priority: P0
- EARS:

```text
WHEN 业主签认某分册的一个待签认版本
THE SYSTEM SHALL 将该版本设为该分册的当前签认版，并生成包含签认人、时间、版本号和文件摘要的签认记录
```

### REQ-F04-04 · 新版签认后受影响工作项进入待重签

- Story: US-F04-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F04-07 · 标记受影响工作项

- Parent: REQ-F04-04
- Priority: P0
- EARS:

```text
WHEN 设计经理发布新版时勾选了受影响的工作项，且该版本被业主签认
THE SYSTEM SHALL 将这些工作项中已签认的基线状态改为「待重签」，并向项目经理与业主生成待办
```

### REQ-F04-05 · 现场查看当前签认版

- Story: US-F04-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F04-08 · 显示版本号与待重签提示

- Parent: REQ-F04-05
- Priority: P0
- EARS:

```text
WHEN 成员在手机上打开某工作项的图纸
THE SYSTEM SHALL 显示该工作项基线所引用的签认版本及版本号；若该分册存在更新的签认版且该工作项处于待重签，在图纸上方显示「图纸已更新，基线待重签」
```

## Feature F05 · 工作项基线签认

### US-F05-01 · 项目经理准备工作项基线

- Role: 项目经理
- Goal: 在开工前把每项工作的图纸版本、做法、费用、顺序、质检人和证据要求写清楚
- Value: 先讲清再干活
- Stage: 全量交付
- Status: active

### US-F05-02 · 业主逐项或批量签认基线

- Role: 业主
- Goal: 看清每项内容后签认
- Value: 以后有争议都拿签认基线对照
- Stage: 全量交付
- Status: active

### REQ-F05-01 · 提交基线待签

- Story: US-F05-01
- Stage: 全量交付
- Revision: 2
- Status: active

### AC-F05-01 · 字段齐全才能提交

- Parent: REQ-F05-01
- Priority: P0
- EARS:

```text
WHEN 项目经理提交一个工作项基线，缺少签认版图纸分册版本、工作说明、验收标准、费用（元）、计划完成日期、质检人、检查点中的任意一项
THE SYSTEM SHALL 拒绝提交并列出所有缺失字段
```

### AC-F05-02 · 只能引用已签认的图纸版本

- Parent: REQ-F05-01
- Priority: P0
- EARS:

```text
WHEN 项目经理为基线选择一个状态为「待业主签认」的图纸版本
THE SYSTEM SHALL 拒绝选择并提示「该版本尚未签认」
```

### AC-F05-10 · 待签认期间锁定

- Parent: REQ-F05-01
- Priority: P0
- EARS:

```text
WHEN 项目经理修改一条处于「待签认」状态的基线
THE SYSTEM SHALL 拒绝修改并提示「基线待业主签认，需业主退回后才能修改」
```

### REQ-F05-02 · 业主签认基线

- Story: US-F05-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F05-03 · 签认前展示完整内容

- Parent: REQ-F05-02
- Priority: P0
- EARS:

```text
WHEN 业主打开一条或多条待签基线
THE SYSTEM SHALL 逐项显示图纸分册与版本号、工作说明、验收标准、费用、计划完成日期、质检人和检查点清单后，才显示签认按钮
```

### AC-F05-04 · 批量签认生成逐项记录

- Parent: REQ-F05-02
- Priority: P0
- EARS:

```text
WHEN 业主勾选同一工段或同一楼层下的 N 条待签基线并确认签认
THE SYSTEM SHALL 生成 N 条独立的签认记录，每条包含签认人、时间和该工作项基线的完整内容快照
```

### AC-F05-05 · 业主可以退回基线

- Parent: REQ-F05-02
- Priority: P1
- EARS:

```text
WHEN 业主对一条待签基线选择退回并填写理由
THE SYSTEM SHALL 将该基线状态改为「已退回」并向项目经理生成待办，理由随基线保存
```

### REQ-F05-03 · 签认后基线锁定

- Story: US-F05-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F05-06 · 已签认字段不可直接编辑

- Parent: REQ-F05-03
- Priority: P0
- EARS:

```text
WHEN 项目经理修改一个已签认基线的图纸版本、工作说明、验收标准、费用、质检人或检查点
THE SYSTEM SHALL 拒绝修改并提示「已签认，请发起变更单或等待新版图纸重签」；完成度、实际完成日期等进度字段仍可修改
```

### REQ-F05-04 · 待重签处理

- Story: US-F05-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F05-07 · 重签前按原签认版核对并提示

- Parent: REQ-F05-04
- Priority: P0
- EARS:

```text
WHEN 质检对一个基线处于「待重签」的工作项的检查点进行核对
THE SYSTEM SHALL 核对页使用原签认版图纸作为底图，并在顶部显示「该工作项有新版图纸待重签」
```

### AC-F05-08 · 重签后引用新版本

- Parent: REQ-F05-04
- Priority: P0
- EARS:

```text
WHEN 项目经理更新待重签基线的图纸版本后提交、业主签认
THE SYSTEM SHALL 基线状态恢复为「已签认」，引用新版本，并保留旧版签认记录
```

### REQ-F05-05 · 临近开工未签认提醒

- Story: US-F05-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F05-09 · 计划完成前 7 天仍未签认生成待办

- Parent: REQ-F05-05
- Priority: P1
- EARS:

```text
WHEN 某工作项的计划完成日期距今不超过 7 天且基线未签认
THE SYSTEM SHALL 向项目经理和业主生成「即将施工，基线未签认」待办
```

## Feature F06 · 检查点、对图核对与业主放行

### US-F06-01 · 质检盖住前对图核对

- Role: 质检
- Goal: 在隐蔽工序被盖住前对照签认图拍照并给出结论
- Value: 偏差在盖住前被发现
- Stage: 全量交付
- Status: active

### US-F06-02 · 业主放行检查点

- Role: 业主
- Goal: 凭质检证据放行或不放行
- Value: 未经放行不得覆盖
- Stage: 全量交付
- Status: active

### US-F06-03 · 业主代理人代为放行

- Role: 业主代理人
- Goal: 业主不在时代为放行
- Value: 不卡工期
- Stage: 全量交付
- Status: active

### REQ-F06-01 · 定义检查点

- Story: US-F06-01
- Stage: 全量交付
- Revision: 2
- Status: active

### AC-F06-01 · 检查点绑定图纸位置

- Parent: REQ-F06-01
- Priority: P0
- EARS:

```text
WHEN 项目经理或质检为工作项新建检查点，填写检查要点、选择是否隐蔽，并在该工作项基线引用的签认版图纸上点选一个位置
THE SYSTEM SHALL 保存检查点，记录图纸分册、版本号与图上坐标，并在图纸上显示钉点
```

### REQ-F06-02 · 对图核对

- Story: US-F06-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F06-02 · 核对必须附照片并钉在图纸位置

- Parent: REQ-F06-02
- Priority: P0
- EARS:

```text
WHEN 质检提交核对记录但未上传任何照片
THE SYSTEM SHALL 拒绝提交并提示「至少上传 1 张现场照片」
```

### AC-F06-03 · 核对记录内容

- Parent: REQ-F06-02
- Priority: P0
- EARS:

```text
WHEN 质检为检查点上传至少 1 张照片（拍照或相册）、选择结论「一致 / 不一致 / 已变更」并选择核对时是否已被覆盖后提交
THE SYSTEM SHALL 保存核对记录，包含核对人、服务器时间、所用图纸版本、照片与钉点位置、结论和覆盖状态，且之后不可修改
```

### AC-F06-04 · 已变更必须关联已生效变更单

- Parent: REQ-F06-02
- Priority: P0
- EARS:

```text
WHEN 质检选择结论「已变更」但未关联一张已由业主签认生效的变更单
THE SYSTEM SHALL 拒绝提交并提示「请关联已生效的变更单」
```

### AC-F06-05 · 复核追加新记录

- Parent: REQ-F06-02
- Priority: P1
- EARS:

```text
WHEN 质检对已有核对记录的检查点再次核对
THE SYSTEM SHALL 追加一条新的核对记录，检查点的当前结论取最新一条，旧记录保留可查
```

### REQ-F06-03 · 放行

- Story: US-F06-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F06-06 · 一致或已变更才能放行

- Parent: REQ-F06-03
- Priority: P0
- EARS:

```text
WHEN 业主或业主代理人对一个当前结论为「一致」或「已变更」的检查点点击放行
THE SYSTEM SHALL 生成放行记录（放行人、是否代理、时间、所依据的核对记录），检查点状态变为「已放行」
```

### AC-F06-07 · 不一致或未核对不能放行

- Parent: REQ-F06-03
- Priority: P0
- EARS:

```text
WHEN 业主或业主代理人尝试放行一个尚未核对或当前结论为「不一致」的检查点
THE SYSTEM SHALL 拒绝放行并提示原因
```

### AC-F06-08 · 非业主方角色不能放行

- Parent: REQ-F06-03
- Priority: P0
- EARS:

```text
WHEN 项目经理、设计经理、质检、预算专员或公司管理员尝试放行检查点
THE SYSTEM SHALL 拒绝操作并提示「只有业主或业主代理人可以放行」
```

### AC-F06-09 · 重复放行不产生第二条记录

- Parent: REQ-F06-03
- Priority: P1
- EARS:

```text
WHEN 一个检查点已被放行后，另一名有放行权限的成员再次提交放行
THE SYSTEM SHALL 不生成新的放行记录，并提示「已由某人于某时放行」
```

### AC-F06-10 · 放行后发现不一致

- Parent: REQ-F06-03
- Priority: P0
- EARS:

```text
WHEN 质检对一个已放行的检查点追加了结论为「不一致」的核对记录
THE SYSTEM SHALL 将检查点状态改为「放行后发现不一致」，保留原放行记录，并按不一致规则生成问题
```

### REQ-F06-04 · 不得覆盖标记与未放行先覆盖

- Story: US-F06-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F06-11 · 未放行的隐蔽检查点显示不得覆盖

- Parent: REQ-F06-04
- Priority: P0
- EARS:

```text
WHEN 一个隐蔽检查点尚未放行
THE SYSTEM SHALL 在工作项、阶段页和手机检查点列表中以红色标签显示「不得覆盖」
```

### AC-F06-12 · 记录未放行先覆盖事件

- Parent: REQ-F06-04
- Priority: P0
- EARS:

```text
WHEN 项目经理将一个尚未放行的隐蔽检查点标记为「已覆盖」，或质检核对时选择「已被覆盖」而该检查点此前未放行
THE SYSTEM SHALL 生成一条「未放行先覆盖」事件记录（检查点、时间、记录人），计入指标并在业主待办中显示
```

### REQ-F06-05 · 放行超时升级提醒

- Story: US-F06-03
- Stage: 全量交付
- Revision: 2
- Status: active

### AC-F06-13 · 超过时限只提醒不自动放行

- Parent: REQ-F06-05
- Priority: P0
- EARS:

```text
WHEN 检查点进入待放行状态后超过项目设定时限（默认 24 小时，可设 1–72 小时）仍未放行
THE SYSTEM SHALL 在业主、业主代理人和项目经理的待办中将该项标为「超时」并置顶，检查点仍保持未放行
```

### REQ-F06-06 · 发现时点推断

- Story: US-F06-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F06-14 · 按覆盖状态与交房日期推断

- Parent: REQ-F06-06
- Priority: P0
- EARS:

```text
WHEN 质检提交结论为「不一致」的核对记录
THE SYSTEM SHALL 将发现时点记为：核对日期不早于项目交房日期（已登记实际交房日期时取实际，否则取计划）时为「交房后」；否则核对时未覆盖为「覆盖前」、已覆盖为「覆盖后」
```

### AC-F06-15 · 发现时点修正留痕

- Parent: REQ-F06-06
- Priority: P1
- EARS:

```text
WHEN 质检或项目经理修正某条不一致记录的发现时点并填写理由
THE SYSTEM SHALL 保存修正后的发现时点，并追加一条包含修正前后值、修正人、时间和理由的记录
```

### AC-F06-16 · 已签认基线新增检查点直接生效

- Parent: REQ-F06-01
- Priority: P0
- EARS:

```text
WHEN 项目经理或质检为一个基线处于「已签认」或「待重签」的工作项新增检查点
THE SYSTEM SHALL 新检查点立即生效且不改变基线签认状态，追加一条留痕记录，并向业主生成「新增检查点」知会待办；已有检查点仍不可修改或删除
```

### AC-F06-17 · 放行时限由项目经理或公司管理员设置

- Parent: REQ-F06-05
- Priority: P1
- EARS:

```text
WHEN 项目经理或公司管理员把项目放行时限设为 1–72 之间的整数小时并保存；或其他角色尝试修改放行时限
THE SYSTEM SHALL 前者保存并对之后进入待放行的检查点生效，后者被拒绝且该设置对其只读
```

## Feature F07 · 变更单

### US-F07-01 · 项目经理发起变更单

- Role: 项目经理
- Goal: 现场需要调整时先发起变更单
- Value: 变更先签后做
- Stage: 全量交付
- Status: active

### US-F07-02 · 预算专员给变更定价

- Role: 预算专员
- Goal: 给每张变更单写清费用和工期影响以及谁承担
- Value: 变更费用有据
- Stage: 全量交付
- Status: active

### US-F07-03 · 业主签认变更单

- Role: 业主
- Goal: 看清内容、费用和承担方后签认或驳回
- Value: 不再出现口头约定事后对不上
- Stage: 全量交付
- Status: active

### REQ-F07-01 · 发起变更单

- Story: US-F07-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F07-01 · 字段齐全才能发起

- Parent: REQ-F07-01
- Priority: P0
- EARS:

```text
WHEN 项目经理发起变更单，缺少原因类别（业主要求 / 设计深化 / 现场条件 / 施工纠偏）、变更内容、至少 1 个受影响工作项、是否需要新版图纸、现场是否已按此施工中的任一项
THE SYSTEM SHALL 拒绝提交并列出缺失字段
```

### AC-F07-02 · 发起后进入待预算定价

- Parent: REQ-F07-01
- Priority: P0
- EARS:

```text
WHEN 项目经理提交字段齐全的变更单
THE SYSTEM SHALL 生成编号为「项目内序号」的变更单，状态为「待预算定价」，并向预算专员生成待办
```

### REQ-F07-02 · 预算专员定价

- Story: US-F07-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F07-03 · 定价后进入待业主签认

- Parent: REQ-F07-02
- Priority: P0
- EARS:

```text
WHEN 预算专员填写费用增减（元，可为负数）、工期影响（天，可为 0 或负数）和费用承担方（业主 / 装修公司 / 设计方）后提交
THE SYSTEM SHALL 变更单状态变为「待业主签认」并向业主生成待办
```

### REQ-F07-03 · 业主签认或驳回

- Story: US-F07-03
- Stage: 全量交付
- Revision: 2
- Status: active

### AC-F07-04 · 签认后生效并修订基线

- Parent: REQ-F07-03
- Priority: P0
- EARS:

```text
WHEN 业主签认一张待签认的变更单
THE SYSTEM SHALL 变更单状态变为「已生效」，生成签认记录，并在每个受影响工作项的基线中追加一条引用该变更单的修订
```

### AC-F07-05 · 驳回需填写理由

- Parent: REQ-F07-03
- Priority: P0
- EARS:

```text
WHEN 业主驳回一张待签认的变更单但未填写理由
THE SYSTEM SHALL 拒绝提交并提示「请填写驳回理由」
```

### AC-F07-06 · 驳回后退回项目经理

- Parent: REQ-F07-03
- Priority: P1
- EARS:

```text
WHEN 业主填写理由后驳回变更单
THE SYSTEM SHALL 变更单状态变为「已驳回」，理由保存，并向项目经理生成待办
```

### REQ-F07-04 · 需新版图纸的变更

- Story: US-F07-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F07-07 · 生效后提醒设计经理出图

- Parent: REQ-F07-04
- Priority: P1
- EARS:

```text
WHEN 一张标记为「需要新版图纸」的变更单生效
THE SYSTEM SHALL 向设计经理生成「按变更单出新版图纸」待办，设计经理发布新版时可关联该变更单
```

### REQ-F07-05 · 后补变更识别

- Story: US-F07-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F07-08 · 现场已施工的变更记为后补

- Parent: REQ-F07-05
- Priority: P0
- EARS:

```text
WHEN 项目经理发起变更单时选择「现场已按此施工」
THE SYSTEM SHALL 将该变更单标记为「后补变更」，计入「变更先签后做比例」的分母但不计入分子
```

### AC-F07-09 · 驳回后修改重新提交

- Parent: REQ-F07-03
- Priority: P0
- EARS:

```text
WHEN 项目经理修改一张「已驳回」的变更单后重新提交
THE SYSTEM SHALL 变更单编号不变、状态回到「待预算定价」，原驳回记录与理由保留在该变更单历史中
```

## Feature F08 · 不一致处置与问题闭环

### US-F08-01 · 质检对不一致给出处置方向

- Role: 质检
- Goal: 判断不一致的原因并得到处置建议
- Value: 按规则定责，不再扯皮
- Stage: 全量交付
- Status: active

### US-F08-02 · 项目经理闭环问题

- Role: 项目经理
- Goal: 登记、处理并闭环问题
- Value: 问题有始有终
- Stage: 全量交付
- Status: active

### REQ-F08-01 · 不一致自动生成问题并给出处置建议

- Story: US-F08-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F08-01 · 核对不一致时生成问题

- Parent: REQ-F08-01
- Priority: P0
- EARS:

```text
WHEN 质检提交结论为「不一致」的核对记录
THE SYSTEM SHALL 自动生成一条问题，带上检查点、工作项、楼层、房间、照片和发现时点，状态为「未闭环」
```

### AC-F08-02 · 按原因给出处置建议

- Parent: REQ-F08-01
- Priority: P0
- EARS:

```text
WHEN 质检为不一致问题选择原因「设计已改但未签变更单」「施工偏离签认图」「图纸本身未表达清楚」之一
THE SYSTEM SHALL 分别显示建议「补签变更单（可一键生成变更单草稿）」「返工后复核」「设计经理出新版或书面澄清」
```

### REQ-F08-02 · 问题登记与闭环

- Story: US-F08-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F08-03 · 手工登记问题

- Parent: REQ-F08-02
- Priority: P0
- EARS:

```text
WHEN 任一项目成员填写问题描述、等级（一般 / 重要 / 严重）、所属工段、楼层与房间、对策、负责人和要求闭环日期后提交
THE SYSTEM SHALL 保存问题，状态为「未闭环」；对策为空时记为「待补充对策」，负责人为空时记为「待指派」
```

### AC-F08-04 · 超期天数计算

- Parent: REQ-F08-02
- Priority: P0
- EARS:

```text
WHEN 一条未闭环问题的要求闭环日期早于今天
THE SYSTEM SHALL 显示超期天数为今天减去要求闭环日期的天数，并在问题遗留清单中按超期天数从大到小排序
```

### AC-F08-05 · 闭环与重新打开

- Parent: REQ-F08-02
- Priority: P0
- EARS:

```text
WHEN 项目经理或质检将问题标记为已闭环，或将已闭环问题重新打开
THE SYSTEM SHALL 分别记录闭环日期为当天、或清除闭环日期并恢复为「处理中」，每次变化追加留痕
```

### REQ-F08-03 · 不一致问题闭环需复核

- Story: US-F08-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F08-06 · 复核通过前不能闭环

- Parent: REQ-F08-03
- Priority: P0
- EARS:

```text
WHEN 项目经理尝试闭环一条由不一致核对生成的问题，而对应检查点的最新核对结论仍为「不一致」
THE SYSTEM SHALL 拒绝闭环并提示「请先由质检复核为一致或已变更」
```

### REQ-F08-04 · 问题不可删除只能作废

- Story: US-F08-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F08-07 · 作废需理由并保留记录

- Parent: REQ-F08-04
- Priority: P0
- EARS:

```text
WHEN 任一成员对问题执行删除
THE SYSTEM SHALL 不删除记录，改为要求填写作废理由后将其标记为「已作废」，作废问题不计入问题统计但仍可在筛选中查看
```

## Feature F09 · 公司检查经验库

### US-F09-01 · 质检把不一致沉淀为检查经验

- Role: 质检
- Goal: 提交和审核检查经验
- Value: 同样的偏差不在下一个工地或下一道工序重演
- Stage: 全量交付
- Status: active

### REQ-F09-01 · 从问题提交经验条目

- Story: US-F09-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F09-01 · 提交时自动脱敏

- Parent: REQ-F09-01
- Priority: P1
- EARS:

```text
WHEN 质检从一条已闭环的不一致问题提交经验条目
THE SYSTEM SHALL 生成待审核条目，只包含工段、工序、问题类型、检查要点和对策，不包含业主姓名、项目地址和照片；质检可另行选择附带照片
```

### REQ-F09-02 · 审核与状态

- Story: US-F09-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F09-02 · 审核通过才对其他项目可见

- Parent: REQ-F09-02
- Priority: P1
- EARS:

```text
WHEN 公司内任一质检审核通过一条待审核经验条目并选择状态「未验证经验 / 历史观察 / 已验证」
THE SYSTEM SHALL 条目对公司全部项目的成员可见，并记录审核人、时间和状态
```

### AC-F09-03 · 修改生成新版本

- Parent: REQ-F09-02
- Priority: P1
- EARS:

```text
WHEN 质检修改一条已审核条目的内容或状态
THE SYSTEM SHALL 生成该条目的新版本，旧版本保留可查
```

### REQ-F09-03 · 新建检查点时推荐经验

- Story: US-F09-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F09-04 · 按工段推荐已审核条目

- Parent: REQ-F09-03
- Priority: P1
- EARS:

```text
WHEN 项目经理或质检为某工段的工作项新建检查点
THE SYSTEM SHALL 列出该工段下已审核的经验条目，按「已验证、历史观察、未验证经验」排序，点击后可将其检查要点加入该检查点
```

## Feature F10 · 总览与指标

### US-F10-01 · 业主在总览看清进度与证据链指标

- Role: 业主
- Goal: 一眼看到进度偏差、问题遗留和四项证据链指标
- Value: 知道工地是否按规矩在走
- Stage: 全量交付
- Status: active

### REQ-F10-01 · 项目总览

- Story: US-F10-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F10-01 · 总体完成度与计划基准

- Parent: REQ-F10-01
- Priority: P0
- EARS:

```text
WHEN 业主打开项目总览
THE SYSTEM SHALL 显示总体完成度 = Σ(工段权重×工段进度)÷Σ工段权重、计划基准 = Σ(工段权重×工段计划进度)÷Σ工段权重，以及两者之差（领先或滞后的百分点），均保留 1 位小数
```

### AC-F10-02 · 工期按自然日含首尾计算

- Parent: REQ-F10-01
- Priority: P0
- EARS:

```text
WHEN 项目各工段计划起止中最早开始日为 S、最晚结束日为 E
THE SYSTEM SHALL 显示项目周期为 S ~ E，总工期为 E 减 S 的天数再加 1，已用天数为今天减 S 再加 1 并限制在 0 到总工期之间
```

### AC-F10-03 · 保留原型总览模块

- Parent: REQ-F10-01
- Priority: P1
- EARS:

```text
WHEN 业主打开项目总览
THE SYSTEM SHALL 显示六阶段甘特图、楼层 × 阶段完成度矩阵、房间完成度短板前 8、房间问题前 6、每日出勤日历、按阶段问题对比、问题遗留清单、计划变更台账和各工段速览卡
```

### REQ-F10-02 · 证据链四项指标

- Story: US-F10-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F10-04 · 覆盖前发现比例

- Parent: REQ-F10-02
- Priority: P0
- EARS:

```text
WHEN 所选范围（全项目或某工段）内存在 N 条未作废的不一致记录，其中 M 条发现时点为「覆盖前」
THE SYSTEM SHALL 显示覆盖前发现比例为 M÷N，保留 1 位小数，并标注水电阶段目标线 90%
```

### AC-F10-05 · 隐蔽检查点合规率

- Parent: REQ-F10-02
- Priority: P0
- EARS:

```text
WHEN 所选范围内有 N 个已放行或已覆盖的隐蔽检查点，其中 M 个在覆盖前同时具备引用签认版图纸的核对记录、至少 1 张照片和放行记录
THE SYSTEM SHALL 显示隐蔽检查点合规率为 M÷N，并标注目标线 100%
```

### AC-F10-06 · 最新签认版使用率

- Parent: REQ-F10-02
- Priority: P0
- EARS:

```text
WHEN 所选范围内有 N 条核对记录，其中 M 条所用图纸版本是核对当时该分册的最新签认版
THE SYSTEM SHALL 显示最新签认版使用率为 M÷N，并标注目标线 100%
```

### AC-F10-07 · 变更先签后做比例

- Parent: REQ-F10-02
- Priority: P0
- EARS:

```text
WHEN 所选范围内有 N 张已生效变更单，其中 M 张未标记为后补变更
THE SYSTEM SHALL 显示变更先签后做比例为 M÷N，并标注目标线 100%
```

### AC-F10-08 · 分母为 0 时显示暂无数据

- Parent: REQ-F10-02
- Priority: P0
- EARS:

```text
WHEN 任一证据链指标的分母为 0
THE SYSTEM SHALL 显示「暂无数据」，不显示 0% 或 100%
```

### REQ-F10-03 · 楼层与房间视图

- Story: US-F10-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F10-09 · 房间 × 阶段矩阵下钻

- Parent: REQ-F10-03
- Priority: P1
- EARS:

```text
WHEN 成员在房间 × 阶段矩阵中点击某房间与某工段交叉的单元格
THE SYSTEM SHALL 跳转到该工段详情页并将工作项筛选为该房间
```

### REQ-F10-04 · 工段详情页

- Story: US-F10-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F10-10 · 保留原型阶段详情模块

- Parent: REQ-F10-04
- Priority: P1
- EARS:

```text
WHEN 成员打开某工段详情页
THE SYSTEM SHALL 显示工段进度与计划基准、计划与实际起止、出勤统计、工作项表（含楼层与房间筛选、工作说明与验收标准、资料数）、本工段楼层房间分布、验收图片、问题卡片和计划变更留档
```

## Feature F11 · 出勤

### US-F11-01 · 项目经理登记每日出勤

- Role: 项目经理
- Goal: 按工段登记每天的出勤人数
- Value: 人工投入真实可查
- Stage: 全量交付
- Status: active

### REQ-F11-01 · 登记出勤

- Story: US-F11-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F11-01 · 单日登记

- Parent: REQ-F11-01
- Priority: P1
- EARS:

```text
WHEN 项目经理为某工段选择工段工期内的一个日期并填写 0–40 的出勤人数
THE SYSTEM SHALL 保存该日出勤人数并重新计算累计人工日、日均出勤和峰值
```

### AC-F11-02 · 批量登记

- Parent: REQ-F11-01
- Priority: P1
- EARS:

```text
WHEN 项目经理选择工段工期内的起止日期、人数和范围（每天 / 仅工作日跳过周日 / 仅至今日）
THE SYSTEM SHALL 按所选范围为每一天写入该人数，并显示写入的天数
```

### AC-F11-03 · 未登记日期不自动生成数据

- Parent: REQ-F11-01
- Priority: P0
- EARS:

```text
WHEN 某工段某日没有出勤登记
THE SYSTEM SHALL 该日显示为「未登记」，在累计人工日与日历中按 0 计，不生成任何推算人数
```

### REQ-F11-02 · 出勤日历

- Story: US-F11-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F11-04 · 按月展示全项目每日出勤

- Parent: REQ-F11-02
- Priority: P1
- EARS:

```text
WHEN 成员在总览查看某月出勤日历
THE SYSTEM SHALL 每格显示当日各工段出勤之和，按 0、1–4、5–8、9–12、13 及以上五档着色，并显示该月合计、施工天数与峰值
```

## Feature F12 · 验收图片、资料库与房屋档案

### US-F12-01 · 成员为工作项上传完工资料

- Role: 质检
- Goal: 为工作项上传完工照片和验收文件
- Value: 完工资料随工作项可查
- Stage: 全量交付
- Status: active

### US-F12-02 · 业主在房屋档案查看图纸效果图和合同

- Role: 业主
- Goal: 集中查看布局图、效果图和合同
- Value: 资料不再散落在微信群
- Stage: 全量交付
- Status: active

### REQ-F12-01 · 工作项资料

- Story: US-F12-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F12-01 · 上传多个文件

- Parent: REQ-F12-01
- Priority: P1
- EARS:

```text
WHEN 成员为某工作项一次选择多个图片、PDF、Word 或 Excel 文件（单个不超过 50MB）上传
THE SYSTEM SHALL 全部保存并在工作项「资料」按钮上显示数量，图片显示缩略图并可放大，其他文件可下载
```

### AC-F12-02 · 超限文件被拒绝

- Parent: REQ-F12-01
- Priority: P1
- EARS:

```text
WHEN 成员上传单个超过 50MB 或格式不在允许范围内的文件
THE SYSTEM SHALL 拒绝该文件并显示文件名与原因，同批其他合格文件照常上传
```

### AC-F12-03 · 删除改为作废并留痕

- Parent: REQ-F12-01
- Priority: P1
- EARS:

```text
WHEN 资料上传者删除自己上传的一个资料文件
THE SYSTEM SHALL 将该文件标记为已作废并从默认列表隐藏，记录作废人与时间；被核对、签认或变更单引用的文件不能作废
```

### REQ-F12-02 · 阶段验收图片

- Story: US-F12-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F12-04 · 上传与状态切换

- Parent: REQ-F12-02
- Priority: P1
- EARS:

```text
WHEN 成员在工段页上传验收图片或切换其状态
THE SYSTEM SHALL 保存图片并在「施工中 → 待复验 → 已验收」之间切换状态，新上传图片默认为「待复验」
```

### REQ-F12-03 · 房屋档案分类资料

- Story: US-F12-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F12-05 · 默认分类与分类管理

- Parent: REQ-F12-03
- Priority: P1
- EARS:

```text
WHEN 公司管理员或项目经理在平面布局图、三维效果图或装修合同专区新建、改名或删除分类
THE SYSTEM SHALL 保存分类变更；删除仅允许空分类，非空分类提示先移出文件
```

### AC-F12-06 · 合同专区仅限相关角色查看

- Parent: REQ-F12-03
- Priority: P1
- EARS:

```text
WHEN 设计经理或质检打开装修合同专区
THE SYSTEM SHALL 拒绝访问并提示「无权查看合同资料」；业主、项目经理、预算专员和公司管理员可以查看
```

## Feature F13 · 补充事项与公告栏

### US-F13-01 · 记录口头约定与待办

- Role: 项目经理
- Goal: 把口头约定、增项和待办登记成台账
- Value: 约定有据可查
- Stage: 全量交付
- Status: active

### US-F13-02 · 各方在公告栏留言沟通

- Role: 业主
- Goal: 在公告栏发布留言和回复
- Value: 沟通留痕
- Stage: 全量交付
- Status: active

### REQ-F13-01 · 补充事项台账

- Story: US-F13-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F13-01 · 登记与状态流转

- Parent: REQ-F13-01
- Priority: P1
- EARS:

```text
WHEN 成员登记补充事项（标题、说明、提出日期、约定完成日期、责任人）或切换其状态
THE SYSTEM SHALL 保存条目，状态在「待处理 → 处理中 → 已完成」之间切换，未完成条目排在前面
```

### AC-F13-02 · 涉及费用或做法时转为变更单

- Parent: REQ-F13-01
- Priority: P1
- EARS:

```text
WHEN 项目经理对一条补充事项选择「转为变更单」
THE SYSTEM SHALL 生成预填了内容与附件的变更单草稿，并在补充事项中关联该变更单编号
```

### REQ-F13-02 · 公告栏

- Story: US-F13-02
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F13-03 · 留言按发布者身份归入板块

- Parent: REQ-F13-02
- Priority: P1
- EARS:

```text
WHEN 已登录成员发布留言
THE SYSTEM SHALL 留言人取登录账号姓名，按其角色归入业主、工地经理或设计师板块（其他角色归入工地经理板块），并按时间倒序显示
```

### AC-F13-04 · 回复与删除

- Parent: REQ-F13-02
- Priority: P1
- EARS:

```text
WHEN 成员回复一条留言，或删除自己发布的留言
THE SYSTEM SHALL 回复挂在原留言下按时间正序显示；删除的留言显示为「该留言已删除」并保留删除记录，不能删除他人留言
```

## Feature F14 · 计划变更留档

### US-F14-01 · 项目经理调整工段计划并自动留档

- Role: 项目经理
- Goal: 调整工段起止日期、班组、权重和施工范围
- Value: 计划变化可追溯
- Stage: 全量交付
- Status: active

### REQ-F14-01 · 逐字段比对留档

- Story: US-F14-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F14-01 · 有变化才追加记录

- Parent: REQ-F14-01
- Priority: P0
- EARS:

```text
WHEN 项目经理保存工段计划，起止日期、班组负责人、权重或施工范围中至少一项发生变化
THE SYSTEM SHALL 追加一条留档记录，包含时间、工段、每个变化字段的变更前后值、日期变化带来的工期增减天数和原因备注
```

### AC-F14-02 · 无变化不产生记录

- Parent: REQ-F14-01
- Priority: P1
- EARS:

```text
WHEN 项目经理保存工段计划但所有字段均未变化
THE SYSTEM SHALL 不追加留档记录
```

### AC-F14-03 · 开始晚于结束被拒绝

- Parent: REQ-F14-01
- Priority: P0
- EARS:

```text
WHEN 项目经理保存的工段计划开始日期晚于结束日期
THE SYSTEM SHALL 拒绝保存并提示「开始日期不能晚于结束日期」
```

### REQ-F14-02 · 留档导出

- Story: US-F14-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F14-04 · 导出 CSV

- Parent: REQ-F14-02
- Priority: P1
- EARS:

```text
WHEN 成员导出计划变更留档
THE SYSTEM SHALL 生成 CSV，列为记录时间、工段、变更项、变更前、变更后、工期影响（天）、变更原因备注
```

## Feature F15 · 付款节点提示

### US-F15-01 · 预算专员维护付款节点并看到未放行提示

- Role: 预算专员
- Goal: 维护合同付款节点
- Value: 付款前看清证据链是否齐全
- Stage: 全量交付
- Status: active

### REQ-F15-01 · 维护付款节点

- Story: US-F15-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F15-01 · 录入节点

- Parent: REQ-F15-01
- Priority: P1
- EARS:

```text
WHEN 预算专员录入付款节点名称、金额（元）、计划日期和关联工段
THE SYSTEM SHALL 保存节点，状态为「未付」
```

### REQ-F15-02 · 付款前提示但不拦截

- Story: US-F15-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F15-02 · 显示未放行检查点与未闭环不一致数

- Parent: REQ-F15-02
- Priority: P1
- EARS:

```text
WHEN 任一成员查看付款节点
THE SYSTEM SHALL 显示关联工段内未放行的检查点数和未闭环的不一致问题数
```

### AC-F15-03 · 仍有未放行时二次确认后允许标记已付

- Parent: REQ-F15-02
- Priority: P1
- EARS:

```text
WHEN 预算专员将一个关联工段仍有未放行检查点的付款节点标记为已付
THE SYSTEM SHALL 弹出「还有 N 个检查点未放行，确认标记已付？」，确认后标记为已付并留痕，取消则不变
```

## Feature F16 · 待办与提醒

### US-F16-01 · 成员在网页内看到自己的待办并催办他人

- Role: 业主
- Goal: 登录后立刻看到需要自己处理的事，并能一键催办
- Value: 不再靠翻微信群找事
- Stage: 全量交付
- Status: active

### REQ-F16-01 · 我的待办

- Story: US-F16-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F16-01 · 按角色汇总待办

- Parent: REQ-F16-01
- Priority: P0
- EARS:

```text
WHEN 成员登录后打开首页
THE SYSTEM SHALL 列出其在各项目中待处理的事项：业主为待签基线、待签图纸、待签变更单和待放行检查点；业主代理人为待放行检查点；质检为待核对检查点；预算专员为待预算定价变更单；设计经理为待出新版图纸；项目经理为被退回基线、被驳回变更单和即将施工未签基线，并在导航上显示总数
```

### AC-F16-02 · 处理后待办消失

- Parent: REQ-F16-01
- Priority: P0
- EARS:

```text
WHEN 成员完成一项待办对应的操作
THE SYSTEM SHALL 该待办从列表中移除，导航上的数量同步减少
```

### REQ-F16-02 · 一键复制催办消息

- Story: US-F16-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F16-03 · 生成带链接的消息文本

- Parent: REQ-F16-02
- Priority: P0
- EARS:

```text
WHEN 成员对任一待办或记录点击「复制微信消息」
THE SYSTEM SHALL 将包含项目名、事项、负责人、截止或超时信息和直达链接的文本复制到剪贴板，并提示「已复制」
```

## Feature F17 · 审计留痕与证据包

### US-F17-01 · 业主相信记录没有被改过并能随时导出

- Role: 业主
- Goal: 确认关键记录不可篡改，并自主导出证据包
- Value: 证据由公司托管也可信
- Stage: 全量交付
- Status: active

### REQ-F17-01 · 关键记录只追加

- Story: US-F17-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F17-01 · 任何角色不能修改或删除关键记录

- Parent: REQ-F17-01
- Priority: P0
- EARS:

```text
WHEN 任何角色（含公司管理员）通过页面或接口尝试修改或删除签认、核对、放行、变更单状态、图纸版本、问题状态变化或计划留档记录
THE SYSTEM SHALL 拒绝该操作，原记录保持不变；更正只能通过追加新记录完成
```

### REQ-F17-02 · 摘要串联与完整性校验

- Story: US-F17-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F17-02 · 每条关键记录带串联摘要

- Parent: REQ-F17-02
- Priority: P0
- EARS:

```text
WHEN 系统写入一条关键记录
THE SYSTEM SHALL 为其计算包含记录内容和上一条关键记录摘要的 SHA-256 摘要并保存
```

### AC-F17-03 · 完整性校验结果

- Parent: REQ-F17-02
- Priority: P0
- EARS:

```text
WHEN 业主或公司管理员在项目中执行完整性校验
THE SYSTEM SHALL 逐条重算摘要链，全部一致时显示「完整」，否则显示第一条不一致记录的编号和时间
```

### REQ-F17-03 · 证据包导出

- Story: US-F17-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F17-04 · 按范围导出证据包

- Parent: REQ-F17-03
- Priority: P0
- EARS:

```text
WHEN 业主选择项目内的工段、楼层、房间或时间范围导出证据包
THE SYSTEM SHALL 生成 ZIP 文件，包含所选范围内的记录清单（.xlsx）、照片原件、相关图纸版本文件、签认内容快照和摘要清单（含导出时的链尾摘要）
```

### AC-F17-05 · 非业主方的导出权限

- Parent: REQ-F17-03
- Priority: P1
- EARS:

```text
WHEN 项目经理、设计经理、质检或预算专员尝试导出证据包
THE SYSTEM SHALL 拒绝导出并提示「仅业主和公司管理员可导出证据包」
```

### REQ-F17-04 · 操作日志

- Story: US-F17-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F17-06 · 写操作留日志

- Parent: REQ-F17-04
- Priority: P1
- EARS:

```text
WHEN 任一成员在项目内完成一次新增、修改、作废或状态变更操作
THE SYSTEM SHALL 记录操作人、时间、对象、变更前后值，业主和公司管理员可以按时间和对象筛选查看
```

## Feature F18 · 原型数据迁移

### US-F18-01 · 公司管理员把原型里的已有数据导入新平台

- Role: 公司管理员
- Goal: 把原型 v1.20 导出的 JSON 备份导入对应项目
- Value: 砌墙阶段已录的数据不丢
- Stage: 全量交付
- Status: active

### REQ-F18-01 · 导入原型 JSON 备份

- Story: US-F18-01
- Stage: 全量交付
- Revision: 1
- Status: active

### AC-F18-01 · 导入可识别内容并标注来源

- Parent: REQ-F18-01
- Priority: P2
- EARS:

```text
WHEN 公司管理员向一个筹备中的项目上传原型 v1.20 导出的 JSON 备份
THE SYSTEM SHALL 导入其中的工作事项、问题、人工出勤登记、计划变更留档、补充事项、公告留言和验收图片，每条标注来源「原型导入」，且不生成任何签认、核对或放行记录
```

### AC-F18-02 · 文件本体缺失时标记

- Parent: REQ-F18-01
- Priority: P2
- EARS:

```text
WHEN JSON 备份中的资料文件只有元数据没有文件本体
THE SYSTEM SHALL 导入元数据并将该文件标记为「文件缺失，需重新上传」
```

### AC-F18-03 · 格式错误时拒绝

- Parent: REQ-F18-01
- Priority: P2
- EARS:

```text
WHEN 公司管理员上传的文件不是可解析的原型 JSON 备份
THE SYSTEM SHALL 拒绝导入并提示「不是有效的原型备份文件」，项目数据不变
```

## Non-functional requirements

### NFR-001 · 手机现场可用

- Revision: 1
- Status: active
- Measure: 在 360–430px 宽的手机屏幕上，检查点核对、放行、基线签认、变更单签认四个流程的页面无横向滚动，可直接调起相机拍照上传；在 1280px 及以上宽度的电脑上，总览与矩阵完整显示。

### NFR-002 · 响应时间

- Revision: 1
- Status: active
- Measure: 在 20 个并发用户下，除文件上传下载外的页面数据接口 P95 响应时间不超过 1 秒；单张 10MB 照片在 10Mbps 上行网络下上传完成不超过 15 秒；证据包导出 1000 张照片以内不超过 5 分钟。

### NFR-003 · 服务端权限校验

- Applies-to: REQ-F01-03
- Revision: 1
- Status: active
- Measure: 所有读写接口在服务端按「项目 × 角色」校验权限；不依赖前端隐藏按钮。越权请求 100% 被拒绝。

### NFR-004 · 关键记录防篡改

- Applies-to: REQ-F17-01
- Revision: 1
- Status: active
- Measure: 关键记录在应用层不提供修改和删除路径，数据库账号对关键记录表只授予插入和查询权限；摘要链完整性校验覆盖 100% 的关键记录。

### NFR-005 · 备份与恢复

- Revision: 2
- Status: active
- Measure: 每日自动备份数据库，并核对对象存储文件清单，备份保留 30 天；文件存于服务器本地磁盘（对象存储未到位）时，每日备份还须同步到公司提供的异地位置；数据恢复点不超过 24 小时，恢复演练后摘要链校验结果为「完整」。

### NFR-006 · 密码安全

- Applies-to: REQ-F02-02
- Revision: 2
- Status: active
- Measure: 密码至少 8 位，必须同时包含字母和数字，以加盐慢哈希（bcrypt 或 argon2）存储；除公司管理员重置密码时在弹窗中一次性显示的临时密码外，任何界面和日志都不显示明文密码；临时密码不落日志。

### NFR-007 · 浏览器兼容

- Revision: 1
- Status: active
- Measure: 支持 Chrome 与 Edge 最新两个大版本、iOS Safari 16 及以上、安卓微信内置浏览器（当前版本）。

### NFR-008 · 时间与格式

- Revision: 1
- Status: active
- Measure: 全部日期按 Asia/Shanghai 时区计算与显示，日期格式为 YYYY-MM-DD，时间为 24 小时制；关键记录时间取服务器时间。

### NFR-009 · 容量

- Revision: 1
- Status: active
- Measure: 单个项目在 1000 个工作项、5000 个检查点、20000 张照片规模下，上述响应时间指标仍满足。
