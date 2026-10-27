# Design System Inspired by 君华装修项目管理平台

> Category: Productivity & SaaS
> 浅色、信息密集的工地协作台。用印章式状态标签一眼区分「已放行 / 不得覆盖 / 待重签」，所有关键操作都可追溯。

## 视觉主题与氛围

- **视觉方向**：沿用原型 v1.20 的浅灰底、白卡片、蓝色品牌色和工段色板（蓝图 §6），在上面叠加一套「印章」语言来表达证据链状态。
- **用户情绪**：可信、冷静、有掌控感。业主要相信记录没被改过；质检在现场要快速、确定地完成一次核对。
- **设计理由**：
  - 工地白天强光下，浅色更易读，所以只做浅色。
  - 用户已习惯原型的信息密度，沿用可以降低迁移成本。
- **风格定位**：B 端数据工作台，接近 Linear 的克制，但不用玻璃拟态和渐变边框，用弥散阴影和留白区分层级。
- **参考先例**：
  - 原型 v1.20：色板、导航、卡片密度。
  - PlanRadar / Fieldwire：图纸钉点与照片关联的交互。
  - 中国传统印章：签认与放行的「盖章」隐喻，也是本系统的签名。

| 核心色 | Hex | 角色 |
|---|---|---|
| 页面底 | #f4f6f9 | --bg |
| 卡片 | #ffffff | --surface |
| 正文 | #111827 | --fg |
| 品牌蓝 | #1e5fd0 | --accent |
| 放行绿 | #15803d | --success |
| 待办橙 | #b45309 | --warn |
| 不得覆盖红 | #c62828 | --danger |

## 色彩美学

- **用途**：
  - 中性色承载内容。
  - 品牌蓝只用于主操作和当前导航。
  - 绿、橙、红只表达证据链状态和问题等级。
  - 工段色只用来区分六个工段（色条、图例、进度条）。
- **强调色纪律**：`--accent` 每屏最多 2 处可见使用，通常是一个主按钮加当前导航项，链接、hover 和 focus ring 也计入。画面占比上限：中性色 70–90%，accent 5–10%，语义色 0–5%。印章标签属于语义色，每张卡片最多 1 个。

| Surface | Hex | 理由 |
|---|---|---|
| --bg | #f4f6f9 | 微冷灰底，衬托白卡片，形成「纸张在桌面」的层级 |
| --surface | #ffffff | 卡片与表格 |
| --surface-warm | #f7f9fc | 表头、筛选条、只读区 |
| --border | #d5dce6 | 输入框与分隔线 |
| --border-soft | #e3e8ef | 卡片描边与表格行线 |

| Accent / 语义 | Hex | 情感定义 |
|---|---|---|
| --accent | #1e5fd0 | 可靠、可操作 |
| --success | #15803d | 已签认、已放行、已闭环 |
| --warn | #b45309 | 待处理、待重签、超时前 |
| --danger | #c62828 | 不得覆盖、不一致、超时、未放行先覆盖 |
| --info | #0f766e | 代理放行、说明性提示 |

| Text | Hex | 与 --surface / --bg 的对比度 |
|---|---|---|
| --fg | #111827 | 17.74 / 16.39 |
| --fg-2 | #374151 | 10.31 / 9.52 |
| --muted / --meta | #5b6779 | 5.74 / 5.30 |
| --accent-on（白字压在 --accent 上） | #ffffff | 5.83 |

全部文本配对实测对比度 ≥ 4.5:1（WCAG 2.2 AA，2026-10-27 用公式计算），包括语义色压在其浅底上：warn 4.57、danger 4.92、success 4.50、accent 5.14。

```css
:root { /* 见 tokens.css，页面通过 <link rel="stylesheet" href="../tokens.css"> 加载 */ }
```

## 排版与字体

- **字体选择**：系统中文字体栈，零加载成本，弱网工地也能即时显示。数字使用 `font-variant-numeric: tabular-nums`，保证表格对齐。
- **字号梯度**：12 / 13 / 15 / 17 / 20 / 24 / 30 / 36。正文 15px 保证手机现场可读；表格内用 13px 提高密度；KPI 数值用 30px。

