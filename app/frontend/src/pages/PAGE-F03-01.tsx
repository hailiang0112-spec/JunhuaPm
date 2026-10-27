// PAGE-F03-01 · 公司模板与工序说明库（REQ-F03-01 模板修改只影响之后新建的项目；REQ-F03-05 工序规则按顺序首个命中补齐）
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { bj } from "../time";
import { api, ApiError } from "../api";
import { Shell } from "../layout/Shell";
import { useSession } from "../session";
import { ConfirmDialog, Field, Icon, Modal, useToast } from "../ui";
import { AdminOnly, StateCard } from "../acct";
import "../styles/pages/PAGE-F03-01.css";

type Cp = { point: string; isConcealed: boolean };
type Task = { name: string; plan?: string | null; owner?: string; weight: number; floor: string | null; room: string | null; description?: string; criteria?: string; checkpoints?: Cp[] };
type Phase = { code?: string; name: string; start?: string; end?: string; team?: string; weight: number; scope?: string; order?: number; tasks: Task[] };
type Floor = { code: string; name: string; order?: number };
type Room = { code: string; floor: string; name: string; order?: number };
type Content = { phases: Phase[]; floors: Floor[]; rooms: Room[] };
type Rule = { id?: number; order?: number; keywords: string[]; description: string; criteria: string };
type Summary = { id: number; name: string; lastSaved: { at: string; by: string } | null; stats: Record<string, number> };
type Detail = Summary & { content: Content; rules: Rule[]; projectCount: number };

const TABS: [string, string][] = [["phases", "工段"], ["floors", "楼层与房间"], ["items", "工作项与检查点"], ["rules", "工序说明库"]];
const PAGE = 20;
const dot = (i: number) => `var(--phase-${(i % 6) + 1})`;

function matchRule(rules: Rule[], name: string) {
  for (let i = 0; i < rules.length; i++) {
    for (const k of rules[i].keywords) {
      try {
        if (new RegExp(k).test(name)) return i + 1;
      } catch {
        if (name.includes(k)) return i + 1;
      }
    }
  }
  return 0;
}

function Pager({ total, page, setPage, unit }: { total: number; page: number; setPage: (n: number) => void; unit: string }) {
  const pages = Math.max(1, Math.ceil(total / PAGE));
  return (
    <div className="pager">
      <span>共 {total} {unit} · 每页 {PAGE} 条 · 第 {page} 页</span>
      <button type="button" className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
      <button type="button" className="btn sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>下一页</button>
    </div>
  );
}

