// PAGE-F08-01 · 问题（REQ-F08-01~04、AC-F08-02~07、AC-F09-01；DEC-081~084）
// 台账（超期降序）、登记、详情抽屉（原因与处置建议、补充对策与指派、闭环 / 重开 / 作废、提交经验库）
import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, idemKey, type UploadedFile } from "../api";
import { Shell } from "../layout/Shell";
import { useProject } from "../session";
import { ConfirmDialog, Field, Icon, Loading, Modal, Seal, useToast } from "../ui";
import "../styles/pages/PAGE-F08-01.css";

type Ref = { id: number; name: string } | null;
type IssueBrief = {
  id: number; code: string; description: string; level: string; countermeasure: string; ownerName: string;
  foundOn: string; dueDate: string | null; overdueDays: number; cause: string; suggestion: string; status: string;
  closedOn: string | null; voidReason: string; isMismatch: boolean; sourceLabel: string;
  phase: Ref; floor: Ref; room: Ref; workItem: Ref;
  checkpoint: { id: number; code: string; point: string; status: string; latestConclusion: string | null } | null;
};
type IssueDetail = IssueBrief & {
  sourceCheck: { id: number; checkedAt: string; conclusion: string; discoveryPhase: string; note: string; photos: UploadedFile[] } | null;
  events: { id: number; kind: string; label: string; before: string; after: string; reason: string; actor: Ref; actorRole: string; at: string }[];
  changeOrders: { id: number; code: string; status: string }[];
};
type ListResp = { items: IssueBrief[]; total: number; page: number; pageSize: number; counts: { open: number; overdue: number; closed: number } };
type Options = { phases: { id: number; name: string }[]; floors: { id: number; name: string; rooms: { id: number; name: string }[] }[]; members: string[] };

const STATUS_CHIPS: [string, string][] = [["valid", "全部有效"], ["未闭环", "未闭环"], ["处理中", "处理中"], ["已闭环", "已闭环"], ["已作废", "已作废"]];
const CAUSES = ["设计已改但未签变更单", "施工偏离签认图", "图纸本身未表达清楚"];
const sealKind = (s: string) => (s === "已闭环" ? "pass" : s === "已作废" ? "proxy" : "pend") as "pass" | "pend" | "proxy";
const t16 = (s: string | null | undefined) => (s ? s.slice(0, 16).replace("T", " ") : "");
const PENDING = ["待补充对策", "待指派"];

function StatusSeal({ s, just }: { s: string; just?: boolean }) {
  if (s === "已作废") return <span className={`seal void${just ? " just" : ""}`}>{s}</span>;
  return <Seal kind={sealKind(s)} just={just}>{s}</Seal>;
}

function eventLine(e: IssueDetail["events"][number]) {
  switch (e.kind) {
    case "created": return "生成问题，状态：未闭环";
    case "cause_set": return `选择原因：${e.after}`;
    case "measure": return `补充对策：${e.reason || e.after}`;
    case "assign": return `指派负责人：${e.after}`;
    case "closed": return "标记已闭环";
    case "reopened": return "重新打开，清除闭环日期";
    case "voided": return `作废：${e.reason}`;
    case "change_draft": return `生成变更单草稿 ${e.after}`;
    default: return e.label;
  }
}

