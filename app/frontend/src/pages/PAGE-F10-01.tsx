// PAGE-F10-01 · 项目总览：KPI、证据链四项指标、甘特、楼层矩阵、房间短板与问题、出勤日历、问题统计、遗留清单、计划变更台账、工段速览
// AC-F10-01 ~ AC-F10-08、AC-F11-03、AC-F11-04、AC-F08-04、REQ-F14-02；DEC-301 ~ DEC-303
import { useState, type KeyboardEvent } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Shell } from "../layout/Shell";
import { useProject } from "../session";
import { ErrorState, Icon, Loading, useToast } from "../ui";
import { CellBar, f1, IssueSeal, Kpi, LevelTag, Matrix, MatrixLegend, md, PlanLogTable, type IssueBrief, type MatrixRow, type PhaseBrief, type PlanLog } from "./plan-common";
import "../styles/pages/PAGE-F10-01.css";

type Metric = { key: string; label: string; numerator: number; denominator: number; value: number | null; target: number };
type PhaseCard = PhaseBrief & {
  teamLead: string; scopeNote: string; weight: number; progress: number; planned: number; status: string; itemCount: number; doneCount: number;
  manDays: number; peak: number; workDays: number; issues: number; closed: number; mid: number; open: number;
};
type RoomStat = { id: number; floorId: number; floorName: string; name: string; itemCount: number; progress: number; issues: number; closed: number; legacy: number };
type OverviewData = {
  today: string; project: { name: string; status: string; owners: string[]; pms: string[] };
  kpi: {
    overall: number; planned: number; gap: number; periodStart: string; periodEnd: string; duration: number; used: number; timeProgress: number;
    todayAttendance: number | null; runningPhases: number; manDays: number; issues: number; overdueOpen: number; closed: number; closeRate: number | null;
    legacy: number; mid: number; open: number;
  };
  evidence: Metric[]; phases: PhaseCard[]; floorMatrix: MatrixRow[]; rooms: RoomStat[]; legacy: IssueBrief[]; planLogs: PlanLog[];
};
type Month = { month: string; periodStart: string; periodEnd: string; today: string; days: Record<string, number>; total: number; workDays: number; peak: number; peakDate: string | null; unregistered: number };

const EVI: Record<string, { unit: string; num: string; to: string }> = {
  coverBefore: { unit: "条不一致记录", num: "覆盖前发现", to: "issues" },
  concealedCompliance: { unit: "个已放行或已覆盖的隐蔽检查点", num: "覆盖前同时具备签认版核对、照片与放行", to: "checkpoints" },
  latestSigned: { unit: "条核对记录", num: "使用当时最新签认版", to: "checkpoints" },
  signBeforeBuild: { unit: "张已生效变更单", num: "非后补变更", to: "changes" },
};

