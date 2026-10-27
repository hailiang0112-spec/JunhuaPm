// PAGE-F10-03 · 工段详情：工段切换、KPI、计划变更留档、工作项表、楼层房间分布、出勤图与台账、验收图片、问题卡；
// 编辑工段计划 / 登记出勤 / 批量登记出勤弹窗。AC-F10-10、AC-F03-05/06、AC-F11-01~03、AC-F12-04、AC-F14-01~03；DEC-304~307、DEC-314
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useParams, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, uploadFile } from "../api";
import { Shell } from "../layout/Shell";
import { useProject } from "../session";
import { ErrorState, Field, Icon, Loading, Modal, Seal, useToast } from "../ui";
import { addDays, CellBar, daysBetween, f1, IssueSeal, Kpi, LevelTag, md, PlanLogTable, SOURCE_LABEL, type IssueBrief, type PhaseBrief, type PlanLog, type WorkItem } from "./plan-common";
import "../styles/pages/PAGE-F10-03.css";

type Photo = { id: number; caption: string; status: string; source: string; file: { id: number; url: string; thumbUrl: string | null } | null; uploaderName: string; createdAt: string | null };
type Detail = {
  today: string;
  phase: PhaseBrief & { teamLead: string; scopeNote: string; weight: number; isDisabled: boolean; progress: number; planned: number; status: string; duration: number };
  phases: PhaseBrief[];
  attendanceStats: { total: number; peak: number; workDays: number; unregistered: number; firstDay: string | null; lastDay: string | null; avg: number };
  attendance: { date: string; headcount: number; source: string }[];
  items: WorkItem[]; floors: { id: number; name: string }[]; rooms: { id: number; floorId: number; name: string }[];
  issues: IssueBrief[]; photos: Photo[]; planLogs: PlanLog[];
};
const PST = ["施工中", "待复验", "已验收"];
const WEEK = "日一二三四五六";
const wk = (s: string) => WEEK.charAt(new Date(s + "T00:00:00").getDay());
const prog = (ts: WorkItem[]) => { const w = ts.reduce((a, t) => a + t.weight, 0); return w ? ts.reduce((a, t) => a + t.weight * t.progress, 0) / w : 0; };
const ALL = "all";

function PhotoSeal({ s }: { s: string }) {
  if (s === "已验收") return <Seal kind="pass">已验收</Seal>;
  if (s === "待复验") return <Seal kind="pend">待复验</Seal>;
  return <span className="seal mute">施工中</span>;
}