| 场景 | 字号 | letter-spacing | line-height |
|---|---|---|---|
| KPI 数值 | --text-3xl | -0.01em | 1.1 |
| 页面标题 | --text-xl | -0.01em | --leading-tight |
| 卡片标题 | --text-lg | 0 | --leading-tight |
| 正文 | --text-base | 0 | --leading-body |
| 表格与小字 | --text-sm / --text-xs | 0.01em | 1.5 |
| 按钮与标签 | --text-sm | 0.02em | 1 |
| 全大写英文（如 PAGE ID） | --text-xs | 0.06em | 1 |

```
Font labels for catalog extraction:

Display: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", sans-serif
Body: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", sans-serif
Mono: "SF Mono", "JetBrains Mono", Menlo, Consolas, "Courier New", monospace
```

## 间距与布局

- **间距**：4px 基准（--space-1 至 --space-12）。卡片内边距 16px，卡片之间 16px，区块之间 24px（手机端 16px）。
- **布局**：
  - **电脑（≥ 1200px）**：左侧导航 260px 加主区，主区最大宽度 1440px。
  - **平板（768–1199px）**：导航收为图标栏。
  - **手机（< 768px）**：无侧栏，底部 60px 标签栏，四个标签为待办、检查点、图纸、更多；主区左右留 16px。
  - **KPI 卡片**：电脑端 6 列，平板 3 列，手机 2 列。
  - **表格**：手机端外层可横向滚动，页面本身不出现横向滚动（NFR-001）。
- **层级**：靠阴影而不是粗边框。卡片用 --elev-raised，弹窗用 --elev-float，表格行用 1px --border-soft 分隔。

```css
.app{display:grid;grid-template-columns:var(--sidebar-w) minmax(0,1fr);min-height:100vh;background:var(--bg);color:var(--fg);font:var(--text-base)/var(--leading-body) var(--font-body)}
.side{background:var(--surface);box-shadow:var(--elev-ring);position:sticky;top:0;height:100vh;overflow-y:auto;padding:var(--space-3)}
.main{min-width:0;padding:var(--section-y-desktop) var(--container-gutter-desktop);max-width:var(--container-max)}
.tabbar{display:none}
.grid-kpi{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:var(--space-4)}
@media (max-width:1199px){.app{grid-template-columns:64px minmax(0,1fr)}.side .nm,.side .navgroup{display:none}.grid-kpi{grid-template-columns:repeat(3,minmax(0,1fr))}.main{padding:var(--section-y-tablet) var(--container-gutter-tablet)}}
@media (max-width:767px){.app{grid-template-columns:1fr}.side{display:none}.main{padding:var(--section-y-phone) var(--container-gutter-phone) calc(var(--tabbar-h) + var(--space-4))}.grid-kpi{grid-template-columns:repeat(2,minmax(0,1fr))}
  .tabbar{display:grid;grid-template-columns:repeat(4,1fr);position:fixed;left:0;right:0;bottom:0;height:var(--tabbar-h);background:var(--surface);box-shadow:var(--elev-float)}}
.scroll-x{overflow-x:auto;-webkit-overflow-scrolling:touch}
```

## 组件设计

**交互哲学：色彩响应型。** hover 只改边框色或背景色，不用位移，也不抬升阴影，全站统一。