function Evidence({ pid, phases }: { pid: string; phases: PhaseBrief[] }) {
  const [scope, setScope] = useState<number | null>(null);
  const q = useQuery({
    queryKey: ["overview", pid, scope], placeholderData: keepPreviousData,
    queryFn: () => api<OverviewData>(`/projects/${pid}/overview${scope ? `?phaseId=${scope}` : ""}`),
  });
  const scopes: [number | null, string][] = [[null, "全项目"], ...phases.map((p) => [p.id, p.name] as [number, string])];
  return (
    <section className="card" aria-labelledby="evi-t">
      <div className="card-hd">
        <h2 id="evi-t">证据链四项指标</h2>
        <span className="desc">按规矩走的程度 · 目标线来自本期成功度量</span>
        <span className="spacer" />
        <div className="chiprow" role="group" aria-label="按工段筛选">
          {scopes.map(([id, nm]) => <button key={String(id)} type="button" className={`chip${scope === id ? " on" : ""}`} aria-pressed={scope === id} onClick={() => setScope(id)}>{nm}</button>)}
        </div>
      </div>
      <div className="card-bd">
        {q.error ? <ErrorState error={q.error} retry={() => q.refetch()} /> : (
          <div className="evi" aria-busy={q.isFetching}>
            {(q.data?.evidence || []).map((m) => {
              const def = EVI[m.key];
              const v = m.value;
              const ok = v !== null && v >= m.target;
              return (
                <Link key={m.key} className="metric card link" to={`/p/${pid}/${def.to}`}>
                  <span className="lb">{m.label}</span>
                  {v === null ? (
                    <>
                      <span className="vl na">暂无数据</span>
                      <span className="frac">所选范围内没有{def.unit.replace(/^[条个张]/, "")}</span>
                      <div className="meter" aria-hidden="true"><b style={{ left: `${m.target}%` }} /><em className={m.target === 100 ? "end" : ""} style={{ left: `${m.target}%` }}>目标 {m.target}%</em></div>
                      <span className="tag">分母为 0</span>
                    </>
                  ) : (
                    <>
                      <span className="vl">{f1(v)}<small>%</small></span>
                      <span className="frac">{def.num} {m.numerator} / {m.denominator} {def.unit}</span>
                      <div className="meter" role="img" aria-label={`${m.label} ${f1(v)}%，目标 ${m.target}%`}>
                        <i className={ok ? "ok" : "low"} style={{ width: `${v}%` }} /><b style={{ left: `${m.target}%` }} />
                        <em className={m.target === 100 ? "end" : ""} style={{ left: `${m.target}%` }}>目标 {m.target}%</em>
                      </div>
                      <span className={`tag ${ok ? "ok" : "warn"}`}>{ok ? "达到目标" : `低于目标 ${f1(m.target - v)} 个百分点`}</span>
                    </>
                  )}
                </Link>
              );
            })}
          </div>
        )}
        <p className="muted" style={{ fontSize: "var(--text-xs)", marginTop: "var(--space-3)" }}>覆盖前发现比例的 90% 目标线针对水电阶段；分母为 0 的指标显示「暂无数据」。点指标卡可查看对应记录。</p>
      </div>
    </section>
  );
}