function AttChart({ d }: { d: Detail }) {
  const p = d.phase, att = new Map(d.attendance.map((a) => [a.date, a.headcount]));
  const n = daysBetween(p.plannedStart, p.plannedEnd) + 1, W = 600, H = 220, L = 32, R = 590, T = 12, B = H - 34;
  let max = 4;
  att.forEach((v) => { if (v > max) max = v; });
  max = Math.ceil(max / 2) * 2;
  const bw = (R - L) / n;
  const cells = [];
  for (let i = 0; i < n; i++) {
    const day = addDays(p.plannedStart, i), x = L + i * bw, v = att.get(day);
    if (day <= d.today) {
      if (v === undefined) cells.push(<rect key={`u${i}`} x={x + bw * 0.15} y={B - 6} width={bw * 0.7} height="6" rx="1" style={{ fill: "var(--surface)", stroke: "var(--muted)", strokeDasharray: "2 1" }}><title>{day} 未登记</title></rect>);
      else if (v > 0) cells.push(<rect key={`v${i}`} x={x + bw * 0.15} y={B - (B - T) * v / max} width={bw * 0.7} height={(B - T) * v / max} rx="1" style={{ fill: `var(${p.colorVar})` }}><title>{day} {v} 人</title></rect>);
    }
    if (i % 7 === 0) cells.push(<text key={`t${i}`} x={x + bw / 2} y={B + 16} textAnchor="middle" fontSize="11" style={{ fill: "var(--muted)" }}>{md(day)}</text>);
    if (day === d.today) cells.push(<line key="today" x1={x + bw / 2} y1={T} x2={x + bw / 2} y2={B} strokeDasharray="3 3" style={{ stroke: "var(--danger)" }} />);
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${p.name}每日出勤人数`}>
      {[0, 1, 2].map((g) => { const y = B - (B - T) * g / 2; return <g key={g}><line x1={L} y1={y} x2={R} y2={y} style={{ stroke: "var(--border-soft)" }} /><text x={L - 6} y={y + 4} textAnchor="end" fontSize="11" style={{ fill: "var(--muted)" }}>{max * g / 2}</text></g>; })}
      {cells}
      {d.today < p.plannedStart && <text x={(L + R) / 2} y={(T + B) / 2} textAnchor="middle" fontSize="13" style={{ fill: "var(--muted)" }}>工段尚未开始，{p.plannedStart} 起可登记出勤</text>}
    </svg>
  );
}

function PlanDialog({ pid, d, onClose }: { pid: string; d: Detail; onClose: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const p = d.phase;
  const [v, setV] = useState({ plannedStart: p.plannedStart, plannedEnd: p.plannedEnd, teamLead: p.teamLead, weight: String(p.weight), scopeNote: p.scopeNote, reason: "" });
  const [err, setErr] = useState<Record<string, string>>({});
  const fields: [keyof typeof v, string][] = [["plannedStart", "计划开始日期"], ["plannedEnd", "计划结束日期"], ["teamLead", "班组负责人"], ["weight", "工段权重"], ["scopeNote", "施工范围"]];
  const cur: Record<string, string> = { plannedStart: p.plannedStart, plannedEnd: p.plannedEnd, teamLead: p.teamLead, weight: String(p.weight), scopeNote: p.scopeNote };
  const changes = fields.filter(([k]) => String(v[k]).trim() !== cur[k]);
  const dd = v.plannedStart && v.plannedEnd ? daysBetween(v.plannedStart, v.plannedEnd) - daysBetween(p.plannedStart, p.plannedEnd) : 0;
  const m = useMutation({
    mutationFn: () => api<{ changed: boolean; changeCount: number }>(`/projects/${pid}/phases/${p.id}/plan`, { method: "PATCH", body: { ...v, teamLead: v.teamLead.trim(), scopeNote: v.scopeNote.trim() } }),
    onSuccess: (r) => {
      onClose();
      toast(r.changed ? `工段计划已保存，已追加 1 条留档（${r.changeCount} 个字段变化）` : "计划未变化，未生成留档记录");
      qc.invalidateQueries({ queryKey: ["phase-detail", pid] });
      qc.invalidateQueries({ queryKey: ["overview", pid] });
      qc.invalidateQueries({ queryKey: ["project", pid] });
    },
    onError: (e: ApiError) => { if (e.fields.length) setErr(e.fieldMap()); else toast(e.message); },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (!v.plannedStart) er.plannedStart = "请填写计划开始日期";
    if (!v.plannedEnd) er.plannedEnd = "请填写计划结束日期";
    if (v.plannedStart && v.plannedEnd && v.plannedStart > v.plannedEnd) er.plannedStart = "开始日期不能晚于结束日期";
    if (!/^\d+$/.test(v.weight.trim()) || +v.weight < 1) er.weight = "工段权重为正整数";
    setErr(er);
    if (Object.keys(er).length) return;
    m.mutate();
  };
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  return (
    <Modal title="编辑工段计划" wide onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>取消</button><button type="submit" form="plan-form" className="btn primary" disabled={m.isPending}>{m.isPending ? "保存中…" : "保存计划"}</button></>}>
      <form id="plan-form" className="f1003-dlg" onSubmit={submit} noValidate style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        <div className="form-grid">
          <Field label="计划开始日期" required error={err.plannedStart}><input className="input" type="date" value={v.plannedStart} onChange={set("plannedStart")} /></Field>
          <Field label="计划结束日期" required error={err.plannedEnd}><input className="input" type="date" value={v.plannedEnd} onChange={set("plannedEnd")} /></Field>
          <Field label="班组负责人"><input className="input" value={v.teamLead} onChange={set("teamLead")} /></Field>
          <Field label="工段权重" error={err.weight}><input className="input" type="number" min={1} step={1} value={v.weight} onChange={set("weight")} /></Field>
          <Field label="施工范围" full><textarea className="textarea" rows={2} value={v.scopeNote} onChange={set("scopeNote")} /></Field>
          <Field label="原因备注" full><textarea className="textarea" rows={2} value={v.reason} placeholder="例如：书房 B 门洞待设计变更，相关隔墙暂缓" onChange={set("reason")} /></Field>
        </div>
        <div className="diff" aria-live="polite">
          {changes.length ? <>
            <b>保存后将追加 1 条留档（不可修改）：</b>
            <ul>{changes.map(([k, l]) => <li key={k}>{l}：{cur[k] || "（空）"} → <b>{String(v[k]).trim() || "（空）"}</b></li>)}</ul>
            {dd !== 0 && <div>工期影响：<b className={dd > 0 ? "down" : "up"}>{dd > 0 ? "+" : ""}{dd} 天</b></div>}
          </> : <span className="muted">尚未修改任何字段。字段都未变化时保存不会产生留档记录。</span>}
        </div>
      </form>
    </Modal>
  );
}

function AttDialog({ pid, d, date, onClose }: { pid: string; d: Detail; date?: string; onClose: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const p = d.phase;
  const att = new Map(d.attendance.map((a) => [a.date, a.headcount]));
  const def = date || (d.today >= p.plannedStart && d.today <= p.plannedEnd ? d.today : p.plannedStart);
  const [day, setDay] = useState(def);
  const [n, setN] = useState(att.has(def) ? String(att.get(def)) : "");
  const [err, setErr] = useState<Record<string, string>>({});
  const m = useMutation({
    mutationFn: () => api(`/projects/${pid}/phases/${p.id}/attendance/${day}`, { method: "PUT", body: { headcount: n.trim() } }),
    onSuccess: () => { onClose(); toast(`${md(day)} 出勤 ${n.trim()} 人已保存`); qc.invalidateQueries({ queryKey: ["phase-detail", pid] }); qc.invalidateQueries({ queryKey: ["overview", pid] }); qc.invalidateQueries({ queryKey: ["attendance-month", pid] }); },
    onError: (e: ApiError) => { if (e.fields.length) setErr(e.fieldMap()); else toast(e.message); },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (!day || day < p.plannedStart || day > p.plannedEnd) er.date = `日期须在工段工期 ${p.plannedStart} ~ ${p.plannedEnd} 内`;
    if (!/^\d+$/.test(n.trim()) || +n > 40) er.headcount = "请填写 0–40 的整数";
    setErr(er);
    if (!Object.keys(er).length) m.mutate();
  };
  return (
    <Modal title="登记每日出勤" onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>取消</button><button type="submit" form="att-form" className="btn primary" disabled={m.isPending}>保存</button></>}>
      <form id="att-form" onSubmit={submit} noValidate style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        <Field label="日期" required error={err.date}><input className="input" type="date" value={day} min={p.plannedStart} max={p.plannedEnd} onChange={(e) => { setDay(e.target.value); if (att.has(e.target.value)) setN(String(att.get(e.target.value))); }} /></Field>
        <Field label="出勤人数" required error={err.headcount}><input className="input" type="number" min={0} max={40} step={1} inputMode="numeric" value={n} onChange={(e) => setN(e.target.value)} /></Field>
        <p className="muted" style={{ fontSize: "var(--text-xs)" }}>只能登记本工段工期内（{p.plannedStart} ~ {p.plannedEnd}）的日期，人数 0–40。保存后重新计算累计人工日、日均出勤和峰值。</p>
      </form>
    </Modal>
  );
}

function BatchDialog({ pid, d, onClose }: { pid: string; d: Detail; onClose: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const p = d.phase;
  const inPhase = d.today >= p.plannedStart && d.today <= p.plannedEnd;
  const [s, setS] = useState(inPhase && d.today > p.plannedStart ? (addDays(d.today, -6) < p.plannedStart ? p.plannedStart : addDays(d.today, -6)) : p.plannedStart);
  const [e2, setE] = useState(inPhase ? d.today : p.plannedEnd);
  const [n, setN] = useState("");
  const [mode, setMode] = useState("workdays");
  const [err, setErr] = useState<Record<string, string>>({});
  const att = new Set(d.attendance.map((a) => a.date));
  const days = useMemo(() => {
    const out: string[] = [];
    if (!s || !e2 || s > e2) return out;
    for (let x = s; x <= e2; x = addDays(x, 1)) {
      if (mode === "workdays" && new Date(x + "T00:00:00").getDay() === 0) continue;
      if (mode === "untilToday" && x > d.today) continue;
      out.push(x);
    }
    return out;
  }, [s, e2, mode, d.today]);
  const over = days.filter((x) => att.has(x)).length;
  const m = useMutation({
    mutationFn: () => api<{ written: number; headcount: number }>(`/projects/${pid}/phases/${p.id}/attendance/batch`, { body: { start: s, end: e2, headcount: n.trim(), mode } }),
    onSuccess: (r) => { onClose(); toast(`已写入 ${r.written} 天，每天 ${r.headcount} 人`); qc.invalidateQueries({ queryKey: ["phase-detail", pid] }); qc.invalidateQueries({ queryKey: ["overview", pid] }); qc.invalidateQueries({ queryKey: ["attendance-month", pid] }); },
    onError: (e: ApiError) => { if (e.fields.length) setErr(e.fieldMap()); else toast(e.message); },
  });
  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    const er: Record<string, string> = {};
    if (!s || s < p.plannedStart || s > p.plannedEnd) er.start = "开始日期须在工段工期内";
    if (!e2 || e2 < p.plannedStart || e2 > p.plannedEnd) er.end = "结束日期须在工段工期内";
    if (s && e2 && s > e2) er.start = "开始日期不能晚于结束日期";
    if (!/^\d+$/.test(n.trim()) || +n > 40) er.headcount = "请填写 0–40 的整数";
    if (!er.start && !er.end && !days.length) er.end = "所选范围内没有可写入的日期";
    setErr(er);
    if (!Object.keys(er).length) m.mutate();
  };
  return (
    <Modal title="批量登记出勤" onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>取消</button><button type="submit" form="batch-form" className="btn primary" disabled={m.isPending}>写入</button></>}>
      <form id="batch-form" className="f1003-dlg" onSubmit={submit} noValidate style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        <div className="form-grid">
          <Field label="开始日期" required error={err.start}><input className="input" type="date" value={s} min={p.plannedStart} max={p.plannedEnd} onChange={(e) => setS(e.target.value)} /></Field>
          <Field label="结束日期" required error={err.end}><input className="input" type="date" value={e2} min={p.plannedStart} max={p.plannedEnd} onChange={(e) => setE(e.target.value)} /></Field>
          <Field label="每天出勤人数" required full error={err.headcount}><input className="input" type="number" min={0} max={40} step={1} inputMode="numeric" value={n} onChange={(e) => setN(e.target.value)} /></Field>
          <div className="field full"><label>写入范围</label>
            <div className="radios" role="radiogroup" aria-label="写入范围">
              {[["all", "每天"], ["workdays", "仅工作日（跳过周日）"], ["untilToday", "仅至今日"]].map(([k, l]) => <label key={k}><input type="radio" name="bt-r" value={k} checked={mode === k} onChange={() => setMode(k)} />{l}</label>)}
            </div>
          </div>
        </div>
        <div className="diff" aria-live="polite">
          {days.length ? <>将写入 <b>{days.length}</b> 天（{days[0]} ~ {days[days.length - 1]}）{over ? `，其中 ${over} 天已有登记将被覆盖为新人数` : ""}。未选中的日期保持「未登记」，不推算。</> : <span className="muted">请选择工段工期内的起止日期。</span>}
        </div>
      </form>
    </Modal>
  );
}

export default function PhaseDetail() {
  const { pid = "", phaseId = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const loc = useLocation();
  const toast = useToast();
  const qc = useQueryClient();
  const { project, can } = useProject(pid);
  const q = useQuery({ queryKey: ["phase-detail", pid, phaseId], queryFn: () => api<Detail>(`/projects/${pid}/phases/${phaseId}/detail`) });
  const [page, setPage] = useState(1);
  const [isf, setIsf] = useState("全部");
  const [dlg, setDlg] = useState<null | { kind: "plan" | "batch" } | { kind: "att"; date?: string }>(null);
  const [busy, setBusy] = useState(false);
  const fl = sp.get("floor") || "", rm = sp.get("room") || "";
  const d = q.data;
  const roomObj = d?.rooms.find((r) => String(r.id) === rm);
  const flEff = roomObj ? String(roomObj.floorId) : fl;
  useEffect(() => { setPage(1); }, [fl, rm, phaseId]);
  useEffect(() => {
    if (!d) return;
    const el = loc.hash === "#issues" ? document.getElementById("issues") : (fl || rm) ? document.getElementById("task-t") : null;
    el?.scrollIntoView();
  }, [d, loc.hash]);

  const cycle = useMutation({
    mutationFn: (ph: Photo) => api<Photo>(`/projects/${pid}/acceptance-photos/${ph.id}/status`, { body: {} }),
    onSuccess: (r) => { toast(`「${r.caption}」已切换为${r.status}`); qc.invalidateQueries({ queryKey: ["phase-detail", pid] }); },
    onError: (e: ApiError) => toast(e.message),
  });

  const err = q.error as ApiError | null;
  if (err?.status === 403) return <Navigate to="/forbidden" replace />;
  if (err?.status === 404 && project?.phases.length) return <Navigate to={`/p/${pid}/phase/${project.phases[0].id}`} replace />;

  const setFilter = (f: string, r: string) => { const n = new URLSearchParams(); if (f) n.set("floor", f); if (r) n.set("room", r); setSp(n, { replace: true }); };
  const scrollTasks = () => document.getElementById("task-t")?.scrollIntoView({ behavior: "smooth", block: "start" });
  const upload = async (files: FileList | null) => {
    if (!files?.length || !d) return;
    setBusy(true);
    const ids: number[] = [];
    for (const f of Array.from(files)) {
      try { ids.push((await uploadFile(pid, f)).id); } catch (e) { toast((e as ApiError).message); }
    }
    try {
      if (ids.length) {
        await api(`/projects/${pid}/phases/${d.phase.id}/acceptance-photos`, { body: { fileIds: ids } });
        toast(`已上传 ${ids.length} 张验收图片，状态为「待复验」`);
        qc.invalidateQueries({ queryKey: ["phase-detail", pid] });
      }
    } catch (e) { toast((e as ApiError).message); }
    setBusy(false);
  };

  const p = d?.phase;
  const actions = p && <>
    {can("phase.plan_edit") && <button className="btn" type="button" onClick={() => setDlg({ kind: "plan" })}><Icon name="doc" />编辑工段计划</button>}
    {can("attendance.edit") && <button className="btn" type="button" onClick={() => setDlg({ kind: "batch" })}><Icon name="list" />批量登记出勤</button>}
    {can("attendance.edit") && <button className="btn primary" type="button" onClick={() => setDlg({ kind: "att" })}><Icon name="plus" />登记出勤</button>}
  </>;

  return (
    <Shell title={p ? `${p.name} · 工段详情` : "工段详情"} sub={p ? `${p.teamLead || "班组待定"}　｜　${p.scopeNote || "施工范围待补充"}` : project?.name} actions={actions}>
      <div className="plan-pg pg-f1003">
        {q.isLoading && <><Loading rows={2} /><Loading rows={6} /></>}
        {q.error && err?.status !== 404 && <div className="card"><ErrorState error={q.error} retry={() => q.refetch()} /></div>}
        {d && p && (() => {
          const items = d.items;
          const floorsIn = d.floors.filter((f) => items.some((t) => t.floorId === f.id));
          const hasCommon = items.some((t) => t.floorId === null);
          const roomsIn = flEff && flEff !== ALL ? d.rooms.filter((r) => String(r.floorId) === flEff && items.some((t) => t.roomId === r.id)) : [];
          const list = items.filter((t) => (!flEff || (flEff === ALL ? t.floorId === null : String(t.floorId) === flEff)) && (!rm || String(t.roomId) === rm));
          const pages = Math.max(1, Math.ceil(list.length / 20)), pg = Math.min(page, pages);
          const rows = list.slice((pg - 1) * 20, pg * 20);
          const done = items.filter((t) => t.progress >= 100).length;
          const a = d.attendanceStats;
          const closed = d.issues.filter((i) => i.status === "已闭环").length;
          const g = p.progress - p.planned;
          const endTxt = !a.lastDay ? "未进场" : p.status === "已完成" ? `完工 ${md(a.lastDay)}` : `至 ${md(a.lastDay)} 在施`;
          const drift = d.planLogs.reduce((s, l) => s + (l.durationDeltaDays || 0), 0);
          const att = new Map(d.attendance.map((x) => [x.date, x]));
          const ledger: string[] = [];
          for (let x = d.today < p.plannedEnd ? d.today : p.plannedEnd; x >= p.plannedStart; x = addDays(x, -1)) ledger.push(x);
          const fname = flEff === ALL ? "全楼通用" : d.floors.find((f) => String(f.id) === flEff)?.name;
          const cnt = { 施工中: 0, 待复验: 0, 已验收: 0 } as Record<string, number>;
          d.photos.forEach((x) => { cnt[x.status] = (cnt[x.status] || 0) + 1; });
          const iss = d.issues.filter((i) => isf === "全部" || i.status === isf);
          return <>
            <nav className="wschips" aria-label="工段速览 · 点击切换">
              {d.phases.map((x) => (
                <Link key={x.id} className={`wschip${x.id === p.id ? " on" : ""}`} to={`/p/${pid}/phase/${x.id}`} aria-current={x.id === p.id ? "page" : undefined}>
                  <b><span className="phase-dot" style={{ background: `var(${x.colorVar})` }} />{x.name}</b><span>{md(x.plannedStart).replace("-", "/")} ~ {md(x.plannedEnd).replace("-", "/")}</span>
                </Link>
              ))}
            </nav>

            <section className="grid-kpi mt-4" aria-label="工段指标">
              <Kpi label="工段进度" value={f1(p.progress)} unit="%"><span className={`tag ${g >= 0 ? "ok" : "bad"}`}>计划基准 {f1(p.planned)}% · {g >= 0 ? "领先" : "滞后"} {f1(Math.abs(g))} 个百分点</span></Kpi>
              <Kpi label="计划开始 / 实际开始" value={md(p.plannedStart)} small><span className="tag">实际 {a.firstDay ? md(a.firstDay) : "未进场"}</span></Kpi>
              <Kpi label="计划结束 / 实际结束" value={md(p.plannedEnd)} small><span className="tag">{endTxt}</span></Kpi>
              <Kpi label="工期 / 已施工天数" value={p.duration} unit="天"><span className="tag">实际施工 {a.workDays} 天</span></Kpi>
              <Kpi label="出勤 · 峰值" value={a.peak} unit="人"><span className="tag brand">累计 {a.total} 人·日</span>{a.unregistered > 0 && <span className="tag">未登记 {a.unregistered} 天</span>}</Kpi>
              <Kpi label="工作项 / 问题" value={`${done}/${items.length}`} unit="项"><span className={`tag ${p.status === "已完成" ? "ok" : p.status === "进行中" ? "brand" : ""}`}>{p.status}（自动）</span><span className={`tag ${closed === d.issues.length ? "ok" : "warn"}`}>问题 {d.issues.length} · 闭环 {closed}</span></Kpi>
            </section>

            <section className="card" aria-labelledby="log-t">
              <div className="card-hd"><h2 id="log-t">计划变更留档</h2><span className="desc">起止日期、班组、权重、范围每次变化自动留档，只追加不覆盖</span><span className="spacer" />
                <span className={`tag ${d.planLogs.length ? "warn" : ""}`}>累计 {d.planLogs.length} 次变更</span>
                {drift ? <span className={`tag ${drift > 0 ? "bad" : "ok"}`}>工期较初始{drift > 0 ? "延后" : "提前"} {Math.abs(drift)} 天</span> : <span className="tag">工期与初始一致</span>}
              </div>
              <div className="card-bd tight"><PlanLogTable logs={d.planLogs} empty="暂无计划变更留档。调整起止日期、班组、权重或施工范围后自动生成，只追加不覆盖。" /></div>
            </section>

            <section className="card" aria-labelledby="task-t">
              <div className="card-hd"><h2 id="task-t">工作项 · 完成情况</h2><span className="desc">共 {items.length} 项，已完成 {done} 项</span><span className="spacer" />
                {can("structure.edit") && <Link className="btn sm" to={`/p/${pid}/structure`}><Icon name="plus" />在项目结构中新增</Link>}</div>
              <div className="filters">
                <div className="chiprow" role="group" aria-label="按楼层筛选"><span className="lb">楼层</span>
                  {[{ id: "", name: "全部" }, ...floorsIn.map((f) => ({ id: String(f.id), name: f.name })), ...(hasCommon ? [{ id: ALL, name: "全楼通用" }] : [])].map((f) => (
                    <button key={f.id} type="button" className={`chip${flEff === f.id && !(f.id === "" && rm) ? " on" : ""}`} aria-pressed={flEff === f.id} onClick={() => setFilter(f.id, "")}>{f.name}</button>
                  ))}
                </div>
                {roomsIn.length > 0 && <div className="chiprow" role="group" aria-label="按房间筛选"><span className="lb">房间</span>
                  {[{ id: "", name: "不限" }, ...roomsIn.map((r) => ({ id: String(r.id), name: r.name }))].map((r) => (
                    <button key={r.id} type="button" className={`chip${rm === r.id ? " on" : ""}`} aria-pressed={rm === r.id} onClick={() => setFilter(flEff, r.id)}>{r.name}</button>
                  ))}
                </div>}
              </div>
              {(flEff || rm) && <div className="noteline"><span>已按{fname ? <>楼层「<b>{fname}</b>」</> : null}{roomObj ? <> + 房间「<b>{roomObj.name}</b>」</> : null}筛选，本工段 {list.length} / {items.length} 项</span><button type="button" onClick={() => setFilter("", "")}>清除筛选</button></div>}
              <div className="scroll-x"><table className="tasktbl">
                <thead><tr><th>#</th><th>工作项</th><th>工作说明与验收标准</th><th>楼层 / 房间</th><th>计划</th><th>实际</th><th>负责人</th><th className="num">权重</th><th style={{ minWidth: 120 }}>完成度</th><th>状态</th><th>检查点</th><th>资料</th></tr></thead>
                <tbody>{rows.length ? rows.map((t, k) => {
                  const late = (t.progress < 100 && !!t.plannedFinish && t.plannedFinish < d.today) || (!!t.actualFinish && !!t.plannedFinish && t.actualFinish > t.plannedFinish);
                  return (
                    <tr key={t.id}>
                      <td className="muted">{(pg - 1) * 20 + k + 1}</td>
                      <td style={{ minWidth: 180 }}><Link className="tn" to={`/p/${pid}/work-items/${t.id}`}>{t.name}</Link></td>
                      <td className="tnote">{t.description || <span className="muted">待补充工作说明</span>}<div className="std"><b>验收</b>{t.acceptanceCriteria || "待补充"}</div></td>
                      <td><div style={{ display: "flex", flexDirection: "column", gap: 2, alignItems: "flex-start" }}><span className="fl-tag">{t.floorName}</span><span className="muted nowrap" style={{ fontSize: "var(--text-xs)" }}>{t.floorId === null ? "全楼通用" : t.roomName}</span></div></td>
                      <td className={`nowrap${late ? " down" : ""}`}>{md(t.plannedFinish)}</td>
                      <td className="nowrap">{t.actualFinish ? md(t.actualFinish) : "—"}{late && <> <span className="tag bad">滞后</span></>}</td>
                      <td className="nowrap">{t.ownerName}</td><td className="num">{t.weight}</td>
                      <td><CellBar v={t.progress} color={t.progress >= 100 ? "var(--success)" : undefined} /></td>
                      <td><span className={`tag ${t.status === "已完成" ? "ok" : t.status === "进行中" ? "brand" : ""}`}>{t.status}</span></td>
                      <td className="nowrap">{t.checkpointSeal ? <Link to={`/p/${pid}/checkpoints/${t.checkpointSeal.checkpointId}`} title={t.checkpointSeal.code} style={{ textDecoration: "none" }}><Seal kind={t.checkpointSeal.kind}>{t.checkpointSeal.text}</Seal></Link> : <span className="muted">—</span>}</td>
                      <td><Link className={`docbtn${t.attachmentCount ? "" : " zero"}`} to={`/p/${pid}/work-items/${t.id}#files`} aria-label={`资料 ${t.attachmentCount} 个`}><Icon name="folder" />{t.attachmentCount}</Link></td>
                    </tr>
                  );
                }) : <tr><td colSpan={12} className="muted" style={{ textAlign: "center", padding: "var(--space-8)" }}>该筛选条件下本工段暂无工作项。项目经理可在项目结构中新增并指定楼层与房间。</td></tr>}</tbody>
              </table></div>
              <div className="hint">{(flEff || rm) && <>当前筛选范围加权完成度 <b className="num-b">{f1(prog(list))}%</b>（{list.length} 项）　｜　</>}工段加权完成度 <b className="num-b">{f1(p.progress)}%</b> = Σ(权重 × 完成度) ÷ Σ权重　｜　「不得覆盖」表示该工作项有未放行的隐蔽检查点</div>
              {pages > 1 && <div className="pager"><span>第 {pg} / {pages} 页 · 每页 20 条</span><button className="btn sm" type="button" disabled={pg === 1} onClick={() => setPage(pg - 1)}>上一页</button><button className="btn sm" type="button" disabled={pg === pages} onClick={() => setPage(pg + 1)}>下一页</button></div>}
            </section>

            <section className="card" aria-labelledby="fr-t">
              <div className="card-hd"><h2 id="fr-t">本工段楼层 · 房间分布</h2><span className="desc">点楼层名或房间筛选上方工作项</span><span className="spacer" /><Link className="btn sm" to={`/p/${pid}/floors`}>楼层 / 房间视图</Link></div>
              <div className="card-bd"><div className="frgrid">
                {[...floorsIn.map((f) => ({ id: String(f.id), name: f.name })), ...(hasCommon ? [{ id: ALL, name: "全楼通用" }] : [])].map((f) => {
                  const ts = items.filter((t) => (f.id === ALL ? t.floorId === null : String(t.floorId) === f.id));
                  const v = prog(ts);
                  const rs = f.id === ALL ? [] : d.rooms.filter((r) => String(r.floorId) === f.id && ts.some((t) => t.roomId === r.id));
                  return (
                    <div key={f.id} className="frbox">
                      <div className="h"><button type="button" onClick={() => { setFilter(f.id, ""); scrollTasks(); }}>{f.name}</button><span className="tag">{ts.length} 项</span><span style={{ marginLeft: "auto" }} className="num-b">{f1(v)}%</span></div>
                      <div className="pbar" style={{ marginBottom: "var(--space-2)" }}><i style={{ width: `${v}%`, background: `var(${p.colorVar})` }} /></div>
                      {rs.map((r) => <button key={r.id} type="button" className="rmchip" onClick={() => { setFilter(f.id, String(r.id)); scrollTasks(); }}>{r.name} <b>{f1(prog(ts.filter((t) => t.roomId === r.id)))}%</b></button>)}
                    </div>
                  );
                })}
              </div></div>
            </section>

            <div className="grid-2">
              <section className="card" aria-labelledby="att-t">
                <div className="card-hd"><h2 id="att-t">每日出勤人数</h2><span className="desc">{p.plannedStart} ~ {p.plannedEnd}</span></div>
                <div className="card-bd"><div className="chartbox"><AttChart d={d} /></div></div>
                <div className="legend"><span><i style={{ background: `var(${p.colorVar})` }} />当日出勤人数</span><span><i style={{ background: "var(--surface)", border: "1px dashed var(--muted)" }} />未登记（按 0 计）</span><span><i style={{ background: "var(--danger)" }} />今天</span></div>
                <div className="attstats"><span>累计人工日 <b>{a.total}</b> 人·日</span><span>日均出勤 <b>{f1(a.avg)}</b> 人</span><span>出勤峰值 <b>{a.peak}</b> 人</span><span>施工天数 <b>{a.workDays}</b> 天</span><span>未登记 <b>{a.unregistered}</b> 天</span></div>
              </section>
              <section className="card" aria-labelledby="attl-t">
                <div className="card-hd"><h2 id="attl-t">出勤明细台账</h2><span className="desc">只记录人工登记，未登记日期不推算</span></div>
                <div className="card-bd tight"><div className="scroll-x" style={{ maxHeight: 420, overflowY: "auto" }}><table>
                  <thead><tr><th>日期</th><th>星期</th><th className="num">出勤人数</th><th>来源</th><th /></tr></thead>
                  <tbody>{ledger.length ? ledger.map((x) => {
                    const r = att.get(x);
                    return (
                      <tr key={x} style={x === d.today ? { background: "var(--accent-soft)" } : undefined}>
                        <td className="nowrap">{x}{x === d.today && <> <span className="tag brand">今天</span></>}</td><td>周{wk(x)}</td>
                        <td className="num">{r ? <b>{r.headcount}</b> : <span className="muted">未登记</span>}</td>
                        <td className="muted nowrap">{r ? SOURCE_LABEL[r.source] || r.source : "—"}</td>
                        <td style={{ textAlign: "right" }}>{can("attendance.edit") && <button className="btn sm" type="button" onClick={() => setDlg({ kind: "att", date: x })}>{r ? "修改" : "登记"}</button>}</td>
                      </tr>
                    );
                  }) : <tr><td colSpan={5} className="muted" style={{ textAlign: "center", padding: "var(--space-6)" }}>工段尚未开始，暂无出勤记录。</td></tr>}</tbody>
                </table></div></div>
              </section>
            </div>

            <section className="card" aria-labelledby="ph-t">
              <div className="card-hd"><h2 id="ph-t">工作完成验收图片</h2><span className="desc">新上传默认「待复验」 · 状态在 施工中 → 待复验 → 已验收 之间切换</span><span className="spacer" />
                <span className="row" style={{ gap: "var(--space-1)" }}><span className="tag ok">已验收 {cnt["已验收"]}</span><span className="tag warn">待复验 {cnt["待复验"]}</span><span className="tag">施工中 {cnt["施工中"]}</span></span></div>
              <div className="card-bd"><div className="photos">
                {d.photos.map((x) => (
                  <figure key={x.id} className="photo">
                    <div className="img">{x.file?.thumbUrl ? <img src={x.file.thumbUrl} alt={x.caption} loading="lazy" /> : <Icon name="camera" />}<PhotoSeal s={x.status} /></div>
                    <figcaption className="cap"><span>{x.caption}</span><span className="m">{x.uploaderName || "—"} 上传于 {md(x.createdAt)}{x.source === "prototype_import" && <> · <span className="tag">原型导入</span></>}{!x.file && " · 文件缺失，需重新上传"}</span></figcaption>
                    {can("acceptance_photo.edit") && <div className="ops"><button className="btn sm" type="button" disabled={cycle.isPending} onClick={() => cycle.mutate(x)}>切换为「{PST[(PST.indexOf(x.status) + 1) % 3]}」</button></div>}
                  </figure>
                ))}
                {can("acceptance_photo.edit") && <label className="upcard"><Icon name="upload" /><b>{busy ? "上传中…" : "上传验收图片"}</b><span style={{ fontSize: "var(--text-xs)" }}>JPG / PNG，上传后默认「待复验」</span>
                  <input className="sr" style={{ position: "absolute", width: 1, height: 1, opacity: 0, overflow: "hidden", pointerEvents: "none" }} type="file" accept="image/*" multiple disabled={busy} onChange={(e) => { upload(e.target.files); e.target.value = ""; }} /></label>}
                {!d.photos.length && <p className="muted" style={{ fontSize: "var(--text-sm)", alignSelf: "center" }}>本工段还没有验收图片。进场后上传隐蔽工程与分项验收照片。</p>}
              </div></div>
            </section>

            <section className="card" id="issues" aria-labelledby="is-t">
              <div className="card-hd"><h2 id="is-t">发现问题与闭环</h2><span className="desc">发现 → 对策 → 负责人 → 闭环 · 闭环、重开与作废在问题页处理</span><span className="spacer" />
                <div className="chiprow" role="group" aria-label="按状态筛选">
                  {["全部", "未闭环", "处理中", "已闭环"].map((f) => <button key={f} type="button" className={`chip${isf === f ? " on" : ""}`} aria-pressed={isf === f} onClick={() => setIsf(f)}>{f} {f === "全部" ? d.issues.length : d.issues.filter((i) => i.status === f).length}</button>)}
                  {can("issue.create") && <Link className="btn sm" to={`/p/${pid}/issues?new=1&phase=${p.id}`}><Icon name="plus" />登记问题</Link>}
                </div>
              </div>
              <div className="card-bd">
                {iss.length ? iss.map((i) => {
                  const cost = daysBetween(i.foundOn, i.closedOn || d.today);
                  return (
                    <article key={i.id} className={`issue ${i.status === "已闭环" ? "ok" : i.level === "严重" || i.overdueDays ? "bad" : ""}`}>
                      <div className="h"><span className="tag">{i.code}</span><b>{i.description}</b><LevelTag level={i.level} /><IssueSeal status={i.status} /><span className="fl-tag">{i.floorName}{i.roomName && i.roomName !== "本层通用" ? ` · ${i.roomName}` : ""}</span>
                        {i.overdueDays > 0 && <span className="tag bad">超期 {i.overdueDays} 天</span>}<Link className="btn sm" to={`/p/${pid}/issues?id=${i.id}`}>查看与处理</Link></div>
                      <div className="meta"><span>发现 {i.foundOn}（周{wk(i.foundOn)}）</span><span>负责人 <b style={{ color: "var(--fg)" }}>{i.ownerName}</b></span><span>要求闭环 {i.dueDate || "—"}</span>
                        {i.closedOn && <span>实际闭环 <b className="up">{i.closedOn}</b></span>}<span>{i.status === "已闭环" ? `闭环耗时 ${cost} 天` : `已挂起 ${cost} 天`}</span>
                        <span>来源 {i.checkpointCode ? `检查点 ${i.checkpointCode}` : SOURCE_LABEL[i.source] || "手工登记"}</span></div>
                      <div className="fix"><b>对策：</b>{i.countermeasure}</div>
                    </article>
                  );
                }) : <div className="state">{d.issues.length ? "该筛选条件下暂无问题。" : "本工段暂无问题记录。进场后在此跟踪「发现 → 对策 → 负责人 → 闭环」。"}</div>}
              </div>
            </section>
          </>;
        })()}
      </div>
      {d && dlg?.kind === "plan" && <PlanDialog pid={pid} d={d} onClose={() => setDlg(null)} />}
      {d && dlg?.kind === "att" && <AttDialog pid={pid} d={d} date={"date" in dlg ? dlg.date : undefined} onClose={() => setDlg(null)} />}
      {d && dlg?.kind === "batch" && <div className="f1003-dlg"><BatchDialog pid={pid} d={d} onClose={() => setDlg(null)} /></div>}
    </Shell>
  );
}