```css
/* 按钮：主按钮每屏 1 个 */
.btn{display:inline-flex;align-items:center;gap:var(--space-2);height:36px;padding:0 var(--space-4);border-radius:var(--radius-sm);border:1px solid var(--border);background:var(--surface);color:var(--fg);font:500 var(--text-sm)/1 var(--font-body);letter-spacing:.02em;cursor:pointer;transition:background var(--motion-fast) var(--ease-standard),border-color var(--motion-fast) var(--ease-standard)}
.btn:hover{border-color:var(--accent);background:var(--surface-warm)}
.btn:active{background:var(--border-soft)}
.btn:focus-visible{outline:none;box-shadow:var(--focus-ring)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-on)}
.btn.primary:hover{background:var(--accent-hover);border-color:var(--accent-hover)}
.btn.primary:active{background:var(--accent-active)}
.btn.danger{color:var(--danger);border-color:color-mix(in oklab,var(--danger),transparent 60%)}
.btn.danger:hover{background:var(--danger-soft);border-color:var(--danger)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn.sm{height:30px;padding:0 var(--space-3);font-size:var(--text-xs)}
.btn.block{width:100%;justify-content:center;height:44px} /* 手机现场主操作，触控高度 44px */

/* 卡片 */
.card{background:var(--surface);border-radius:var(--radius-md);box-shadow:var(--elev-raised);border:1px solid var(--border-soft);margin-bottom:var(--space-4);transition:border-color var(--motion-fast) var(--ease-standard)}
.card.link:hover{border-color:var(--accent)}
.card.link:active{background:var(--surface-warm)}
.card.link:focus-visible{outline:none;box-shadow:var(--focus-ring)}
.card-hd{display:flex;align-items:center;gap:var(--space-3);padding:var(--space-3) var(--space-4);border-bottom:1px solid var(--border-soft)}
.card-hd h2{font-size:var(--text-lg);font-weight:600;line-height:var(--leading-tight)}
.card-bd{padding:var(--space-4)}

/* KPI */
.kpi{background:var(--surface);border-radius:var(--radius-md);box-shadow:var(--elev-raised);padding:var(--space-4)}
.kpi .lb{font-size:var(--text-sm);color:var(--muted)}
.kpi .vl{font-size:var(--text-3xl);font-weight:700;letter-spacing:-.01em;line-height:1.1;font-variant-numeric:tabular-nums}
.kpi .target{font-size:var(--text-xs);color:var(--muted)}

/* 输入框 */
.input,.select,.textarea{width:100%;min-height:40px;padding:var(--space-2) var(--space-3);border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface);color:var(--fg);font:var(--text-base)/1.4 var(--font-body);transition:border-color var(--motion-fast) var(--ease-standard)}
.input:hover,.select:hover,.textarea:hover{border-color:var(--muted)}
.input:focus-visible,.select:focus-visible,.textarea:focus-visible{outline:none;border-color:var(--accent);box-shadow:var(--focus-ring)}
.input:active{border-color:var(--accent)}
.field{display:flex;flex-direction:column;gap:var(--space-1)}
.field label{font-size:var(--text-sm);color:var(--fg-2)}
.field label .req{color:var(--danger)}
.field .err{font-size:var(--text-xs);color:var(--danger)}
.field.invalid .input{border-color:var(--danger)}

/* 普通标签 */
.tag{display:inline-flex;align-items:center;height:22px;padding:0 var(--space-2);border-radius:var(--radius-pill);font-size:var(--text-xs);font-weight:600;letter-spacing:.02em;background:var(--surface-warm);color:var(--muted)}
.tag.ok{background:var(--success-soft);color:var(--success)}
.tag.warn{background:var(--warn-soft);color:var(--warn)}
.tag.bad{background:var(--danger-soft);color:var(--danger)}
.tag.brand{background:var(--accent-soft);color:var(--accent)}

/* ★ 设计签名：印章式状态标签 */
.seal{display:inline-flex;align-items:center;gap:var(--space-1);padding:2px var(--space-2);border:2px solid currentColor;border-radius:var(--radius-sm);font:700 var(--text-xs)/1.3 var(--font-display);letter-spacing:.08em;transform:rotate(-3deg);background:color-mix(in oklab,currentColor,transparent 92%);white-space:nowrap}
.seal.pass{color:var(--success)}      /* 已签认 / 已放行 / 已闭环 */
.seal.stop{color:var(--danger)}       /* 不得覆盖 / 不一致 / 超时 / 未放行先覆盖 */
.seal.pend{color:var(--warn)}         /* 待签认 / 待放行 / 待重签 / 待预算定价 */
.seal.proxy{color:var(--info)}        /* 代理放行 */
.seal:focus-visible{outline:none;box-shadow:var(--focus-ring)}

/* 表格 */
table{width:100%;border-collapse:collapse;font-size:var(--text-sm)}
th{background:var(--surface-warm);color:var(--muted);font-weight:600;text-align:left;padding:var(--space-2) var(--space-3);letter-spacing:.01em}
td{padding:var(--space-2) var(--space-3);border-top:1px solid var(--border-soft);vertical-align:top}
tr.row-link{cursor:pointer;transition:background var(--motion-fast) var(--ease-standard)}
tr.row-link:hover{background:var(--surface-warm)}
tr.row-link:active{background:var(--border-soft)}
tr.row-link:focus-visible{outline:none;box-shadow:inset var(--focus-ring)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}

/* 导航项 */
.navitem{display:flex;align-items:center;gap:var(--space-2);padding:var(--space-2) var(--space-3);border-radius:var(--radius-sm);color:var(--fg-2);text-decoration:none;font-size:var(--text-base);transition:background var(--motion-fast) var(--ease-standard)}
.navitem:hover{background:var(--surface-warm)}
.navitem:active{background:var(--border-soft)}
.navitem:focus-visible{outline:none;box-shadow:var(--focus-ring)}
.navitem.on{background:var(--accent-soft);color:var(--accent);font-weight:600}
.navgroup{font-size:var(--text-xs);color:var(--muted);letter-spacing:.06em;padding:var(--space-4) var(--space-3) var(--space-1)}
.badge{min-width:18px;height:18px;padding:0 5px;border-radius:var(--radius-pill);background:var(--danger);color:var(--accent-on);font-size:11px;font-weight:700;display:inline-flex;align-items:center;justify-content:center}

/* chips 筛选 */
.chip{display:inline-flex;align-items:center;height:30px;padding:0 var(--space-3);border-radius:var(--radius-pill);border:1px solid var(--border);background:var(--surface);font-size:var(--text-sm);cursor:pointer;transition:border-color var(--motion-fast) var(--ease-standard)}
.chip:hover{border-color:var(--accent)}
.chip:active{background:var(--surface-warm)}
.chip:focus-visible{outline:none;box-shadow:var(--focus-ring)}
.chip.on{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}

/* 进度条 */
.pbar{height:6px;border-radius:var(--radius-pill);background:var(--border-soft);overflow:hidden}
.pbar>i{display:block;height:100%;background:var(--accent);border-radius:inherit}

/* 弹窗与二次确认摘要 */
.mask{position:fixed;inset:0;background:color-mix(in oklab,var(--fg),transparent 55%);display:none;align-items:center;justify-content:center;padding:var(--space-4)}
.mask.show{display:flex;animation:fadeIn var(--motion-base) var(--ease-standard)}
.dialog{background:var(--surface-overlay);border-radius:var(--radius-lg);box-shadow:var(--elev-float);width:min(560px,100%);max-height:90vh;overflow:auto;animation:dialogIn var(--motion-base) var(--ease-standard)}
.confirm-summary{background:var(--surface-warm);border-radius:var(--radius-sm);padding:var(--space-3);font-size:var(--text-sm)}
.confirm-summary dt{color:var(--muted)}
.confirm-summary dd{color:var(--fg);margin-bottom:var(--space-2)}

/* 提示条 */
.toast{position:fixed;top:var(--space-4);left:50%;transform:translateX(-50%);background:var(--fg);color:var(--surface);padding:var(--space-2) var(--space-4);border-radius:var(--radius-sm);font-size:var(--text-sm);box-shadow:var(--elev-float);animation:toastIn var(--motion-base) var(--ease-standard)}

/* 状态页：空 / 加载 / 错误 / 无权限 */
.state{text-align:center;padding:var(--space-12) var(--space-4);color:var(--muted)}
.state .ic{font-size:32px;margin-bottom:var(--space-2)}
.skeleton{background:linear-gradient(90deg,var(--border-soft),var(--surface-warm),var(--border-soft));background-size:200% 100%;border-radius:var(--radius-sm);animation:shimmer 1.2s linear infinite;height:14px}

/* 手机底部标签 */
.tab{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;color:var(--muted);text-decoration:none;font-size:var(--text-xs)}
.tab:hover{color:var(--fg)}
.tab:active{background:var(--surface-warm)}
.tab:focus-visible{outline:none;box-shadow:inset var(--focus-ring)}
.tab.on{color:var(--accent);font-weight:600}
```