/* ——— 登记问题 ——— */
function RegisterDialog({ pid, opts, onClose, init }: { pid: string; opts?: Options; onClose: () => void; init?: { phaseId: string; floorId: string; roomId: string } }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [v, setV] = useState({ description: "", level: "", phaseId: init?.phaseId || "", dueDate: "", floorId: init?.floorId || "", roomId: init?.roomId || "", countermeasure: "", ownerName: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const set = (k: keyof typeof v, x: string) => { setV((o) => ({ ...o, [k]: x, ...(k === "floorId" ? { roomId: "" } : {}) })); setErrs((e) => ({ ...e, [k]: "" })); };
  const rooms = opts?.floors.find((f) => String(f.id) === v.floorId)?.rooms || [];
  const m = useMutation({
    mutationFn: () => api<IssueDetail>(`/projects/${pid}/issues`, { body: { ...v, phaseId: Number(v.phaseId) || null, floorId: Number(v.floorId) || null, roomId: Number(v.roomId) || null } }),
    onSuccess: (d) => { qc.invalidateQueries({ queryKey: ["issues", pid] }); toast(`已登记问题 ${d.code}，状态：未闭环`); onClose(); },
    onError: (e: ApiError) => (e.fields?.length ? setErrs(e.fieldMap()) : toast(e.message)),
  });
  function submit(ev: FormEvent) {
    ev.preventDefault();
    const e: Record<string, string> = {};
    if (!v.description.trim()) e.description = "请填写问题描述";
    if (!v.level) e.level = "请选择等级";
    if (!v.phaseId) e.phaseId = "请选择所属工段";
    if (!v.dueDate) e.dueDate = "请选择要求闭环日期";
    if (!v.floorId) e.floorId = "请选择楼层";
    if (!v.roomId) e.roomId = "请选择房间";
    setErrs(e);
    if (!Object.keys(e).length) m.mutate();
  }
  return (
    <Modal title="登记问题" onClose={onClose} footer={<>
      <button type="button" className="btn" onClick={onClose}>取消</button>
      <button type="submit" form="regForm" className="btn primary" disabled={m.isPending}>{m.isPending ? "提交中…" : "提交"}</button>
    </>}>
      <form id="regForm" className="is-form" onSubmit={submit} noValidate>
        <Field label="问题描述" required error={errs.description} full>
          <textarea className="textarea" rows={3} aria-label="问题描述" value={v.description} onChange={(e) => set("description", e.target.value)} placeholder="例如：夹层楼梯间墙体砂浆饱满度不足，局部可见透光缝" />
        </Field>
        <Field label="等级" required error={errs.level} full>
          <div className="radios" role="radiogroup" aria-label="等级">
            {["一般", "重要", "严重"].map((l) => <label key={l} className="radio"><input type="radio" name="lv" checked={v.level === l} onChange={() => set("level", l)} />{l}</label>)}
          </div>
        </Field>
        <Field label="所属工段" required error={errs.phaseId}>
          <select className="select" aria-label="所属工段" value={v.phaseId} onChange={(e) => set("phaseId", e.target.value)}>
            <option value="">请选择</option>{opts?.phases.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>
        <Field label="要求闭环日期" required error={errs.dueDate}>
          <input className="input" type="date" aria-label="要求闭环日期" value={v.dueDate} onChange={(e) => set("dueDate", e.target.value)} />
        </Field>
        <Field label="楼层" required error={errs.floorId}>
          <select className="select" aria-label="楼层" value={v.floorId} onChange={(e) => set("floorId", e.target.value)}>
            <option value="">请选择</option>{opts?.floors.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        </Field>
        <Field label="房间" required error={errs.roomId}>
          <select className="select" aria-label="房间" value={v.roomId} onChange={(e) => set("roomId", e.target.value)}>
            <option value="">{rooms.length ? "请选择" : "先选楼层"}</option>{rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </Field>
        <Field label="对策（可空，空时记为「待补充对策」）" full>
          <textarea className="textarea" rows={2} aria-label="对策" value={v.countermeasure} onChange={(e) => set("countermeasure", e.target.value)} />
        </Field>
        <Field label="负责人（可空，空时记为「待指派」）">
          <select className="select" aria-label="负责人" value={v.ownerName} onChange={(e) => set("ownerName", e.target.value)}>
            <option value="">待指派</option>{opts?.members.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </Field>
      </form>
    </Modal>
  );
}

/* ——— 详情抽屉 ——— */
function IssueDrawer({ pid, id, opts, onClose }: { pid: string; id: string; opts?: Options; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const nav = useNavigate();
  const { can } = useProject(pid);
  const q = useQuery({ queryKey: ["issue", pid, id], queryFn: () => api<IssueDetail>(`/projects/${pid}/issues/${id}`) });
  const [block, setBlock] = useState("");
  const [just, setJust] = useState(false);
  const [measure, setMeasure] = useState("");
  const [owner, setOwner] = useState("");
  const [closeOpen, setCloseOpen] = useState(false);
  const [voidOpen, setVoidOpen] = useState(false);
  const [voidReason, setVoidReason] = useState("");
  const [voidErr, setVoidErr] = useState("");
  const [expOpen, setExpOpen] = useState(false);
  const [expPhoto, setExpPhoto] = useState(false);
  const x = q.data;
  useEffect(() => {
    if (x) { setMeasure(x.countermeasure === "待补充对策" ? "" : x.countermeasure); setOwner(x.ownerName === "待指派" ? "" : x.ownerName); }
  }, [x?.countermeasure, x?.ownerName]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && !document.querySelector(".mask.show") && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const apply = (d: IssueDetail, msg: string, stamp = false) => {
    qc.setQueryData(["issue", pid, id], d);
    qc.invalidateQueries({ queryKey: ["issues", pid] });
    setBlock("");
    if (stamp) setJust(true);
    toast(msg);
  };
  const act = (path: string, body: unknown = {}) => api<IssueDetail>(`/projects/${pid}/issues/${id}/${path}`, { body, headers: { "Idempotency-Key": idemKey() } });
  const fail = (e: ApiError) => toast(e.message || "操作失败");
  const cause = useMutation({ mutationFn: (c: string) => act("cause", { cause: c }), onSuccess: (d) => apply(d, "已保存原因，显示对应处置建议"), onError: fail });
  const assign = useMutation({ mutationFn: () => act("assign", { countermeasure: measure, ownerName: owner }), onSuccess: (d) => apply(d, "已保存"), onError: fail });
  const close = useMutation({
    mutationFn: () => act("close"),
    onSuccess: (d) => { setCloseOpen(false); apply(d, `${d.code} 已闭环，闭环日期 ${d.closedOn}`, true); },
    onError: (e: ApiError) => { setCloseOpen(false); if (e.status === 422) setBlock(e.message); else fail(e); },
  });
  const reopen = useMutation({ mutationFn: () => act("reopen"), onSuccess: (d) => apply(d, `${d.code} 已重新打开，状态：处理中`), onError: fail });
  const voidM = useMutation({
    mutationFn: () => act("void", { reason: voidReason.trim() }),
    onSuccess: (d) => { setVoidOpen(false); apply(d, `${d.code} 已作废，可在「已作废」筛选中查看`, true); },
    onError: (e: ApiError) => (e.fields?.length ? setVoidErr(e.fieldMap().reason || e.message) : (setVoidOpen(false), fail(e))),
  });
  const draft = useMutation({
    mutationFn: () => api<{ id: number; code: string; existing: boolean }>(`/projects/${pid}/issues/${id}/change-order-draft`, { body: {} }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["change-orders", pid] });
      qc.invalidateQueries({ queryKey: ["issue", pid, id] });
      toast(r.existing ? `已有变更单 ${r.code}` : `已生成变更单草稿 ${r.code}`);
      nav(`/p/${pid}/changes/${r.id}`);
    },
    onError: fail,
  });
  const exp = useMutation({
    mutationFn: () => api(`/projects/${pid}/issues/${id}/experience`, { body: { photoFileIds: expPhoto ? (x?.sourceCheck?.photos || []).map((p) => p.id) : [] } }),
    onSuccess: () => { setExpOpen(false); qc.invalidateQueries({ queryKey: ["issue", pid, id] }); toast("已提交经验库，等待质检审核"); },
    onError: (e: ApiError) => { setExpOpen(false); fail(e); },
  });

  const canPQ = can("issue.close");
  const open = x && (x.status === "未闭环" || x.status === "处理中");
  const phaseName = x?.phase?.name || "—";
  const procName = x?.workItem?.name || "—";
  const coLinked = x?.changeOrders.filter((c) => c.status !== "已驳回").slice(-1)[0];

  return (
    <div className="dw-wrap" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="dwTitle">
        {!x ? (q.isError ? <div className="state"><div>{(q.error as ApiError)?.message || "加载失败"}</div><button type="button" className="btn sm" onClick={onClose}>关闭</button></div> : <Loading rows={6} />) : (
          <>
            <div className="dw-hd">
              <div style={{ minWidth: 0 }}><div className="mono">{x.code} · {x.isMismatch ? "核对不一致" : "手工登记"}</div><h2 id="dwTitle" style={{ fontSize: "var(--text-lg)", lineHeight: "var(--leading-tight)", overflowWrap: "anywhere" }}>{x.description}</h2></div>
              <span className="spacer" /><StatusSeal s={x.status} just={just} />
              <button type="button" className="icon-btn ghost" aria-label="关闭详情" onClick={onClose}><Icon name="close" /></button>
            </div>
            <div className="dw-bd">
              {block && <div className="note bad" role="alert"><Icon name="alert" /><span>{block}</span></div>}
              <div className="sec">
                <dl className="is-kv">
                  {([["等级", x.level], ["所属工段", phaseName], ["楼层 · 房间", `${x.floor?.name || "—"} · ${x.room?.name || "—"}`], ["负责人", x.ownerName],
                    ["要求闭环日期", x.dueDate || "—"], ["超期天数", x.overdueDays ? `${x.overdueDays} 天` : "未超期"], ["对策", x.countermeasure], ["闭环日期", x.closedOn || "—"],
                    ...(x.status === "已作废" ? [["作废理由", x.voidReason]] : [])] as [string, string][]).map(([k, val]) => (
                    <div key={k}><dt>{k}</dt><dd className={PENDING.includes(val) ? "pending-txt" : k === "超期天数" && x.overdueDays ? "over" : ""}>{val}</dd></div>
                  ))}
                </dl>
              </div>
              {x.isMismatch && x.checkpoint && (
                <div className="sec">
                  <h3>不一致来源</h3>
                  <dl className="is-kv">
                    <div><dt>检查点</dt><dd><Link to={`/p/${pid}/checkpoints/${x.checkpoint.id}`}>{x.checkpoint.code}</Link> · 最新结论：{x.checkpoint.latestConclusion || "—"}</dd></div>
                    <div><dt>工作项</dt><dd>{x.workItem?.name || "—"}</dd></div>
                    <div><dt>发现时点</dt><dd>{x.sourceCheck ? `${x.sourceCheck.discoveryPhase || "—"} · ${t16(x.sourceCheck.checkedAt)}` : "—"}</dd></div>
                    <div><dt>照片</dt><dd>{x.sourceCheck?.photos.length || 0} 张</dd></div>
                  </dl>
                  {!!x.sourceCheck?.photos.length && (
                    <div className="photos" style={{ marginTop: "var(--space-2)" }}>
                      {x.sourceCheck.photos.map((p) => <a key={p.id} className="photo" href={p.url} target="_blank" rel="noreferrer">{p.thumbUrl ? <img src={p.thumbUrl} alt={p.name} /> : p.name}</a>)}
                    </div>
                  )}
                </div>
              )}
              {x.isMismatch && (
                <div className="sec">
                  <h3>不一致原因（质检选择）</h3>
                  <div className="causes" role="radiogroup" aria-label="不一致原因">
                    {CAUSES.map((c) => (
                      <label key={c} className="cause"><input type="radio" name="cause" checked={x.cause === c} disabled={!can("issue.cause") || x.status === "已作废" || cause.isPending} onChange={() => cause.mutate(c)} />{c}</label>
                    ))}
                  </div>
                  <div className="sugg">
                    {!x.cause ? <span className="muted">尚未选择原因。由质检选择后显示处置建议。</span> : <>
                      <div>处置建议：<b>{x.suggestion}</b></div>
                      {x.cause === CAUSES[0] && (coLinked
                        ? <div>已生成变更单 <Link to={`/p/${pid}/changes/${coLinked.id}`}>{coLinked.code}</Link>（{coLinked.status}）</div>
                        : can("change.create") ? <div><button type="button" className="btn sm" disabled={draft.isPending} onClick={() => draft.mutate()}><Icon name="doc" />一键生成变更单草稿</button></div>
                          : <div className="muted">由项目经理一键生成变更单草稿。</div>)}
                      {x.cause === CAUSES[1] && <div>返工完成后，由质检在 <Link to={`/p/${pid}/checkpoints/${x.checkpoint?.id}`}>检查点 {x.checkpoint?.code}</Link> 追加复核核对。</div>}
                      {x.cause === CAUSES[2] && <div>由设计经理在 <Link to={`/p/${pid}/drawings`}>图纸</Link> 发布新版或出具书面澄清。</div>}
                    </>}
                  </div>
                </div>
              )}
              {can("issue.assign") && open && (
                <div className="sec">
                  <h3>补充对策与指派</h3>
                  <div className="is-form">
                    <Field label="对策" full><textarea className="textarea" rows={2} aria-label="对策" value={measure} onChange={(e) => setMeasure(e.target.value)} /></Field>
                    <Field label="负责人">
                      <select className="select" aria-label="负责人" value={owner} onChange={(e) => setOwner(e.target.value)}>
                        <option value="">待指派</option>
                        {[...new Set([...(opts?.members || []), ...(owner ? [owner] : [])])].map((n) => <option key={n} value={n}>{n}</option>)}
                      </select>
                    </Field>
                    <div className="field" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" disabled={assign.isPending} onClick={() => assign.mutate()}>保存</button></div>
                  </div>
                </div>
              )}
              <div className="sec">
                <h3>留痕记录</h3>
                <ol className="tl">
                  {x.events.map((e) => <li key={e.id}>{eventLine(e)}<div className="m">{e.actor?.name}{e.actorRole ? `（${e.actorRole}）` : ""} · {t16(e.at)}</div></li>)}
                </ol>
              </div>
            </div>
            {x.status !== "已作废" && (
              <div className="dw-ft">
                {canPQ && open && <button type="button" className="btn primary" onClick={() => setCloseOpen(true)}>标记已闭环</button>}
                {canPQ && x.status === "已闭环" && <button type="button" className="btn" disabled={reopen.isPending} onClick={() => reopen.mutate()}>重新打开</button>}
                {can("experience.submit") && x.status === "已闭环" && x.isMismatch && <button type="button" className="btn" onClick={() => { setExpPhoto(false); setExpOpen(true); }}>提交到经验库</button>}
                {can("issue.void") && <button type="button" className="btn danger" onClick={() => { setVoidReason(""); setVoidErr(""); setVoidOpen(true); }}>作废</button>}
              </div>
            )}
            {closeOpen && (
              <ConfirmDialog title={`闭环问题 ${x.code}`} confirmText="确认闭环" busy={close.isPending} onClose={() => setCloseOpen(false)} onConfirm={() => close.mutate()}
                summary={[["问题", `${x.code} ${x.description}`], ["当前状态", x.status], ["对策", x.countermeasure], ["负责人", x.ownerName], ["闭环后", "状态「已闭环」，闭环日期记为今天；可重新打开"]]}
                warn={x.isMismatch ? `由不一致核对生成：检查点 ${x.checkpoint?.code} 的最新结论须为一致或已变更` : undefined} />
            )}
            {voidOpen && (
              <Modal title="作废问题" onClose={() => setVoidOpen(false)} footer={<>
                <button type="button" className="btn" onClick={() => setVoidOpen(false)}>取消</button>
                <button type="button" className="btn danger" disabled={voidM.isPending} onClick={() => { if (!voidReason.trim()) { setVoidErr("请填写作废理由"); return; } voidM.mutate(); }}>{voidM.isPending ? "提交中…" : "确认作废"}</button>
              </>}>
                <p className="muted" style={{ fontSize: "var(--text-sm)" }}>问题不能删除。作废后不可撤回，不计入问题统计，仍可在「已作废」筛选中查看。</p>
                <dl className="confirm-summary">
                  {([["问题", `${x.code} ${x.description}`], ["当前状态", x.status]] as [string, string][]).map(([k, val]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{val}</dd></div>)}
                </dl>
                <Field label="作废理由" required error={voidErr}>
                  <textarea className="textarea" rows={2} aria-label="作废理由" value={voidReason} onChange={(e) => { setVoidReason(e.target.value); setVoidErr(""); }} placeholder="例如：与 WT-017 重复登记" />
                </Field>
              </Modal>
            )}
            {expOpen && (
              <Modal title="提交到公司经验库" onClose={() => setExpOpen(false)} footer={<>
                <button type="button" className="btn" onClick={() => setExpOpen(false)}>取消</button>
                <button type="button" className="btn primary" disabled={exp.isPending} onClick={() => exp.mutate()}>{exp.isPending ? "提交中…" : "提交待审核"}</button>
              </>}>
                <div className="note info"><Icon name="shield" /><span>已自动脱敏：只提交以下字段，不含业主姓名、项目地址和照片。提交后进入待审核，审核通过才对其他项目可见。</span></div>
                <dl className="confirm-summary">
                  {([["工段", phaseName], ["工序", procName], ["问题类型", x.cause || "核对不一致"], ["检查要点", x.checkpoint?.point || "—"], ["对策", x.countermeasure]] as [string, string][]).map(([k, val]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{val}</dd></div>)}
                </dl>
                {!!x.sourceCheck?.photos.length && <label className="chk"><input type="checkbox" checked={expPhoto} onChange={(e) => setExpPhoto(e.target.checked)} />另行附带现场照片（{x.sourceCheck.photos.length} 张）</label>}
              </Modal>
            )}
          </>
        )}
      </aside>
    </div>
  );
}

export default function Issues() {
  const { pid = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const { project, can } = useProject(pid);
  const [st, setSt] = useState("valid");
  const [src, setSrc] = useState("");
  const [lv, setLv] = useState("");
  const [ph, setPh] = useState("");
  const [page, setPage] = useState(1);
  // 从总览 / 工段详情「登记问题」跳转时带 ?new=1&phase=&floor=&room=，直接打开并预填
  const [reg, setReg] = useState(sp.get("new") === "1");
  const regInit = { phaseId: sp.get("phase") || "", floorId: sp.get("floor") || "", roomId: sp.get("room") || "" };
  const params = new URLSearchParams({ status: st, page: String(page) });
  if (src) params.set("source", src);
  if (lv) params.set("level", lv);
  if (ph) params.set("phaseId", ph);
  const q = useQuery({ queryKey: ["issues", pid, st, src, lv, ph, page], queryFn: () => api<ListResp>(`/projects/${pid}/issues?${params}`), placeholderData: keepPreviousData });
  const opts = useQuery({ queryKey: ["issue-options", pid], queryFn: () => api<Options>(`/projects/${pid}/issues/options`) });
  const openId = sp.get("id");
  const openIssue = (id: number) => setSp((s) => { s.set("id", String(id)); return s; });
  const closeIssue = () => setSp((s) => { s.delete("id"); return s; }, { replace: true });
  const reset = (fn: () => void) => { fn(); setPage(1); };

  if ((q.error as ApiError | null)?.status === 403) return <Navigate to="/forbidden" replace />;
  const regBtn = can("issue.create") && <button type="button" className="btn primary" onClick={() => setReg(true)}>登记问题</button>;
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.pageSize)) : 1;
  const filtered = st !== "valid" || !!src || !!lv || !!ph;
  const ownerTxt = (x: IssueBrief) => (x.ownerName === "待指派" ? <span className="pending-txt">待指派</span> : x.ownerName);

  return (
    <Shell title="问题" sub={`${project?.name || ""} · 不一致按规则定责，问题有始有终`} actions={regBtn}>
      <div className="pg-f0801">
        <section className="card" aria-labelledby="ledTitle">
          <div className="card-hd" style={{ flexWrap: "wrap" }}>
            <h2 id="ledTitle">问题台账</h2>
            {q.data && <><span className="tag warn">未闭环 {q.data.counts.open}</span><span className="tag bad">超期 {q.data.counts.overdue}</span></>}
          </div>
          <div className="card-bd" style={{ paddingBottom: "var(--space-3)", display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
            <div className="is-filters chip-row" role="group" aria-label="按状态筛选">
              {STATUS_CHIPS.map(([k, label]) => <button key={k} type="button" className={`chip${st === k ? " on" : ""}`} aria-pressed={st === k} onClick={() => reset(() => setSt(k))}>{label}</button>)}
            </div>
            <div className="is-filters">
              <select className="select" aria-label="来源" value={src} onChange={(e) => reset(() => setSrc(e.target.value))}><option value="">全部来源</option><option value="check">核对不一致</option><option value="manual">手工登记</option></select>
              <select className="select" aria-label="等级" value={lv} onChange={(e) => reset(() => setLv(e.target.value))}><option value="">全部等级</option>{["严重", "重要", "一般"].map((l) => <option key={l}>{l}</option>)}</select>
              <select className="select" aria-label="工段" value={ph} onChange={(e) => reset(() => setPh(e.target.value))}><option value="">全部工段</option>{opts.data?.phases.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
              <span className="sortnote">按超期天数从大到小排序</span>
            </div>
          </div>
          {q.isLoading ? <Loading rows={4} /> : q.isError ? (
            <div className="state"><div className="ic"><Icon name="alert" /></div><h3>问题台账加载失败（网络中断）</h3><p>已有数据未受影响，请检查网络后重试。</p><button type="button" className="btn" onClick={() => q.refetch()}>重新加载</button></div>
          ) : q.data && q.data.total === 0 && !filtered ? (
            <div className="state"><div className="ic"><Icon name="alert" /></div><h3>还没有问题</h3><p>核对不一致时系统会自动生成问题，也可以手工登记。</p>{regBtn}</div>
          ) : q.data && q.data.items.length === 0 ? (
            <div className="state"><div className="ic"><Icon name="list" /></div><h3>没有符合条件的问题</h3><p>换个筛选条件再看看。</p></div>
          ) : q.data && (
            <>
              <div className="is-table scroll-x">
                <table>
                  <thead><tr><th style={{ width: 76 }}>编号</th><th>问题</th><th>来源</th><th>等级</th><th>负责人</th><th>要求闭环</th><th className="num">超期（天）</th><th>状态</th></tr></thead>
                  <tbody>
                    {q.data.items.map((x) => (
                      <tr key={x.id} className="row-link" tabIndex={0} onClick={() => openIssue(x.id)} onKeyDown={(e) => e.key === "Enter" && openIssue(x.id)}>
                        <td className="mono" style={{ fontSize: "var(--text-sm)" }}>{x.code}</td>
                        <td><div className="t-title">{x.description}</div><div className="t-sub">{x.phase?.name || "—"} · {x.floor?.name || "—"} · {x.room?.name || "—"}{x.countermeasure === "待补充对策" && <> · <span className="pending-txt">待补充对策</span></>}</div></td>
                        <td>{x.isMismatch ? <span className="tag bad">{x.sourceLabel}</span> : <span className="tag">手工登记</span>}</td>
                        <td><span className={`tag lv-${x.level}`}>{x.level}</span></td>
                        <td>{ownerTxt(x)}</td>
                        <td className="num">{x.dueDate || "—"}</td>
                        <td className="num">{x.overdueDays ? <span className="over">{x.overdueDays}</span> : <span className="muted">—</span>}</td>
                        <td><StatusSeal s={x.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="is-cards">
                {q.data.items.map((x) => (
                  <button key={x.id} type="button" className="is-card" onClick={() => openIssue(x.id)}>
                    <div className="l1">
                      <div><span className="mono">{x.code}</span> <span className={`tag lv-${x.level}`}>{x.level}</span><div className="t-title">{x.description}</div></div>
                      <StatusSeal s={x.status} />
                    </div>
                    <div className="l3">
                      <span>{x.sourceLabel}</span><span>{x.floor?.name || "—"} · {x.room?.name || "—"}</span><span>负责人 {ownerTxt(x)}</span>
                      <span>要求 {x.dueDate || "—"}</span>{x.overdueDays > 0 && <span className="over">超期 {x.overdueDays} 天</span>}
                    </div>
                  </button>
                ))}
              </div>
              <div className="is-pager">
                <span>第 {page} 页 · 每页 {q.data.pageSize} 条</span>
                <button type="button" className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
                <button type="button" className="btn sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>下一页</button>
              </div>
            </>
          )}
        </section>
        {reg && <RegisterDialog pid={pid} opts={opts.data} init={regInit} onClose={() => { setReg(false); if (sp.get("new")) setSp((s) => { ["new", "phase", "floor", "room"].forEach((k) => s.delete(k)); return s; }, { replace: true }); }} />}
        {openId && <IssueDrawer key={openId} pid={pid} id={openId} opts={opts.data} onClose={closeIssue} />}
      </div>
    </Shell>
  );
}
