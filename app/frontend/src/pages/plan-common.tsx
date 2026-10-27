// 结构与计划各页共用：类型、数值格式、完成度矩阵（内联 SVG）、计划留档表、问题状态印章。
import type { ReactNode } from "react";
import { useNavigate } from "react-router";
import { Seal } from "../ui";
import "../styles/pages/plan-common.css";

export type PhaseBrief = { id: number; code: string; name: string; colorVar: string; plannedStart: string; plannedEnd: string };
export type MatrixRow = { id: number | "all"; name: string; floorId?: number; floorName?: string; cells: (number | null)[] };
export type IssueBrief = {
  id: number; code: string; phaseId: number | null; phaseName: string; phaseColor: string; floorId: number | null; roomId: number | null;
  floorName: string; roomName: string; description: string; level: string; status: string; ownerName: string;
  foundOn: string; dueDate: string | null; closedOn: string | null; overdueDays: number; countermeasure: string; source: string;
  checkpointId: number | null; checkpointCode: string | null;
};
export type PlanLog = {
  id: number; at: string; displayAt: string; phaseId: number; phaseName: string; changes: { field: string; label: string; before: string; after: string }[];
  durationDeltaDays: number | null; reason: string; source: string; actorName: string;
};
export type Seal4 = { kind: "pass" | "stop" | "pend"; text: string; checkpointId: number; code: string } | null;
export type WorkItem = {
  id: number; name: string; phaseId: number; phaseName: string; floorId: number | null; roomId: number | null; floorName: string; roomName: string;
  description: string; acceptanceCriteria: string; cost: string | null; plannedFinish: string | null; actualFinish: string | null; ownerName: string;
  qcUserId: number | null; qcUserName: string | null; drawingVersionId: number | null; weight: number; progress: number; status: string;
  isDisabled: boolean; source: string; baselineStatus: string; checkpointSeal: Seal4; attachmentCount: number; recordCount: number;
};

export const f1 = (v: number | null | undefined) => (v === null || v === undefined ? "—" : (Math.round(v * 10) / 10).toFixed(1));
export const md = (s: string | null | undefined) => (s ? s.slice(5) : "—");
export const phaseVar = (c: string | undefined) => `var(${c || "--accent"})`;
export const SOURCE_LABEL: Record<string, string> = { manual: "手工登记", excel_import: "Excel 导入", prototype_import: "原型导入", check: "核对不一致" };

export function addDays(s: string, n: number) {
  const d = new Date(s + "T00:00:00");
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
export function daysBetween(a: string, b: string) {
  return Math.round((new Date(b + "T00:00:00").getTime() - new Date(a + "T00:00:00").getTime()) / 86400000);
}

export function lvCls(v: number | null) {
  if (v === null) return "lv-none";
  if (v <= 0) return "lv0";
  if (v < 40) return "lv1";
  if (v < 70) return "lv2";
  if (v < 90) return "lv3";
  if (v < 99.95) return "lv4";
  return "lv5";
}

export function MatrixLegend({ noneText = "无事项" }: { noneText?: string }) {
  const items: [string, string][] = [["lv0", "0% 未开始"], ["lv1", "1–39%"], ["lv2", "40–69%"], ["lv3", "70–89%"], ["lv4", "90–99%"], ["lv5", "100% 完成"], ["lv-none", noneText]];
  return <div className="legend">{items.map(([c, t]) => <span key={c}><i className={c} />{t}</span>)}</div>;
}

/** 完成度矩阵：行名打开详情，单元格进入工段详情并带楼层 / 房间筛选（AC-F10-09）。 */
export function Matrix({ phases, rows, label, labelW = 110, rowH = 40, onRow, cellTo, groupBy }: {
  phases: PhaseBrief[]; rows: MatrixRow[]; label: string; labelW?: number; rowH?: number;
  onRow?: (r: MatrixRow) => void; cellTo: (r: MatrixRow, p: PhaseBrief) => string; groupBy?: boolean;
}) {
  const nav = useNavigate();
  const W = 900, T = 30, CW = (W - labelW) / Math.max(phases.length, 1), H = T + rowH * rows.length + 4;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
      {phases.map((p, j) => <text key={p.id} x={labelW + CW * j + CW / 2} y={20} textAnchor="middle" fontSize="13" fontWeight="600" style={{ fill: "var(--fg-2)" }}>{p.name}</text>)}
      {rows.map((r, i) => {
        const y = T + i * rowH;
        const group = groupBy && (i === 0 || rows[i - 1].floorId !== r.floorId) ? r.floorName : "";
        return (
          <g key={String(r.id)}>
            {group && <text x={8} y={y + rowH / 2 + 4} fontSize="12" style={{ fill: "var(--muted)" }}>{group}</text>}
            {onRow ? (
              <a href="#" onClick={(e) => { e.preventDefault(); onRow(r); }} aria-label={`查看${r.name}详情`}>
                <text className="rl" x={labelW - 10} y={y + rowH / 2 + 5} textAnchor="end" fontSize="14" fontWeight="600" style={{ fill: "var(--fg)" }}>{r.name}</text>
              </a>
            ) : <text x={labelW - 10} y={y + rowH / 2 + 5} textAnchor="end" fontSize="14" fontWeight="600" style={{ fill: "var(--fg)" }}>{r.name}</text>}
            {r.cells.map((v, j) => {
              const c = lvCls(v), dark = c === "lv4" || c === "lv5";
              const inner = (
                <>
                  <rect className={c} x={labelW + CW * j + 2} y={y + 2} width={CW - 4} height={rowH - 4} rx="6" />
                  <text x={labelW + CW * j + CW / 2} y={y + rowH / 2 + 5} textAnchor="middle" fontSize="13" style={{ fill: dark ? "var(--accent-on)" : "var(--fg-2)" }}>{v === null ? "—" : `${f1(v)}%`}</text>
                </>
              );
              if (v === null) return <g key={j}>{inner}</g>;
              const to = cellTo(r, phases[j]);
              return <a key={j} href={to} onClick={(e) => { e.preventDefault(); nav(to); }} aria-label={`${r.name} ${phases[j].name} ${f1(v)}%`}>{inner}</a>;
            })}
          </g>
        );
      })}
    </svg>
  );
}