export default function Templates() {
  const { me } = useSession();
  const admin = !!me?.isCompanyAdmin;
  const toast = useToast();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["admin-templates"], queryFn: () => api<{ items: Summary[]; projectCount: number }>("/admin/templates"), enabled: admin });
  const [tid, setTid] = useState(0);
  const curId = tid || list.data?.items[0]?.id || 0;
  const detail = useQuery({ queryKey: ["admin-template", curId], queryFn: () => api<Detail>(`/admin/templates/${curId}`), enabled: admin && !!curId });
  const [draft, setDraft] = useState<Content | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("phases");
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState(false);
  const [confirm, setConfirm] = useState<{ title: string; summary: [string, ReactNode][]; text: string; danger?: boolean; run: () => void } | null>(null);
  const [phaseEdit, setPhaseEdit] = useState<number | null>(null);
  const [itemEdit, setItemEdit] = useState<{ p: number; t: number } | null>(null);
  const [ruleEdit, setRuleEdit] = useState<number | null>(null);
  const [roomEdit, setRoomEdit] = useState<{ floor: string; idx: number | null } | null>(null);
  const [floorEdit, setFloorEdit] = useState<number | null>(null);
  const [copying, setCopying] = useState(false);
  const [itemPhase, setItemPhase] = useState(0);
  const [itemPage, setItemPage] = useState(1);
  const [rulePage, setRulePage] = useState(1);

  useEffect(() => {
    if (detail.data) {
      setDraft(structuredClone(detail.data.content));
      setRules(structuredClone(detail.data.rules));
      setDirty(false);
    }
  }, [detail.data]);

  const update = (fn: (c: Content) => void) => {
    setDraft((d) => {
      const n = structuredClone(d!);
      fn(n);
      return n;
    });
    setDirty(true);
  };
  const updateRules = (fn: (r: Rule[]) => Rule[]) => {
    setRules((r) => fn(structuredClone(r)));
    setDirty(true);
  };

  const floorName = useMemo(() => Object.fromEntries((draft?.floors || []).map((f) => [f.code, f.name])), [draft]);
  const roomName = useMemo(() => Object.fromEntries((draft?.rooms || []).map((r) => [r.code, r.name])), [draft]);

  if (!admin) return <Shell title="公司模板与工序说明库" sub="修改只影响之后新建的项目"><AdminOnly /></Shell>;

  async function save() {
    if (!draft) return;
    const sum = draft.phases.reduce((s, p) => s + Number(p.weight || 0), 0);
    if (sum !== 100) return toast(`工段权重合计为 ${sum}%，需为 100%`);
    if (draft.phases.some((p) => p.tasks.some((t) => (t.checkpoints || []).some((c) => !c.point.trim())))) return toast("请填写检查要点，或删除空的检查点模板");
    setSaving(true);
    try {
      const d = await api<Detail>(`/admin/templates/${curId}`, { method: "PUT", body: { content: draft, rules } });
      qc.setQueryData(["admin-template", curId], d);
      qc.invalidateQueries({ queryKey: ["admin-templates"] });
      setSaveErr(false);
      toast("模板已保存，只对之后新建的项目生效");
    } catch (e) {
      const a = e as ApiError;
      if (a.status && a.status < 500 && a.fields?.length) toast(a.fields[0].message);
      else setSaveErr(true);
    } finally {
      setSaving(false);
    }
  }

  function pickTemplate(v: string) {
    if (v === "new") return setCopying(true);
    const id = Number(v);
    const go = () => {
      setTid(id);
      setDirty(false);
      toast(`已切换到「${list.data?.items.find((x) => x.id === id)?.name}」`);
    };
    if (dirty) setConfirm({ title: "切换模板", summary: [["提示", "放弃未保存的修改？"]], text: "放弃并切换", danger: true, run: go });
    else go();
  }

  const d = detail.data;
  const sum = draft?.phases.reduce((s, p) => s + Number(p.weight || 0), 0) ?? 0;
  const items = draft ? draft.phases.flatMap((p, pi) => p.tasks.map((t, ti) => ({ p: pi, t: ti, task: t }))).filter((x) => !itemPhase || x.p === itemPhase - 1) : [];
  const top = (
    <div className="row tpl-top">
      {dirty && <span className="dirty"><Icon name="alert" />有未保存的修改</span>}
      <select className="select tpl-pick" aria-label="选择模板" value={curId} onChange={(e) => pickTemplate(e.target.value)}>
        {(list.data?.items || []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        <option value="new">＋ 复制为新模板…</option>
      </select>
      <button type="button" className="btn primary" disabled={saving || !draft} onClick={save}><Icon name="check" />{saving ? "保存中…" : "保存模板"}</button>
    </div>
  );

  return (
    <Shell title="公司模板与工序说明库" sub="修改只影响之后新建的项目" actions={top}>
      <div className="pg-tpl">
        {list.isLoading || detail.isLoading || (!draft && !detail.isError) ? (
          <div className="card"><div className="card-bd" style={{ display: "grid", gap: "var(--space-3)" }}>{[40, 100, 85, 70, 90].map((w, i) => <div key={i} className="skeleton" style={{ width: `${w}%` }} />)}</div></div>
        ) : detail.isError || list.isError || !draft || !d ? (
          <StateCard icon="alert" title="模板加载失败（网络中断），请重试" action={<button type="button" className="btn" onClick={() => detail.refetch()}>重试</button>} />
        ) : (
          <>
            {saveErr && <div className="notice bad" role="alert" style={{ marginBottom: "var(--space-4)" }}><span>模板保存失败（网络中断），修改仍保留在页面上，可重试</span></div>}
            <div className="notice info" style={{ marginBottom: "var(--space-4)" }}>
              <span>保存后只对之后新建的项目生效，已创建的 {d.projectCount} 个项目不变。{d.lastSaved && `最近保存：${bj(d.lastSaved.at).format("YYYY-MM-DD HH:mm")} ${d.lastSaved.by}`}</span>
            </div>
            <div className="card"><div className="summary">
              <div><b>{draft.phases.length}</b>个工段</div>
              <div><b>{draft.floors.length}</b>层 · {draft.rooms.length} 个房间</div>
              <div><b>{draft.phases.reduce((s, p) => s + p.tasks.length, 0)}</b>项工作</div>
              <div><b>{rules.length}</b>条工序规则</div>
            </div></div>
            <div className="tabs" role="tablist" aria-label="模板内容">
              {TABS.map(([k, v]) => <button key={k} type="button" role="tab" aria-selected={tab === k} className={`chip${tab === k ? " on" : ""}`} onClick={() => setTab(k)}>{v}</button>)}
            </div>

            {tab === "phases" && (
              <section className="card tabpanel" role="tabpanel">
                <div className="card-hd"><h2>工段</h2><span className="hint">权重合计 <b>{sum}</b>%</span><span className="spacer" />
                  <button type="button" className="btn sm" onClick={() => { update((c) => { c.phases.push({ name: "", weight: 0, scope: "", tasks: [] }); }); setPhaseEdit(draft.phases.length); }}><Icon name="plus" />添加工段</button>
                </div>
                <div className="scroll-x"><table className="ttable">
                  <thead><tr><th>顺序</th><th>工段</th><th className="num">权重</th><th>施工范围</th><th className="num">工作项</th><th>操作</th></tr></thead>
                  <tbody>{draft.phases.map((p, i) => (
                    <tr key={i}>
                      <td className="ord">{i + 1}</td>
                      <td className="nw"><span className="phase-dot" style={{ background: dot(i), marginRight: 6 }} />{p.name || <span className="hint">未命名</span>}</td>
                      <td className="num">{p.weight}%</td>
                      <td className="desc">{p.scope || <span className="hint">—</span>}</td>
                      <td className="num">{p.tasks.length}</td>
                      <td><button type="button" className="btn sm" onClick={() => setPhaseEdit(i)}>编辑</button></td>
                    </tr>
                  ))}</tbody>
                </table></div>
              </section>
            )}

            {tab === "floors" && (
              <section className="card tabpanel" role="tabpanel">
                <div className="card-hd"><h2>楼层与房间</h2><span className="spacer" />
                  <button type="button" className="btn sm" onClick={() => setFloorEdit(-1)}><Icon name="plus" />添加楼层</button>
                </div>
                {draft.floors.map((f, fi) => {
                  const rooms = draft.rooms.map((r, i) => ({ r, i })).filter((x) => x.r.floor === f.code);
                  return (
                    <div className="floor" key={f.code}>
                      <div className="fn">{f.name} <span className="hint">{rooms.length}</span></div>
                      <div className="rooms">
                        {rooms.map(({ r, i }) => <button type="button" key={r.code} className="tag" onClick={() => setRoomEdit({ floor: f.code, idx: i })}>{r.name}</button>)}
                        {!rooms.length && <span className="hint">本层通用</span>}
                      </div>
                      <div className="row" style={{ flexWrap: "nowrap" }}>
                        <button type="button" className="btn sm" onClick={() => setFloorEdit(fi)}>改名</button>
                        <button type="button" className="btn sm" onClick={() => setRoomEdit({ floor: f.code, idx: null })}><Icon name="plus" />添加房间</button>
                      </div>
                    </div>
                  );
                })}
                <div className="floor"><div className="fn">全楼通用</div><div className="rooms"><span className="hint">楼层留空的工作项（如放线定位、材料进场验收）</span></div><div /></div>
              </section>
            )}

            {tab === "items" && (
              <section className="card tabpanel" role="tabpanel">
                <div className="card-hd" style={{ flexWrap: "wrap" }}><h2>工作项与检查点</h2>
                  <div className="row" role="toolbar" aria-label="按工段筛选">
                    {["全部", ...draft.phases.map((p) => p.name)].map((n, i) => (
                      <button key={i} type="button" className={`chip${itemPhase === i ? " on" : ""}`} onClick={() => { setItemPhase(i); setItemPage(1); }}>{n}</button>
                    ))}
                  </div>
                  <span className="spacer" />
                  <button type="button" className="btn sm" onClick={() => {
                    const p = itemPhase ? itemPhase - 1 : 0;
                    update((c) => { c.phases[p].tasks.push({ name: "", weight: 1, floor: null, room: null, checkpoints: [] }); });
                    setItemEdit({ p, t: draft.phases[p].tasks.length });
                  }}><Icon name="plus" />添加工作项</button>
                </div>
                <div className="scroll-x"><table className="ttable">
                  <thead><tr><th>工作项</th><th>楼层 / 房间</th><th className="num">权重</th><th>工作说明</th><th>验收标准</th><th>检查点模板</th><th>操作</th></tr></thead>
                  <tbody>{items.slice((itemPage - 1) * PAGE, itemPage * PAGE).map(({ p, t, task }) => {
                    const hit = matchRule(rules, task.name);
                    const auto = hit ? <span className="hint">将由工序规则 #{hit} 补齐</span> : <span className="hint">未命中规则，需手工填写</span>;
                    const cps = task.checkpoints || [];
                    return (
                      <tr key={`${p}-${t}`}>
                        <td className="nw"><span className="phase-dot" style={{ background: dot(p), marginRight: 6 }} />{task.name}</td>
                        <td className="nw">{task.floor ? floorName[task.floor] : "全楼通用"}{task.room ? ` / ${roomName[task.room]}` : ""}</td>
                        <td className="num">{task.weight}</td>
                        <td className="desc">{task.description || auto}</td>
                        <td className="desc">{task.criteria || auto}</td>
                        <td className="nw">{cps.length ? `${cps.length} 个（${cps.filter((c) => c.isConcealed).length} 个隐蔽）` : <span className="hint">—</span>}</td>
                        <td><button type="button" className="btn sm" onClick={() => setItemEdit({ p, t })}>编辑</button></td>
                      </tr>
                    );
                  })}</tbody>
                </table></div>
                <Pager total={items.length} page={itemPage} setPage={setItemPage} unit="项" />
              </section>
            )}

            {tab === "rules" && (
              <section className="card tabpanel" role="tabpanel">
                <div className="card-hd"><h2>工序说明库</h2><span className="spacer" />
                  <button type="button" className="btn sm" onClick={() => setRuleEdit(-1)}><Icon name="plus" />添加规则</button>
                </div>
                <div className="card-bd" style={{ paddingBottom: 0 }}><div className="notice plain"><span>按顺序匹配工作项名称：名称包含任一关键词即命中，首个命中的规则补齐空缺的工作说明与验收标准，已填写的内容不会被覆盖。特异规则放在前面，通用规则放在后面。</span></div></div>
                {rules.length ? (
                  <>
                    <div className="scroll-x"><table className="ttable">
                      <thead><tr><th>顺序</th><th>匹配关键词</th><th>工作说明</th><th>验收标准</th><th>操作</th></tr></thead>
                      <tbody>{rules.slice((rulePage - 1) * PAGE, rulePage * PAGE).map((r, k) => {
                        const i = (rulePage - 1) * PAGE + k;
                        return (
                          <tr key={r.id ?? `n${i}`}>
                            <td className="ord">{i + 1}</td>
                            <td><div className="kw">{r.keywords.map((w) => <span key={w} className="tag">{w}</span>)}</div></td>
                            <td className="desc">{r.description}</td>
                            <td className="desc">{r.criteria}</td>
                            <td><div className="row" style={{ flexWrap: "nowrap" }}>
                              <button type="button" className="btn sm" disabled={i === 0} onClick={() => { updateRules((x) => { [x[i - 1], x[i]] = [x[i], x[i - 1]]; return x; }); toast(`规则 #${i + 1} 已上移`); }}>上移</button>
                              <button type="button" className="btn sm" disabled={i === rules.length - 1} onClick={() => { updateRules((x) => { [x[i + 1], x[i]] = [x[i], x[i + 1]]; return x; }); toast(`规则 #${i + 1} 已下移`); }}>下移</button>
                              <button type="button" className="btn sm" onClick={() => setRuleEdit(i)}>编辑</button>
                              <button type="button" className="btn sm danger" onClick={() => setConfirm({
                                title: "删除规则", summary: [["规则", `删除规则 #${i + 1} ${r.keywords.join("、")}？`]], text: "删除", danger: true,
                                run: () => { updateRules((x) => x.filter((_, j) => j !== i)); toast("规则已删除，保存模板后生效"); },
                              })}>删除</button>
                            </div></td>
                          </tr>
                        );
                      })}</tbody>
                    </table></div>
                    <Pager total={rules.length} page={rulePage} setPage={setRulePage} unit="条" />
                  </>
                ) : (
                  <div className="state"><h3>还没有工序规则</h3><p>添加第一条规则，新建工作项时会自动补齐说明。</p></div>
                )}
              </section>
            )}
          </>
        )}
      </div>

      {phaseEdit !== null && draft && (
        <PhaseDialog phase={draft.phases[phaseEdit]} names={draft.phases.filter((_, i) => i !== phaseEdit).map((p) => p.name)}
          onClose={() => { if (!draft.phases[phaseEdit].name) update((c) => { c.phases.splice(phaseEdit, 1); }); setPhaseEdit(null); }}
          onSave={(p) => { update((c) => { Object.assign(c.phases[phaseEdit], p); }); setPhaseEdit(null); toast("工段已更新，保存模板后生效"); }} />
      )}
      {itemEdit && draft && (
        <ItemDialog task={draft.phases[itemEdit.p].tasks[itemEdit.t]} floors={draft.floors} rooms={draft.rooms}
          onClose={() => { if (!draft.phases[itemEdit.p].tasks[itemEdit.t].name) update((c) => { c.phases[itemEdit.p].tasks.splice(itemEdit.t, 1); }); setItemEdit(null); }}
          onSave={(t) => { update((c) => { c.phases[itemEdit.p].tasks[itemEdit.t] = t; }); setItemEdit(null); toast("工作项已更新，保存模板后生效"); }} />
      )}
      {ruleEdit !== null && (
        <RuleDialog rule={ruleEdit >= 0 ? rules[ruleEdit] : { keywords: [], description: "", criteria: "" }} onClose={() => setRuleEdit(null)}
          onSave={(r) => { updateRules((x) => { if (ruleEdit >= 0) x[ruleEdit] = { ...x[ruleEdit], ...r }; else x.push(r); return x; }); setRuleEdit(null); toast("规则已更新，保存模板后生效"); }} />
      )}
      {floorEdit !== null && draft && (
        <NameDialog title={floorEdit >= 0 ? "楼层改名" : "添加楼层"} label="楼层名称" value={floorEdit >= 0 ? draft.floors[floorEdit].name : ""} onClose={() => setFloorEdit(null)}
          onSave={(name) => {
            update((c) => {
              if (floorEdit >= 0) c.floors[floorEdit].name = name;
              else c.floors.push({ code: "", name });
            });
            setFloorEdit(null);
          }} />
      )}
      {roomEdit && draft && (
        <NameDialog title={roomEdit.idx === null ? `添加房间 · ${floorName[roomEdit.floor]}` : "编辑房间"} label="房间名称" value={roomEdit.idx === null ? "" : draft.rooms[roomEdit.idx].name}
          onClose={() => setRoomEdit(null)}
          onDelete={roomEdit.idx === null ? undefined : () => {
            const code = draft.rooms[roomEdit.idx!].code;
            if (draft.phases.some((p) => p.tasks.some((t) => t.room === code))) return toast("该房间下还有模板工作项，请先修改这些工作项");
            update((c) => { c.rooms.splice(roomEdit.idx!, 1); });
            setRoomEdit(null);
          }}
          onSave={(name) => {
            update((c) => {
              if (roomEdit.idx === null) c.rooms.push({ code: "", floor: roomEdit.floor, name });
              else c.rooms[roomEdit.idx].name = name;
            });
            setRoomEdit(null);
          }} />
      )}
      {copying && d && (
        <NameDialog title="复制为新模板" label="新模板名称" value={`${d.name}（副本）`} onClose={() => setCopying(false)}
          onSave={async (name) => {
            try {
              const t = await api<Summary>("/admin/templates", { body: { name, copyFromId: curId } });
              await qc.invalidateQueries({ queryKey: ["admin-templates"] });
              setCopying(false);
              setTid(t.id);
              toast(`已切换到「${t.name}」`);
            } catch (e) {
              toast((e as ApiError).fields?.[0]?.message || (e as ApiError).message);
            }
          }} />
      )}
      {confirm && <ConfirmDialog title={confirm.title} summary={confirm.summary} confirmText={confirm.text} danger={confirm.danger}
        onConfirm={() => { confirm.run(); setConfirm(null); }} onClose={() => setConfirm(null)} />}
    </Shell>
  );
}

function PhaseDialog({ phase, names, onClose, onSave }: { phase: Phase; names: string[]; onClose: () => void; onSave: (p: Partial<Phase>) => void }) {
  const [f, setF] = useState({ name: phase.name, weight: String(phase.weight), scope: phase.scope || "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  function save() {
    const er: Record<string, string> = {};
    if (!f.name.trim()) er.name = "请填写工段名称";
    else if (names.includes(f.name.trim())) er.name = "工段名称重复";
    if (!/^\d+$/.test(f.weight) || Number(f.weight) > 100) er.weight = "权重为 0–100 的整数";
    setErrs(er);
    if (!Object.keys(er).length) onSave({ name: f.name.trim(), weight: Number(f.weight), scope: f.scope.trim() });
  }
  return (
    <Modal title="编辑工段" onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>取消</button><button type="button" className="btn primary" onClick={save}>保存工段</button></>}>
      <div className="tpl-dlg" style={{ display: "grid", gap: "var(--space-3)" }}>
        <Field label="工段名称" required error={errs.name}><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="权重（%）" required error={errs.weight}><input className="input" type="number" min={0} max={100} inputMode="numeric" value={f.weight} onChange={(e) => setF({ ...f, weight: e.target.value })} /></Field>
        <Field label="施工范围"><textarea className="textarea" rows={2} value={f.scope} onChange={(e) => setF({ ...f, scope: e.target.value })} /></Field>
        <div className="hint">各工段权重合计须为 100%，用于按权重加权计算总体进度。</div>
      </div>
    </Modal>
  );
}

function ItemDialog({ task, floors, rooms, onClose, onSave }: { task: Task; floors: Floor[]; rooms: Room[]; onClose: () => void; onSave: (t: Task) => void }) {
  const [t, setT] = useState<Task>({ ...task, checkpoints: structuredClone(task.checkpoints || []) });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const toast = useToast();
  const cps = t.checkpoints || [];
  const setCp = (i: number, c: Partial<Cp>) => setT({ ...t, checkpoints: cps.map((x, j) => (j === i ? { ...x, ...c } : x)) });
  function save() {
    const er: Record<string, string> = {};
    if (!t.name.trim()) er.name = "请填写工作项名称";
    if (!(t.weight >= 1 && t.weight <= 5 && Number.isInteger(t.weight))) er.weight = "权重为 1–5 的整数";
    if (cps.some((c) => !c.point.trim())) er.cps = "请填写检查要点，或删除空的检查点模板";
    setErrs(er);
    if (er.cps) toast(er.cps);
    if (!Object.keys(er).length) onSave({ ...t, name: t.name.trim(), description: t.description?.trim() || undefined, criteria: t.criteria?.trim() || undefined, checkpoints: cps.map((c) => ({ ...c, point: c.point.trim() })) });
  }
  return (
    <Modal title="编辑模板工作项" onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>取消</button><button type="button" className="btn primary" onClick={save}>保存工作项</button></>}>
      <div className="tpl-dlg" style={{ display: "grid", gap: "var(--space-3)" }}>
        <Field label="工作项名称" required error={errs.name}><input className="input" value={t.name} onChange={(e) => setT({ ...t, name: e.target.value })} /></Field>
        <div className="row2">
          <Field label="楼层" required>
            <select className="select" value={t.floor || ""} onChange={(e) => setT({ ...t, floor: e.target.value || null, room: null })}>
              <option value="">全楼通用</option>
              {floors.map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}
            </select>
          </Field>
          <Field label="房间">
            <select className="select" value={t.room || ""} disabled={!t.floor} onChange={(e) => setT({ ...t, room: e.target.value || null })}>
              <option value="">本层通用</option>
              {rooms.filter((r) => r.floor === t.floor).map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
            </select>
          </Field>
        </div>
        <Field label="权重（1–5）" error={errs.weight}><input className="input" type="number" min={1} max={5} step={1} value={t.weight} onChange={(e) => setT({ ...t, weight: Number(e.target.value) })} /></Field>
        <Field label="工作说明"><textarea className="textarea" rows={2} placeholder="留空则按工序说明库补齐" value={t.description || ""} onChange={(e) => setT({ ...t, description: e.target.value })} /></Field>
        <Field label="验收标准"><textarea className="textarea" rows={2} placeholder="留空则按工序说明库补齐" value={t.criteria || ""} onChange={(e) => setT({ ...t, criteria: e.target.value })} /></Field>
        <Field label="检查点模板" error={errs.cps}>
          <div className="cp-edit">
            {cps.map((c, i) => (
              <div className="line" key={i}>
                <input className="input" placeholder="检查要点，如：拉结筋间距 ≤500mm" aria-label="检查要点" value={c.point} onChange={(e) => setCp(i, { point: e.target.value })} />
                <label className="cpchk"><input type="checkbox" checked={c.isConcealed} onChange={(e) => setCp(i, { isConcealed: e.target.checked })} />隐蔽</label>
                <button type="button" className="icon-btn ghost" aria-label="删除检查点模板" onClick={() => setT({ ...t, checkpoints: cps.filter((_, j) => j !== i) })}><Icon name="close" /></button>
              </div>
            ))}
            <button type="button" className="btn sm" style={{ justifySelf: "start" }} onClick={() => setT({ ...t, checkpoints: [...cps, { point: "", isConcealed: true }] })}><Icon name="plus" />添加检查点模板</button>
          </div>
        </Field>
        <div className="hint">只填检查要点和是否隐蔽；图纸位置在项目内对着签认版图纸钉点。</div>
      </div>
    </Modal>
  );
}

function RuleDialog({ rule, onClose, onSave }: { rule: Rule; onClose: () => void; onSave: (r: Rule) => void }) {
  const [f, setF] = useState({ kw: rule.keywords.join("、"), description: rule.description, criteria: rule.criteria });
  const [errs, setErrs] = useState<Record<string, string>>({});
  function save() {
    const keywords = f.kw.split(/[、，,]/).map((x) => x.trim()).filter(Boolean);
    const er: Record<string, string> = {};
    if (!keywords.length) er.kw = "请填写匹配关键词";
    if (!f.description.trim()) er.description = "请填写工作说明";
    if (!f.criteria.trim()) er.criteria = "请填写验收标准";
    setErrs(er);
    if (!Object.keys(er).length) onSave({ ...rule, keywords, description: f.description.trim(), criteria: f.criteria.trim() });
  }
  return (
    <Modal title="编辑工序规则" onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>取消</button><button type="button" className="btn primary" onClick={save}>保存规则</button></>}>
      <Field label="匹配关键词" required error={errs.kw}><input className="input" placeholder="多个关键词用「、」分隔，如：门洞、过梁" value={f.kw} onChange={(e) => setF({ ...f, kw: e.target.value })} /></Field>
      <Field label="工作说明" required error={errs.description}><textarea className="textarea" rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      <Field label="验收标准" required error={errs.criteria}><textarea className="textarea" rows={3} placeholder="写可量化的判定标准" value={f.criteria} onChange={(e) => setF({ ...f, criteria: e.target.value })} /></Field>
    </Modal>
  );
}

function NameDialog({ title, label, value, onClose, onSave, onDelete }: { title: string; label: string; value: string; onClose: () => void; onSave: (v: string) => void; onDelete?: () => void }) {
  const [v, setV] = useState(value);
  const [err, setErr] = useState("");
  return (
    <Modal title={title} onClose={onClose} footer={<>
      {onDelete && <button type="button" className="btn danger" onClick={onDelete} style={{ marginRight: "auto" }}>删除</button>}
      <button type="button" className="btn" onClick={onClose}>取消</button>
      <button type="button" className="btn primary" onClick={() => (v.trim() ? onSave(v.trim()) : setErr(`请填写${label}`))}>保存</button>
    </>}>
      <Field label={label} required error={err}><input className="input" value={v} onChange={(e) => setV(e.target.value)} /></Field>
    </Modal>
  );
}
