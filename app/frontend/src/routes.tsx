// 28 个页面路由（页面清单.md）。路由 → PAGE ID 一一对应。
import { lazy } from "react";

export const ROUTES = [
  { path: "/login", Component: lazy(() => import("./pages/PAGE-F02-01")) },  // PAGE-F02-01 登录
  { path: "/invite/:token", Component: lazy(() => import("./pages/PAGE-F02-02")) },  // PAGE-F02-02 邀请落地
  { path: "/me", Component: lazy(() => import("./pages/PAGE-F02-03")) },  // PAGE-F02-03 个人设置
  { path: "/", Component: lazy(() => import("./pages/PAGE-F16-01")) },  // PAGE-F16-01 我的待办
  { path: "/admin/projects", Component: lazy(() => import("./pages/PAGE-F01-01")) },  // PAGE-F01-01 项目管理
  { path: "/p/:pid/members", Component: lazy(() => import("./pages/PAGE-F01-02")) },  // PAGE-F01-02 成员与项目
  { path: "/forbidden", Component: lazy(() => import("./pages/PAGE-F01-03")) },  // PAGE-F01-03 无权限
  { path: "/admin/templates", Component: lazy(() => import("./pages/PAGE-F03-01")) },  // PAGE-F03-01 公司模板与工序说明库
  // 页面规格与验收契约中的地址（/company/*）与技术方案路由（/admin/*）等价
  { path: "/company/projects", Component: lazy(() => import("./pages/PAGE-F01-01")) },
  { path: "/company/templates", Component: lazy(() => import("./pages/PAGE-F03-01")) },
  { path: "/p/:pid/structure", Component: lazy(() => import("./pages/PAGE-F03-02")) },  // PAGE-F03-02 项目结构
  { path: "/p/:pid/import", Component: lazy(() => import("./pages/PAGE-F03-03")) },  // PAGE-F03-03 数据导入导出
  { path: "/experience", Component: lazy(() => import("./pages/PAGE-F09-01")) },  // PAGE-F09-01 公司经验库
  { path: "/p/:pid", Component: lazy(() => import("./pages/PAGE-F10-01")) },  // PAGE-F10-01 项目总览
  { path: "/p/:pid/floors", Component: lazy(() => import("./pages/PAGE-F10-02")) },  // PAGE-F10-02 楼层 / 房间
  { path: "/p/:pid/phase/:phaseId", Component: lazy(() => import("./pages/PAGE-F10-03")) },  // PAGE-F10-03 工段详情
  { path: "/p/:pid/work-items/:wid", Component: lazy(() => import("./pages/PAGE-F05-01")) },  // PAGE-F05-01 工作项详情
  { path: "/p/:pid/baselines", Component: lazy(() => import("./pages/PAGE-F05-02")) },  // PAGE-F05-02 基线签认
  { path: "/p/:pid/drawings", Component: lazy(() => import("./pages/PAGE-F04-01")) },  // PAGE-F04-01 图纸
  { path: "/p/:pid/drawings/:versionId", Component: lazy(() => import("./pages/PAGE-F04-02")) },  // PAGE-F04-02 图纸查看器
  { path: "/p/:pid/checkpoints", Component: lazy(() => import("./pages/PAGE-F06-01")) },  // PAGE-F06-01 检查点
  { path: "/p/:pid/checkpoints/:cid", Component: lazy(() => import("./pages/PAGE-F06-02")) },  // PAGE-F06-02 检查点详情
  { path: "/p/:pid/changes", Component: lazy(() => import("./pages/PAGE-F07-01")) },  // PAGE-F07-01 变更单
  { path: "/p/:pid/changes/:coid", Component: lazy(() => import("./pages/PAGE-F07-02")) },  // PAGE-F07-02 变更单详情
  { path: "/p/:pid/issues", Component: lazy(() => import("./pages/PAGE-F08-01")) },  // PAGE-F08-01 问题
  { path: "/p/:pid/archive", Component: lazy(() => import("./pages/PAGE-F12-01")) },  // PAGE-F12-01 档案资料
  { path: "/p/:pid/supplements", Component: lazy(() => import("./pages/PAGE-F13-01")) },  // PAGE-F13-01 补充事项
  { path: "/p/:pid/notices", Component: lazy(() => import("./pages/PAGE-F13-02")) },  // PAGE-F13-02 公告栏
  { path: "/p/:pid/payments", Component: lazy(() => import("./pages/PAGE-F15-01")) },  // PAGE-F15-01 付款节点
  { path: "/p/:pid/audit", Component: lazy(() => import("./pages/PAGE-F17-01")) },  // PAGE-F17-01 审计与证据包
];