export function IssueSeal({ status }: { status: string }) {
  if (status === "已闭环") return <Seal kind="pass">已闭环</Seal>;
  if (status === "处理中") return <Seal kind="pend">处理中</Seal>;
  return <Seal kind="stop">{status === "已作废" ? "已作废" : "未闭环"}</Seal>;
}

export function LevelTag({ level }: { level: string }) {
  return <span className={`tag ${level === "严重" ? "bad" : level === "重要" ? "warn" : ""}`}>{level}</span>;
}

export function Delta({ v }: { v: number | null }) {
  if (v === null || v === undefined) return <span className="muted">—</span>;
  if (v > 0) return <b className="down">+{v} 天</b>;
  if (v < 0) return <b className="up">{v} 天</b>;
  return <>0 天</>;
}

/** 计划变更留档表（只追加，不可编辑删除）。 */
export function PlanLogTable({ logs, withPhase, empty }: { logs: PlanLog[]; withPhase?: boolean; empty: ReactNode }) {
  return (
    <div className="scroll-x">
      <table style={{ minWidth: withPhase ? 820 : 760 }}>
        <thead><tr><th>记录时间</th>{withPhase && <th>工段</th>}<th>变更项</th><th>变更前 → 变更后</th><th className="num">工期影响</th><th>变更原因备注</th></tr></thead>
        <tbody>
          {logs.length ? logs.map((r) => (
            <tr key={r.id}>
              <td className="nowrap muted">{r.displayAt}{r.source === "prototype_import" && <div><span className="tag">原型导入</span></div>}</td>
              {withPhase && <td className="nowrap"><b>{r.phaseName}</b></td>}
              <td><div className="logcol">{r.changes.map((c, i) => <span key={i} className="nowrap">{c.label}</span>)}</div></td>
              <td style={{ minWidth: 260 }}><div className="logcol">{r.changes.map((c, i) => <span key={i}><span className="from">{c.before || "（空）"}</span> → <b>{c.after || "（空）"}</b></span>)}</div></td>
              <td className="num nowrap"><Delta v={r.durationDeltaDays} /></td>
              <td className="muted" style={{ minWidth: 180 }}>{r.reason || "—"}</td>
            </tr>
          )) : <tr><td colSpan={withPhase ? 6 : 5} className="muted" style={{ textAlign: "center", padding: "var(--space-6)" }}>{empty}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export function Kpi({ label, value, unit, children, small }: { label: string; value: ReactNode; unit?: string; children?: ReactNode; small?: boolean }) {
  return (
    <div className="kpi">
      <div className="lb">{label}</div>
      <div className={`vl${small ? " sm" : ""}`}>{value}{unit && <small>{unit}</small>}</div>
      {children && <div className="sb">{children}</div>}
    </div>
  );
}

export function CellBar({ v, color }: { v: number; color?: string }) {
  return <div className="cellbar"><div className="pbar"><i style={{ width: `${Math.min(100, Math.max(0, v))}%`, ...(color ? { background: color } : {}) }} /></div><span>{f1(v)}%</span></div>;
}