function Gantt({ pid, phases, today }: { pid: string; phases: PhaseCard[]; today: string }) {
  const nav = useNavigate();
  if (!phases.length) return <p className="muted">暂无工段</p>;
  const W = 1000, L = 92, R = 960, T = 34, RH = 40, H = T + RH * phases.length + 24;
  const start = phases.reduce((a, p) => (p.plannedStart < a ? p.plannedStart : a), phases[0].plannedStart);
  const end = phases.reduce((a, p) => (p.plannedEnd > a ? p.plannedEnd : a), phases[0].plannedEnd);
  const s0 = new Date(start.slice(0, 7) + "-01T00:00:00");
  const e0 = new Date(end.slice(0, 7) + "-01T00:00:00");
  const months = (e0.getFullYear() - s0.getFullYear()) * 12 + e0.getMonth() - s0.getMonth() + 1;
  const s1 = new Date(s0.getFullYear(), s0.getMonth() + months, 1);
  const x = (d: string) => L + (new Date(d + "T00:00:00").getTime() - s0.getTime()) / (s1.getTime() - s0.getTime()) * (R - L);
  const ticks = Array.from({ length: months + 1 }, (_, m) => new Date(s0.getFullYear(), s0.getMonth() + m, 1));
  const tx = x(today);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="各工段计划与实际进度时间轴" className="gantt">
      {ticks.map((t, m) => {
        const ds = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-01`, xx = x(ds);
        return (
          <g key={m}>
            <line x1={xx} y1={T - 8} x2={xx} y2={H - 20} style={{ stroke: "var(--border-soft)" }} />
            {m < months && <text x={xx + 4} y={T - 14} fontSize="12" style={{ fill: "var(--muted)" }}>{(t.getMonth() === 0 || m === 0 ? `${t.getFullYear()}年` : "") + (t.getMonth() + 1)}月</text>}
          </g>
        );
      })}
      {phases.map((p, i) => {
        const y = T + i * RH, x1 = x(p.plannedStart), x2 = x(addOne(p.plannedEnd)), w = Math.max(x2 - x1, 2);
        const nearEnd = x2 > 830, to = `/p/${pid}/phase/${p.id}`;
        return (
          <g key={p.id}>
            <a href={to} onClick={(e) => { e.preventDefault(); nav(to); }}><text x={L - 10} y={y + 22} textAnchor="end" fontSize="14" fontWeight="600" style={{ fill: "var(--fg)" }}>{p.name}</text></a>
            <rect x={x1} y={y + 8} width={w} height="20" rx="4" style={{ fill: `color-mix(in oklab,var(${p.colorVar}) 20%,var(--surface))` }} />
            {p.progress > 0 && <rect x={x1} y={y + 8} width={w * p.progress / 100} height="20" rx="4" style={{ fill: `var(${p.colorVar})` }} />}
            <text x={nearEnd ? x1 - 6 : x2 + 6} y={y + 22} fontSize="12" textAnchor={nearEnd ? "end" : "start"} style={{ fill: "var(--fg-2)" }}>{f1(p.progress)}%（计划 {f1(p.planned)}%）</text>
          </g>
        );
      })}
      {tx >= L && tx <= R && <>
        <line x1={tx} y1={T - 4} x2={tx} y2={H - 20} strokeWidth="1.5" strokeDasharray="4 3" style={{ stroke: "var(--danger)" }} />
        <text x={tx + 4} y={H - 6} fontSize="12" style={{ fill: "var(--danger)" }}>今天 {md(today)}</text>
      </>}
    </svg>
  );
}
const addOne = (d: string) => { const t = new Date(d + "T00:00:00"); t.setDate(t.getDate() + 1); return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`; };

function Calendar({ pid, today, start, end }: { pid: string; today: string; start: string; end: string }) {
  const toast = useToast();
  const [month, setMonth] = useState(today.slice(0, 7));
  const q = useQuery({ queryKey: ["attendance-month", pid, month], queryFn: () => api<Month>(`/projects/${pid}/attendance?month=${month}`), placeholderData: keepPreviousData });
  const shift = (n: number) => {
    let y = +month.slice(0, 4), m = +month.slice(5, 7) + n;
    if (m < 1) { m = 12; y--; }
    if (m > 12) { m = 1; y++; }
    const k = `${y}-${String(m).padStart(2, "0")}`;
    if (k < start.slice(0, 7) || k > end.slice(0, 7)) { toast(`项目周期为 ${start} ~ ${end}`); return; }
    setMonth(k);
  };
  const y = +month.slice(0, 4), m = +month.slice(5, 7);
  const first = new Date(y, m - 1, 1), nd = new Date(y, m, 0).getDate(), off = (first.getDay() + 6) % 7;
  const cells: (string | null)[] = [...Array(off).fill(null), ...Array.from({ length: nd }, (_, i) => `${month}-${String(i + 1).padStart(2, "0")}`)];
  while (cells.length % 7) cells.push(null);
  const days = q.data?.days || {};
  const rows = Array.from({ length: cells.length / 7 }, (_, r) => cells.slice(r * 7, r * 7 + 7));
  return (
    <section className="card" aria-labelledby="cal-t">
      <div className="card-hd"><h2 id="cal-t">每日出勤日历</h2><span className="desc">每格为当日各工段出勤之和 · 只显示人工登记数据</span></div>
      <div className="calbar">
        <button className="btn sm" type="button" onClick={() => shift(-1)} aria-label="上一月"><Icon name="back" />上月</button>
        <span className="month" aria-live="polite">{y} 年 {m} 月</span>
        <button className="btn sm" type="button" onClick={() => shift(1)} aria-label="下一月">下月<span style={{ transform: "rotate(180deg)", display: "inline-flex" }}><Icon name="back" /></span></button>
        <span className="spacer" />
        {q.data && <span className="sumrow">
          <span className="tag brand">合计 {q.data.total} 人·日</span><span className="tag">施工 {q.data.workDays} 天</span>
          <span className="tag warn">峰值 {q.data.peak} 人{q.data.peakDate ? ` · ${md(q.data.peakDate)}` : ""}</span>
          {q.data.unregistered > 0 && <span className="tag">未登记 {q.data.unregistered} 天</span>}
        </span>}
      </div>
      <div className="scroll-x" style={{ padding: "0 var(--space-4)" }}>
        <table className="cal">
          <thead><tr>{["周一", "周二", "周三", "周四", "周五", "周六", "周日"].map((w) => <th key={w}>{w}</th>)}</tr></thead>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri}>
                {r.map((ds, ci) => {
                  if (!ds) return <td key={ci} className="ce" />;
                  const v = days[ds];
                  let cls = "cf", txt = "";
                  if (ds >= start && ds <= today && ds <= end) {
                    if (v === undefined) { cls = "cu"; txt = "未登记"; }
                    else { cls = v === 0 ? "c0" : v <= 4 ? "c1" : v <= 8 ? "c2" : v <= 12 ? "c3" : "c4"; txt = `${v} 人`; }
                  }
                  return <td key={ci} className={cls + (ds === today ? " today" : "")} title={ds}><span className="cd">{+ds.slice(8)} 日</span><span className="cn">{txt}</span></td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="legend"><span><i className="c0" />0 人</span><span><i className="c1" />1–4 人</span><span><i className="c2" />5–8 人</span><span><i className="c3" />9–12 人</span><span><i className="c4" />13 人及以上</span><span><i className="cu" />未登记（按 0 计，不推算）</span></div>
    </section>
  );
}

function IssueBars({ pid, phases }: { pid: string; phases: PhaseCard[] }) {
  const nav = useNavigate();
  const W = 900, H = 210, L = 40, R = 880, T = 20, B = H - 36;
  let max = Math.max(1, ...phases.map((p) => p.issues));
  max = Math.max(4, Math.ceil(max / 2) * 2);
  const gw = (R - L) / Math.max(phases.length, 1), bw = 56;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="各阶段问题发现与闭环">
      {[0, 1, 2, 3, 4].map((g) => { const yy = B - (B - T) * g / 4; return <g key={g}><line x1={L} y1={yy} x2={R} y2={yy} style={{ stroke: "var(--border-soft)" }} /><text x={L - 8} y={yy + 4} textAnchor="end" fontSize="12" style={{ fill: "var(--muted)" }}>{max * g / 4}</text></g>; })}
      {phases.map((p, i) => {
        const cx = L + gw * i + gw / 2, x0 = cx - bw / 2;
        let y = B;
        const segs = ([[p.closed, "var(--success)"], [p.mid, "var(--warn)"], [p.open, "var(--danger)"]] as [number, string][]).map(([n, c], k) => {
          const hh = (B - T) * n / max;
          if (!hh) return null;
          y -= hh;
          return <rect key={k} x={x0} y={y} width={bw} height={hh} style={{ fill: c }} />;
        });
        const to = `/p/${pid}/phase/${p.id}#issues`;
        return (
          <a key={p.id} href={to} onClick={(e) => { e.preventDefault(); nav(to); }} aria-label={`${p.name} 问题 ${p.issues} 项`}>
            {segs}
            {!p.issues && <rect x={x0} y={B - 2} width={bw} height="2" style={{ fill: "var(--border)" }} />}
            <text x={cx} y={y - 6} textAnchor="middle" fontSize="13" fontWeight="700" style={{ fill: "var(--fg)" }}>{p.issues}</text>
            <text x={cx} y={B + 20} textAnchor="middle" fontSize="13" style={{ fill: "var(--fg-2)" }}>{p.name}</text>
          </a>
        );
      })}
    </svg>
  );
}

export default function Overview() {
  const { pid = "" } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { project, can } = useProject(pid);
  const q = useQuery({ queryKey: ["overview", pid, null], queryFn: () => api<OverviewData>(`/projects/${pid}/overview`) });
  if ((q.error as ApiError | null)?.status === 403) return <Navigate to="/forbidden" replace />;
  const o = q.data;
  const sub = o ? <>{o.project.name}　｜　{o.project.owners.length ? `业主 ${o.project.owners.join("、")}` : "业主未加入"} · {o.project.pms.length ? `项目经理 ${o.project.pms.join("、")}` : "项目经理未指定"}　｜　<span className="tag brand">{o.project.status}</span></> : project?.name;
  const actions = can("issue.create") && <Link className="btn primary" to={`/p/${pid}/issues?new=1`}><Icon name="plus" />登记问题</Link>;
  const exportCsv = () => {
    const rows = (o?.planLogs || []).reduce((a, l) => a + l.changes.length, 0);
    const a = document.createElement("a");
    a.href = `/api/projects/${pid}/plan-logs/export.csv`;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast(`已导出计划变更留档 CSV（${rows} 条）`);
  };
  const go = (to: string) => () => nav(to);
  const key = (fn: () => void) => (e: KeyboardEvent) => { if (e.key === "Enter") fn(); };

  return (
    <Shell title="项目总览" sub={sub} actions={actions}>
      <div className="plan-pg pg-f1001">
        {q.isLoading && <><Loading rows={3} /><Loading rows={5} /></>}
        {q.error && <div className="card"><ErrorState error={q.error} retry={() => q.refetch()} /></div>}
        {o && <>
          <section className="grid-kpi mt-4" aria-label="关键指标">
            <Kpi label="总体完成度" value={f1(o.kpi.overall)} unit="%"><span className={`tag ${o.kpi.gap >= 0 ? "ok" : "bad"}`}>计划基准 {f1(o.kpi.planned)}% · {o.kpi.gap >= 0 ? "领先" : "滞后"} {f1(Math.abs(o.kpi.gap))} 个百分点</span></Kpi>
            <Kpi label="工期进度" value={f1(o.kpi.timeProgress)} unit="%"><span className="tag">{o.kpi.periodStart} ~ {o.kpi.periodEnd}</span><span className="tag">已用 {o.kpi.used} 天 / 总 {o.kpi.duration} 天</span></Kpi>
            <Kpi label="今日出勤" value={o.kpi.todayAttendance === null ? "未登记" : o.kpi.todayAttendance} unit={o.kpi.todayAttendance === null ? "" : "人"}><span className="tag brand">在施 {o.kpi.runningPhases} 个工段</span><span className="tag">累计 {o.kpi.manDays} 人·日</span></Kpi>
            <Kpi label="发现问题" value={o.kpi.issues} unit="项"><span className={`tag ${o.kpi.overdueOpen ? "bad" : "ok"}`}>超期未闭环 {o.kpi.overdueOpen} 项</span></Kpi>
            <Kpi label="已闭环" value={o.kpi.closed} unit="项"><span className={`tag ${(o.kpi.closeRate ?? 0) >= 80 ? "ok" : "warn"}`}>闭环率 {o.kpi.closeRate === null ? "—" : `${f1(o.kpi.closeRate)}%`}</span></Kpi>
            <Kpi label="问题遗留" value={o.kpi.legacy} unit="项"><span className="tag warn">处理中 {o.kpi.mid}</span><span className="tag bad">未闭环 {o.kpi.open}</span></Kpi>
          </section>

          <Evidence pid={pid} phases={o.phases} />

          <section className="card" aria-labelledby="gantt-t">
            <div className="card-hd"><h2 id="gantt-t">项目进度总览 · {o.phases.length === 6 ? "六阶段" : `${o.phases.length} 个阶段`}时间轴</h2><span className="desc">浅色为计划区间，深色为实际完成度，红色虚线为今天</span></div>
            <div className="card-bd"><div className="scroll-x"><div className="chartbox" style={{ minWidth: 720 }}><Gantt pid={pid} phases={o.phases} today={o.today} /></div></div></div>
          </section>

          <section className="card" aria-labelledby="fm-t">
            <div className="card-hd"><h2 id="fm-t">楼层 × 阶段 完成度矩阵</h2><span className="desc">点楼层名看该楼层全部事项 · 点单元格进入该工段并筛选该楼层</span><span className="spacer" /><Link className="btn sm" to={`/p/${pid}/floors`}>楼层 / 房间视图</Link></div>
            <div className="card-bd" style={{ paddingBottom: 0 }}><div className="scroll-x"><div className="chartbox mx" style={{ minWidth: 640 }}>
              <Matrix phases={o.phases} rows={o.floorMatrix} label="楼层与阶段完成度矩阵" onRow={(r) => nav(`/p/${pid}/floors?floor=${r.id}`)}
                cellTo={(r, p) => `/p/${pid}/phase/${p.id}?floor=${r.id}`} />
            </div></div></div>
            <MatrixLegend />
          </section>

          <div className="grid-2">
            <section className="card" aria-labelledby="slow-t">
              <div className="card-hd"><h2 id="slow-t">房间完成度 · 短板 TOP 8</h2><span className="desc">{o.rooms.length} 个房间中进展最慢的 8 个</span></div>
              <div className="card-bd tight"><div className="scroll-x"><table><thead><tr><th>楼层 / 房间</th><th className="num">事项</th><th style={{ width: "40%" }}>加权完成度</th><th className="num">问题</th></tr></thead>
                <tbody>{[...o.rooms].filter((r) => r.itemCount > 0).sort((a, b) => a.progress - b.progress || b.issues - a.issues || b.itemCount - a.itemCount).slice(0, 8).map((r) => {
                  const fn = go(`/p/${pid}/floors?room=${r.id}`);
                  return <tr key={r.id} className="row-link" tabIndex={0} onClick={fn} onKeyDown={key(fn)}><td className="nowrap"><span className="fl-tag">{r.floorName}</span> <b>{r.name}</b></td><td className="num">{r.itemCount}</td><td><CellBar v={r.progress} /></td><td className={`num${r.legacy ? " down" : ""}`}>{r.issues}</td></tr>;
                })}</tbody></table></div></div>
            </section>
            <section className="card" aria-labelledby="rmiss-t">
              <div className="card-hd"><h2 id="rmiss-t">房间问题聚焦 TOP 6</h2><span className="desc">按房间统计发现与闭环</span></div>
              <div className="card-bd tight"><div className="scroll-x"><table><thead><tr><th>楼层 / 房间</th><th className="num">问题</th><th className="num">闭环</th><th className="num">遗留</th><th style={{ width: "30%" }}>闭环率</th></tr></thead>
                <tbody>{(() => {
                  const top = o.rooms.filter((r) => r.issues > 0).sort((a, b) => b.issues - a.issues || b.legacy - a.legacy).slice(0, 6);
                  return <>
                    {top.map((r) => { const fn = go(`/p/${pid}/floors?room=${r.id}`); return <tr key={r.id} className="row-link" tabIndex={0} onClick={fn} onKeyDown={key(fn)}><td className="nowrap"><span className="fl-tag">{r.floorName}</span> <b>{r.name}</b></td><td className="num">{r.issues}</td><td className="num">{r.closed}</td><td className={`num${r.legacy ? " down" : ""}`}>{r.legacy}</td><td><CellBar v={r.closed / r.issues * 100} color="var(--success)" /></td></tr>; })}
                    {top.length < 6 && <tr><td colSpan={5} className="muted" style={{ fontSize: "var(--text-xs)" }}>{top.length ? "其余房间暂无问题记录" : "各房间暂无问题记录"}</td></tr>}
                  </>;
                })()}</tbody></table></div></div>
            </section>
          </div>

          <Calendar pid={pid} today={o.today} start={o.kpi.periodStart} end={o.kpi.periodEnd} />

          <section className="card" aria-labelledby="ib-t">
            <div className="card-hd"><h2 id="ib-t">问题发现与闭环 · 按阶段</h2><span className="desc">不含已作废问题 · 点柱形进入该工段的问题卡</span></div>
            <div className="card-bd"><div className="scroll-x"><div className="chartbox" style={{ minWidth: 560 }}><IssueBars pid={pid} phases={o.phases} /></div></div></div>
            <div className="legend"><span><i style={{ background: "var(--success)" }} />已闭环</span><span><i style={{ background: "var(--warn)" }} />处理中</span><span><i style={{ background: "var(--danger)" }} />未闭环</span></div>
          </section>

          <section className="card" aria-labelledby="leg-t">
            <div className="card-hd"><h2 id="leg-t">问题遗留清单 · 需重点跟进</h2><span className="desc">未闭环与处理中的问题，按超期天数从大到小</span><span className="spacer" /><Link className="btn sm" to={`/p/${pid}/issues`}>问题台账</Link></div>
            <div className="card-bd tight"><div className="scroll-x"><table className="legacy-tb" style={{ minWidth: 860 }}>
              <thead><tr><th>编号</th><th>阶段</th><th>楼层 / 房间</th><th>问题</th><th>等级</th><th>状态</th><th>负责人</th><th>要求闭环</th><th className="num">超期</th></tr></thead>
              <tbody>{o.legacy.length ? o.legacy.map((i) => {
                const fn = go(`/p/${pid}/issues?id=${i.id}`);
                return (
                  <tr key={i.id} className="row-link" tabIndex={0} onClick={fn} onKeyDown={key(fn)}>
                    <td className="muted">{i.code}</td>
                    <td className="nowrap"><span className="phase-dot" style={{ background: `var(${i.phaseColor})` }} /> {i.phaseName}</td>
                    <td className="nowrap"><span className="fl-tag">{i.floorName}</span> {i.roomName}</td>
                    <td style={{ minWidth: 220 }}>{i.description}</td>
                    <td><LevelTag level={i.level} /></td><td><IssueSeal status={i.status} /></td>
                    <td className="nowrap">{i.ownerName}</td><td className="nowrap">{i.dueDate || "—"}</td>
                    <td className="num nowrap">{i.overdueDays > 0 ? <b className="down">{i.overdueDays} 天</b> : <span className="muted">—</span>}</td>
                  </tr>
                );
              }) : <tr><td colSpan={9} className="muted" style={{ textAlign: "center", padding: "var(--space-6)" }}>当前无遗留问题</td></tr>}</tbody>
            </table></div></div>
          </section>

          <section className="card" aria-labelledby="log-t">
            <div className="card-hd"><h2 id="log-t">计划变更台账 · 全阶段</h2><span className="desc">工段起止、班组、权重、范围的每次调整自动留档，只追加不覆盖</span><span className="spacer" />
              <span className="tag warn">累计 {o.planLogs.length} 条</span>
              <button className="btn sm" type="button" onClick={exportCsv}><Icon name="download" />导出 CSV</button></div>
            <div className="card-bd tight"><PlanLogTable logs={o.planLogs} withPhase empty="暂无计划变更留档" /></div>
          </section>

          <section className="card" aria-labelledby="ph-t">
            <div className="card-hd"><h2 id="ph-t">各工段速览</h2><span className="desc">工期 / 出勤 / 事项 / 问题 · 点卡片进入工段详情</span></div>
            <div className="card-bd"><div className="grid-3">
              {o.phases.map((p) => (
                <Link key={p.id} className="phcard" to={`/p/${pid}/phase/${p.id}`}>
                  <div className="h"><span className="phase-dot" style={{ background: `var(${p.colorVar})` }} /><b>{p.name}</b><span className={`tag ${p.status === "已完成" ? "ok" : p.status === "进行中" ? "brand" : ""}`}>{p.status}</span></div>
                  <CellBar v={p.progress} color={`var(${p.colorVar})`} />
                  <div className="m">
                    <span>工期 {md(p.plannedStart)} ~ {md(p.plannedEnd)}</span><span>计划基准 {f1(p.planned)}%</span>
                    <span>累计出勤 {p.manDays} 人·日</span><span>峰值 {p.peak} 人 / 施工 {p.workDays} 天</span>
                    <span>工作项 {p.itemCount} 项</span><span>问题 {p.issues} · 闭环 {p.closed}</span>
                  </div>
                </Link>
              ))}
            </div></div>
          </section>
        </>}
      </div>
    </Shell>
  );
}