设计说明：
- 圆角 6/10/14px，既不显得锋利，也不松散。
- 印章倾斜 -3°、2px 描边、字距 0.08em，是唯一允许的「不规整」元素，让签认和放行有盖章的分量。
- 主操作在手机上为通栏 44px 高，方便戴手套或单手操作。

## 动效与交互物理

动效只用来确认操作和切换状态，不用来装饰。

```css
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes dialogIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes toastIn{from{opacity:0;transform:translate(-50%,-6px)}to{opacity:1;transform:translate(-50%,0)}}
@keyframes shimmer{from{background-position:200% 0}to{background-position:-200% 0}}
@keyframes sealStamp{0%{opacity:0;transform:rotate(-3deg) scale(1.4)}60%{opacity:1;transform:rotate(-3deg) scale(.96)}100%{transform:rotate(-3deg) scale(1)}}
.seal.just{animation:sealStamp var(--motion-base) var(--ease-standard)} /* 签认 / 放行成功的那一刻盖章 */
.card.enter{animation:fadeIn var(--motion-base) var(--ease-standard) both}
.card.enter:nth-child(2){animation-delay:40ms}.card.enter:nth-child(3){animation-delay:80ms}.card.enter:nth-child(4){animation-delay:120ms}
.tabpanel{transition:opacity var(--motion-fast) var(--ease-standard)}
.drawer{transition:transform var(--motion-base) var(--ease-standard)}
@media (prefers-reduced-motion:reduce){
  .seal.just,.card.enter,.mask.show,.dialog,.toast,.skeleton{animation:none}
  .drawer,.tabpanel,.btn,.card,.chip,.navitem,.input{transition:none}
}
```

