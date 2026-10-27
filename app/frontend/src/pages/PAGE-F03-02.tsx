// PAGE-F03-02 · 项目结构：楼层与房间、工段、工作项三个页签；新增 / 改名 / 删除（有记录只能停用）、工作项表单。
// AC-F03-02 ~ AC-F03-06、AC-F03-10；DEC-308（删除与停用二次确认）、DEC-309（楼层改变后保留不匹配房间并提交时拒绝）
import { useMemo, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Link, Navigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Shell } from "../layout/Shell";
import { useProject } from "../session";
import { ConfirmDialog, ErrorState, Field, Icon, Loading, Modal, useToast } from "../ui";
import { CellBar, type WorkItem } from "./plan-common";
import "../styles/pages/PAGE-F03-02.css";

type FloorRow = { id: number; name: string; isDisabled: boolean; roomCount: number; recordCount: number; childCount: number };
type RoomRow = { id: number; floorId: number; name: string; isDisabled: boolean; workItemCount: number; recordCount: number; childCount: number };
type PhaseRow = { id: number; name: string; colorVar: string; plannedStart: string; plannedEnd: string; weight: number; isDisabled: boolean; workItemCount: number; progress: number; status: string; recordCount: number };
type Struct = { floors: FloorRow[]; rooms: RoomRow[]; phases: PhaseRow[]; workItems: { total: number; disabled: number } };
type Kind = "floor" | "room" | "phase" | "item";
const LBL: Record<Kind, string> = { floor: "楼层", room: "房间", phase: "工段", item: "工作项" };
const PATH: Record<Kind, string> = { floor: "floors", room: "rooms", phase: "phases", item: "work-items" };
const SUB = "从「君华别墅标准模板」复制，可按真实房屋增删改；有记录的结构只能停用";

function StateSeal({ off }: { off: boolean }) {
  return off ? <span className="seal mute">已停用</span> : <span className="tag ok">启用</span>;
}
const Rec = ({ n }: { n: number }) => <td className={`num rec${n ? "" : " zero"}`}>{n}</td>;

function NameDialog({ pid, kind, obj, floors, defFloor, onClose, onDone }: {
  pid: string; kind: "floor" | "room" | "phase"; obj?: { id: number; name: string }; floors: FloorRow[]; defFloor?: number; onClose: () => void; onDone: (msg: string, floorId?: number) => void;
}) {
  const [name, setName] = useState(obj?.name || "");
  const [floorId, setFloorId] = useState(String(defFloor || floors.find((f) => !f.isDisabled)?.id || ""));
  const [err, setErr] = useState("");
  const m = useMutation({
    mutationFn: () => obj ? api(`/projects/${pid}/${PATH[kind]}/${obj.id}`, { method: "PATCH", body: { name: name.trim() } })
      : api(`/projects/${pid}/${PATH[kind]}`, { body: { name: name.trim(), floorId: kind === "room" ? Number(floorId) : undefined } }),
    onSuccess: () => onDone(`${LBL[kind]}「${name.trim()}」已${obj ? "改名" : "新增"}，矩阵与筛选项已同步`, kind === "room" && !obj ? Number(floorId) : undefined),
    onError: (e: ApiError) => setErr(e.fields[0]?.message || e.message),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (!name.trim()) { setErr("请填写名称"); return; } m.mutate(); };
  return (
    <Modal title={`${obj ? "改名 · " : "新增"}${LBL[kind]}`} onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>取消</button><button type="submit" form="name-form" className="btn primary" disabled={m.isPending}>保存</button></>}>
      <form id="name-form" onSubmit={submit} noValidate style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        <Field label="名称" required error={err}><input className="input" maxLength={20} value={name} autoFocus onChange={(e) => setName(e.target.value)} /></Field>
        {kind === "room" && !obj && <Field label="所属楼层" required><select className="select" value={floorId} onChange={(e) => setFloorId(e.target.value)}>{floors.filter((f) => !f.isDisabled).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></Field>}
      </form>
    </Modal>
  );
}

type ItemForm = { name: string; phaseId: string; ownerName: string; floorId: string; roomId: string; plannedFinish: string; weight: string; progress: string; description: string; acceptanceCriteria: string };

function ItemDialog({ pid, s, item, onClose, onDone }: { pid: string; s: Struct; item?: WorkItem; onClose: () => void; onDone: (name: string) => void }) {
  const firstPhase = s.phases.find((p) => !p.isDisabled);
  const init: ItemForm = item ? {
    name: item.name, phaseId: String(item.phaseId), ownerName: item.ownerName === "待指派" ? "" : item.ownerName, floorId: item.floorId ? String(item.floorId) : "all",
    roomId: item.roomId ? String(item.roomId) : "all", plannedFinish: item.plannedFinish || "", weight: String(item.weight), progress: String(item.progress),
    description: item.description, acceptanceCriteria: item.acceptanceCriteria,
  } : { name: "", phaseId: String(firstPhase?.id || ""), ownerName: "", floorId: "", roomId: "", plannedFinish: "", weight: "", progress: "", description: "", acceptanceCriteria: "" };
  const [v, setV] = useState<ItemForm>(init);
  const [err, setErr] = useState<Record<string, string>>({});
  const toast = useToast();
  const floorOpts = s.floors.filter((f) => !f.isDisabled || String(f.id) === init.floorId);
  const roomOpts = v.floorId === "all" ? [{ id: "all", name: "全楼通用" }]
    : v.floorId ? [{ id: "all", name: "本层通用" }, ...s.rooms.filter((r) => String(r.floorId) === v.floorId && (!r.isDisabled || String(r.id) === init.roomId)).map((r) => ({ id: String(r.id), name: r.name }))] : [];
  const stray = v.roomId && v.roomId !== "all" && !roomOpts.some((r) => r.id === v.roomId) ? s.rooms.find((r) => String(r.id) === v.roomId) : undefined;
  const body = () => {
    const full = {
      name: v.name.trim(), phaseId: Number(v.phaseId), ownerName: v.ownerName.trim(), floorId: v.floorId === "all" ? null : Number(v.floorId),
      roomId: v.roomId === "all" || !v.roomId ? null : Number(v.roomId), plannedFinish: v.plannedFinish || null, weight: v.weight.trim(), progress: v.progress.trim(),
      description: v.description.trim(), acceptanceCriteria: v.acceptanceCriteria.trim(),
    };
    if (!item) return full;
    const before = { name: item.name, phaseId: item.phaseId, ownerName: item.ownerName === "待指派" ? "" : item.ownerName, floorId: item.floorId, roomId: item.roomId, plannedFinish: item.plannedFinish, weight: String(item.weight), progress: String(item.progress), description: item.description, acceptanceCriteria: item.acceptanceCriteria };
    return Object.fromEntries(Object.entries(full).filter(([k, x]) => String(x ?? "") !== String(before[k as keyof typeof before] ?? "")));
  };
  const m = useMutation({
    mutationFn: () => item ? api(`/projects/${pid}/work-items/${item.id}`, { method: "PATCH", body: body() }) : api(`/projects/${pid}/work-items`, { body: body() }),
    onSuccess: () => onDone(v.name.trim()),
    onError: (e: ApiError) => { if (e.fields.length) setErr(e.fieldMap()); else toast(e.message); },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (!v.name.trim()) er.name = "请填写工作项名称";
    if (!v.phaseId) er.phaseId = "请选择所属工段";
    if (!v.floorId) er.floorId = "请选择楼层";
    if (!v.roomId) er.roomId = "请选择房间";
    else if (stray) er.roomId = "房间与楼层不匹配";
    if (!/^[1-5]$/.test(v.weight.trim())) er.weight = "权重为 1–5 的整数";
    if (!/^\d+$/.test(v.progress.trim()) || +v.progress > 100) er.progress = "完成度为 0–100 的整数";
    setErr(er);
    if (Object.keys(er).length) return;
    m.mutate();
  };
  const set = (k: keyof ItemForm) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  const locked = item && !["草稿", "已退回"].includes(item.baselineStatus);
  return (
    <Modal title={item ? "编辑工作项" : "新增工作项"} wide onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>取消</button><button type="submit" form="item-form" className="btn primary" disabled={m.isPending}>{m.isPending ? "保存中…" : "保存工作项"}</button></>}>
      <form id="item-form" onSubmit={submit} noValidate style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        <div className="form-grid">
          <Field label="工作项名称" required full error={err.name}><input className="input" maxLength={120} value={v.name} onChange={set("name")} /></Field>
          <Field label="所属工段" required error={err.phaseId}><select className="select" value={v.phaseId} onChange={set("phaseId")}>{s.phases.filter((p) => !p.isDisabled || String(p.id) === init.phaseId).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <Field label="负责人"><input className="input" value={v.ownerName} placeholder="空则记为「待指派」" onChange={set("ownerName")} /></Field>
          <Field label="楼层" required error={err.floorId}><select className="select" value={v.floorId} onChange={(e) => setV({ ...v, floorId: e.target.value, roomId: e.target.value === "all" ? "all" : v.roomId })}>
            <option value="" disabled>请选择楼层</option>{floorOpts.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}<option value="all">全楼通用</option></select></Field>
          <Field label="房间" required error={err.roomId}><select className="select" value={v.roomId} onChange={set("roomId")}>
            <option value="" disabled>请选择房间</option>{roomOpts.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            {stray && <option value={stray.id}>{s.floors.find((f) => f.id === stray.floorId)?.name} · {stray.name}（不属于所选楼层）</option>}</select></Field>
          <Field label="计划日期"><input className="input" type="date" value={v.plannedFinish} onChange={set("plannedFinish")} /></Field>
          <Field label="权重（1–5）" required error={err.weight}><input className="input" type="number" min={1} max={5} step={1} value={v.weight} onChange={set("weight")} /></Field>
          <Field label="完成度（0–100）" required error={err.progress}><input className="input" type="number" min={0} max={100} step={1} value={v.progress} onChange={set("progress")} /></Field>
          <Field label="工作说明" full error={err.description}><textarea className="textarea" rows={3} value={v.description} placeholder="工艺做法、材料要求；留空时按工序说明库补齐" onChange={set("description")} /></Field>
          <Field label="验收标准" full error={err.acceptanceCriteria}><textarea className="textarea" rows={2} value={v.acceptanceCriteria} placeholder="可量化的判定依据；留空时按工序说明库补齐" onChange={set("acceptanceCriteria")} /></Field>
        </div>
        {item && item.recordCount > 0 && <p className="muted" style={{ fontSize: "var(--text-xs)" }}>该工作项已有 {item.recordCount} 条关联记录；已签认的基线内容需走变更单修改。</p>}
        {locked && <p className="muted" style={{ fontSize: "var(--text-xs)" }}>基线状态「{item!.baselineStatus}」：{item!.baselineStatus === "待签认" ? "需业主退回后才能修改，完成度与实际完成日期照常保存。" : "图纸版本、工作说明、验收标准、费用、质检人与计划日期需走变更单修改。"}</p>}
      </form>
    </Modal>
  );
}

export default function Structure() {
  const { pid = "" } = useParams();
  const toast = useToast();
  const qc = useQueryClient();
  const { project, can } = useProject(pid);
  const canEdit = can("structure.edit");
  const q = useQuery({ queryKey: ["structure", pid], queryFn: () => api<Struct>(`/projects/${pid}/structure`) });
  const items = useQuery({ queryKey: ["work-items-all", pid], queryFn: () => api<{ items: WorkItem[] }>(`/projects/${pid}/work-items?includeDisabled=1`) });
  const [tab, setTab] = useState<"fr" | "ph" | "it">("fr");
  const [selFloor, setSelFloor] = useState<number | null>(null);
  const [name, setName] = useState<null | { kind: "floor" | "room" | "phase"; obj?: { id: number; name: string } }>(null);
  const [itemDlg, setItemDlg] = useState<null | { item?: WorkItem }>(null);
  const [del, setDel] = useState<null | { kind: Kind; id: number; label: string; recs: number; children: number }>(null);
  const [fp, setFp] = useState(""), [ff, setFf] = useState(""), [kw, setKw] = useState(""), [off, setOff] = useState(false), [ip, setIp] = useState(1);

  const refresh = () => {
    ["structure", "work-items-all", "floor-view", "overview", "phase-detail", "project", "scope-detail"].forEach((k) => qc.invalidateQueries({ queryKey: [k, pid] }));
  };
  const delM = useMutation({
    mutationFn: (x: NonNullable<typeof del>) => api(`/projects/${pid}/${PATH[x.kind]}/${x.id}`, { method: "DELETE" }),
    onSuccess: () => { setDel(null); toast("已删除，矩阵与筛选项已同步"); refresh(); },
    onError: (e: ApiError) => {
      if (e.code === "HAS_RECORDS_DISABLE_ONLY" && del) setDel({ ...del, recs: Number(e.details.records) || 0, children: Number(e.details.children) || 0 });
      else { setDel(null); toast(e.message); }
    },
  });
  const offM = useMutation({
    mutationFn: (x: NonNullable<typeof del>) => api(`/projects/${pid}/${PATH[x.kind]}/${x.id}/disable`, { body: {} }),
    onSuccess: () => { setDel(null); toast("已停用，历史记录保持可查"); refresh(); },
    onError: (e: ApiError) => { setDel(null); toast(e.message); },
  });

  const s = q.data;
  const list = useMemo(() => (items.data?.items || []).filter((t) => (!fp || String(t.phaseId) === fp) && (!ff || (ff === "all" ? t.floorId === null : String(t.floorId) === ff)) && (!kw.trim() || t.name.includes(kw.trim())) && (off || !t.isDisabled)), [items.data, fp, ff, kw, off]);
  if ((q.error as ApiError | null)?.status === 403) return <Navigate to="/forbidden" replace />;

  const floorSel = s ? (s.floors.find((f) => f.id === selFloor) || s.floors[0]) : undefined;
  const rooms = s && floorSel ? s.rooms.filter((r) => r.floorId === floorSel.id) : [];
  const pages = Math.max(1, Math.ceil(list.length / 20)), pg = Math.min(ip, pages);
  const key = (fn: () => void) => (e: KeyboardEvent) => { if (e.key === "Enter") fn(); };
  const askDel = (kind: Kind, id: number, label: string, recs: number, children: number) => setDel({ kind, id, label, recs, children });
  const ops = (kind: "floor" | "room" | "phase", o: { id: number; name: string; isDisabled: boolean }, recs: number, children: number, extra?: ReactNode) => (
    <td><div className="ops">{extra}{canEdit && !o.isDisabled && <>
      <button className="btn sm" type="button" onClick={(e) => { e.stopPropagation(); setName({ kind, obj: o }); }}>改名</button>
      <button className="btn sm danger" type="button" onClick={(e) => { e.stopPropagation(); askDel(kind, o.id, kind === "room" ? `${s?.floors.find((f) => f.id === (o as RoomRow).floorId)?.name} · ${o.name}` : o.name, recs, children); }}>删除</button>
    </>}</div></td>
  );
  const actions = canEdit && <>
    <Link className="btn" to={`/p/${pid}/import`}><Icon name="download" />Excel 导入导出</Link>
    <button className="btn primary" type="button" onClick={() => setItemDlg({})}><Icon name="plus" />新增工作项</button>
  </>;
  const blocked = del && del.recs + del.children > 0;

  return (
    <Shell title="项目结构" sub={`${project?.name || ""}　｜　${SUB}`} actions={actions}>
      <div className="plan-pg pg-f0302">
        {!canEdit && <div className="rulebox"><Icon name="lock" /><span>当前身份对项目结构只读。结构与工作项由项目经理维护。</span></div>}
        {q.isLoading && <Loading rows={6} />}
        {q.error && <div className="card"><ErrorState error={q.error} retry={() => q.refetch()} /></div>}
        {s && <>
          <div className="tabs" role="tablist" aria-label="结构类别">
            <button role="tab" type="button" aria-selected={tab === "fr"} onClick={() => setTab("fr")}>楼层与房间<span className="cnt">{s.floors.filter((f) => !f.isDisabled).length} / {s.rooms.filter((r) => !r.isDisabled).length}</span></button>
            <button role="tab" type="button" aria-selected={tab === "ph"} onClick={() => setTab("ph")}>工段<span className="cnt">{s.phases.filter((p) => !p.isDisabled).length}</span></button>
            <button role="tab" type="button" aria-selected={tab === "it"} onClick={() => setTab("it")}>工作项<span className="cnt">{s.workItems.total}</span></button>
          </div>

          {tab === "fr" && <section className="tabpanel" role="tabpanel">
            <div className="grid-2">
              <section className="card" aria-labelledby="fl-t">
                <div className="card-hd"><h2 id="fl-t">楼层</h2><span className="desc">点行查看该楼层房间</span><span className="spacer" />{canEdit && <button className="btn sm" type="button" onClick={() => setName({ kind: "floor" })}><Icon name="plus" />新增楼层</button>}</div>
                <div className="card-bd tight"><div className="scroll-x"><table style={{ minWidth: 440 }}>
                  <thead><tr><th>楼层</th><th className="num">房间</th><th className="num">关联记录</th><th>状态</th><th /></tr></thead>
                  <tbody>{s.floors.map((f) => {
                    const fn = () => setSelFloor(f.id);
                    return <tr key={f.id} className={`row-link${f.id === floorSel?.id ? " sel" : ""}${f.isDisabled ? " off" : ""}`} tabIndex={0} onClick={fn} onKeyDown={key(fn)}>
                      <td><b>{f.name}</b></td><td className="num">{f.roomCount}</td><Rec n={f.recordCount} /><td><StateSeal off={f.isDisabled} /></td>{ops("floor", f, f.recordCount, f.childCount)}</tr>;
                  })}</tbody>
                </table></div></div>
              </section>
              <section className="card" aria-labelledby="rm-t">
                <div className="card-hd"><h2 id="rm-t">房间</h2><span className="desc">{floorSel?.name} · {rooms.filter((r) => !r.isDisabled).length} 个启用房间</span><span className="spacer" />{canEdit && <button className="btn sm" type="button" onClick={() => setName({ kind: "room" })}><Icon name="plus" />新增房间</button>}</div>
                <div className="card-bd tight"><div className="scroll-x"><table style={{ minWidth: 440 }}>
                  <thead><tr><th>房间</th><th className="num">工作项</th><th className="num">关联记录</th><th>状态</th><th /></tr></thead>
                  <tbody>{rooms.length ? rooms.map((r) => (
                    <tr key={r.id} className={r.isDisabled ? "off" : ""}>
                      <td><b>{r.name}</b>{r.isDisabled && <div style={{ fontSize: "var(--text-xs)" }}>历史记录仍可在问题与审计中查看</div>}</td>
                      <td className="num">{r.workItemCount}</td><Rec n={r.recordCount} /><td><StateSeal off={r.isDisabled} /></td>{ops("room", r, r.recordCount, r.childCount)}
                    </tr>
                  )) : <tr><td colSpan={5} className="muted" style={{ textAlign: "center", padding: "var(--space-6)" }}>该楼层还没有房间。</td></tr>}</tbody>
                </table></div></div>
              </section>
            </div>
            <p className="muted" style={{ fontSize: "var(--text-xs)" }}>关联记录 = 签认、核对、问题与资料记录之和。增删改后，楼层 × 阶段矩阵、房间 × 阶段矩阵和各处筛选项即时更新。</p>
          </section>}

          {tab === "ph" && <section className="tabpanel" role="tabpanel">
            <section className="card" aria-labelledby="ph-t">
              <div className="card-hd"><h2 id="ph-t">工段</h2><span className="desc">进度按工作项权重加权，状态自动推导不可手改；起止、班组、权重、范围在工段详情中编辑并自动留档</span><span className="spacer" />{canEdit && <button className="btn sm" type="button" onClick={() => setName({ kind: "phase" })}><Icon name="plus" />新增工段</button>}</div>
              <div className="card-bd tight"><div className="scroll-x"><table style={{ minWidth: 860 }}>
                <thead><tr><th>工段</th><th>计划起止</th><th className="num">权重</th><th className="num">工作项</th><th style={{ width: "22%" }}>加权进度</th><th>状态（自动）</th><th className="num">关联记录</th><th /></tr></thead>
                <tbody>{s.phases.map((p) => (
                  <tr key={p.id} className={p.isDisabled ? "off" : ""}>
                    <td className="nowrap"><span className="phase-dot" style={{ background: `var(${p.colorVar})` }} /> <b>{p.name}</b></td>
                    <td className="nowrap">{p.plannedStart} ~ {p.plannedEnd}</td><td className="num">{p.weight}</td><td className="num">{p.workItemCount}</td>
                    <td><CellBar v={p.progress} /></td>
                    <td>{p.isDisabled ? <StateSeal off /> : <span className={`tag ${p.status === "已完成" ? "ok" : p.status === "进行中" ? "brand" : ""}`}>{p.status}</span>}</td>
                    <Rec n={p.recordCount} />
                    {ops("phase", p, p.recordCount, p.workItemCount, !p.isDisabled && can("phase.plan_edit") ? <Link className="btn sm" to={`/p/${pid}/phase/${p.id}`}>编辑计划</Link> : null)}
                  </tr>
                ))}</tbody>
              </table></div></div>
            </section>
          </section>}

          {tab === "it" && <section className="tabpanel" role="tabpanel">
            <section className="card" aria-labelledby="it-t">
              <div className="card-hd"><h2 id="it-t">工作项</h2><span className="desc">筛选结果 {list.length} 项 · 已停用 {s.workItems.disabled} 项</span></div>
              <div className="toolbar">
                <select className="select" aria-label="工段" value={fp} onChange={(e) => { setFp(e.target.value); setIp(1); }}><option value="">全部工段</option>{s.phases.filter((p) => !p.isDisabled).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
                <select className="select" aria-label="楼层" value={ff} onChange={(e) => { setFf(e.target.value); setIp(1); }}><option value="">全部楼层</option>{s.floors.filter((f) => !f.isDisabled).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}<option value="all">全楼通用</option></select>
                <input className="input" aria-label="搜索" placeholder="搜索工作项名称" value={kw} onChange={(e) => { setKw(e.target.value); setIp(1); }} />
                <label className="chk"><input type="checkbox" checked={off} onChange={(e) => { setOff(e.target.checked); setIp(1); }} />显示已停用</label>
              </div>
              {items.isLoading ? <Loading rows={4} /> : <div className="scroll-x"><table style={{ minWidth: 1080 }}>
                <thead><tr><th>工作项</th><th>工段</th><th>楼层 / 房间</th><th>计划</th><th>负责人</th><th className="num">权重</th><th className="num">完成度</th><th className="num">关联记录</th><th>状态</th><th /></tr></thead>
                <tbody>{list.length ? list.slice((pg - 1) * 20, pg * 20).map((t) => (
                  <tr key={t.id} className={t.isDisabled ? "off" : ""}>
                    <td style={{ minWidth: 200 }}><b>{t.name}</b></td><td className="nowrap">{t.phaseName}</td>
                    <td className="nowrap">{t.floorId === null ? "全楼通用" : `${t.floorName} · ${t.roomName}`}</td>
                    <td className="nowrap">{t.plannedFinish || "—"}</td><td className="nowrap">{t.ownerName}</td><td className="num">{t.weight}</td><td className="num">{t.progress}%</td>
                    <Rec n={t.recordCount} /><td><StateSeal off={t.isDisabled} /></td>
                    <td><div className="ops">{canEdit ? !t.isDisabled && <>
                      <button className="btn sm" type="button" onClick={() => setItemDlg({ item: t })}>编辑</button>
                      <button className="btn sm danger" type="button" onClick={() => askDel("item", t.id, t.name, t.recordCount, 0)}>删除</button>
                    </> : <Link className="btn sm" to={`/p/${pid}/work-items/${t.id}`}>查看</Link>}</div></td>
                  </tr>
                )) : <tr><td colSpan={10} className="muted" style={{ textAlign: "center", padding: "var(--space-8)" }}>没有符合条件的工作项。</td></tr>}</tbody>
              </table></div>}
              <div className="pager"><span>第 {pg} / {pages} 页 · 每页 20 条</span><button className="btn sm" type="button" disabled={pg === 1} onClick={() => setIp(pg - 1)}>上一页</button><button className="btn sm" type="button" disabled={pg === pages} onClick={() => setIp(pg + 1)}>下一页</button></div>
            </section>
          </section>}
        </>}

        {s && name && <NameDialog pid={pid} kind={name.kind} obj={name.obj} floors={s.floors} defFloor={floorSel?.id} onClose={() => setName(null)}
          onDone={(msg, fid) => { setName(null); toast(msg); if (fid) setSelFloor(fid); refresh(); }} />}
        {s && itemDlg && <ItemDialog pid={pid} s={s} item={itemDlg.item} onClose={() => setItemDlg(null)}
          onDone={(n) => { setItemDlg(null); setTab("it"); toast(`工作项「${n}」已保存，所属工段进度已重新计算`); refresh(); }} />}
        {del && (blocked ? (
          <ConfirmDialog title={`删除${LBL[del.kind]}`} danger confirmText="确认停用" busy={offM.isPending} onClose={() => setDel(null)} onConfirm={() => offM.mutate(del)}
            summary={[[LBL[del.kind], del.label], ["关联内容", `${del.recs + del.children} 条（签认、核对、问题、资料${del.kind === "item" ? "" : "或下级结构"}）`], ["停用后", "不再出现在新增选项中，已有记录与历史保持可查。"]]}
            warn="停用不可撤回。">
            <div className="blocked" role="alert">已有记录，只能停用</div>
          </ConfirmDialog>
        ) : (
          <ConfirmDialog title={`删除${LBL[del.kind]}`} danger confirmText="确认删除" busy={delM.isPending} onClose={() => setDel(null)} onConfirm={() => delM.mutate(del)}
            summary={[[LBL[del.kind], del.label], ["关联记录", "0 条"], ["删除后", "从楼层 × 阶段矩阵、房间 × 阶段矩阵和筛选项中移除。"]]} />
        ))}
      </div>
    </Shell>
  );
}