## 品牌情感与声音

- **品牌灵魂**：一位严谨、可靠的监理。话不多，记性好，从不篡改。
- **文案声音**：直接、具体、不卖萌。例如「至少上传 1 张现场照片」，不写「哎呀，好像少了点什么」。
- **边缘时刻**：
  - 空状态：「还没有检查点。先在工作项基线里添加检查点。」配主操作按钮。
  - 加载：骨架屏，不用转圈。
  - 错误：说明原因和下一步，例如「上传失败（网络中断），已保存在本机草稿，可重新上传」。
  - 无权限：「无权访问该项目」加返回我的待办。
- **装饰**：不用插画，状态图标只用简单字符或线性图标。
- **给生成 HTML 的 Agent 的指令**：
  - 只用 tokens.css 变量，组件直接复用本文件的类名。
  - 状态一律用 `.seal`，每张卡片最多 1 个。
  - 主按钮每屏 1 个。
  - 手机端检查本页面是否出现横向滚动。
  - 页面数据使用君华工地的真实中文样例：砌墙阶段、二楼书房 B 门洞净宽 860mm 与图纸 900mm 不符等。

## 设计禁忌

- 禁止用 `.seal` 以外的样式表达签认或放行状态。印章是证据链的唯一视觉语言，混用会让业主误判是否合规。
- 禁止在一张卡片上出现 2 个以上印章，否则「哪个状态说了算」会变得含糊。
- 禁止 hover 时用位移或阴影抬升。全站统一为色彩响应，混搭会显得廉价，也会干扰密集表格的阅读。
- 禁止对签认、放行、驳回、作废、标记已覆盖、标记已付使用单击直接提交。这些操作不可撤回，必须先展示确认内容摘要。
- 禁止任何可点击区域在手机上小于 40×40px。现场用户可能戴手套或单手操作。
- 禁止深色模式和大面积彩色背景。工地强光下的可读性优先。
- 禁止在页面中硬编码颜色值，必须使用 `var(--xxx)`，以保证 tokens.css 是唯一事实源。
- 禁止用工段色表达状态。工段色只区分工段，状态只用语义色。
