// PAGE-F07-02 · 变更单详情（含发起表单、预算定价、业主签认 / 驳回、驳回后修改重新提交）
// REQ-F07-01~05、AC-F07-01~09、AC-F13-02；DEC-071（来源草稿立即分配编号）、DEC-072（可选附件）
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useBlocker, useNavigate, useParams, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, idemKey, uploadFile, type UploadedFile } from "../api";
import { Shell } from "../layout/Shell";
import { useProject, useSession } from "../session";
import { ConfirmDialog, Field, Icon, Loading, Modal, Seal, useApiError, useToast } from "../ui";
import "../styles/pages/PAGE-F07-02.css";

type Actor = { id: number; name: string } | null;
type CoEvent = { id: number; kind: string; roundNo: number; payload: Record<string, unknown>; actor: Actor; actorRole: string; at: string };
type CoWorkItem = { id: number; name: string; label: string; revision: { revNo: number; at: string } | null };
export type CoDetail = {
  id: number; code: string; roundNo: number; title: string; reasonCategory: string; content: string;
  needsNewDrawing: boolean | null; builtBeforeSign: boolean | null; isLate: boolean; status: string;
  priceDelta: number | null; scheduleDeltaDays: number | null; costBearer: string; rejectReason: string;
  createdBy: Actor; createdAt: string; source: { type: string; id: number; code: string; label: string } | null;
  workItems: CoWorkItem[]; files: UploadedFile[]; events: CoEvent[]; pricedBy: Actor; pricedAt: string | null;
  signedBy: Actor; signedAt: string | null; rejects: { roundNo: number; by: Actor; at: string; reason: string }[];
  drawing: { designManagers: string[]; linkedVersions: { id: number; setId: number; setName: string; versionNo: number; at: string }[]; todoPending: boolean };
  budgetNames: string[];
};
type WiOption = { id: number; label: string };

const REASONS = ["业主要求", "设计深化", "现场条件", "施工纠偏"];
const BEARERS = ["业主", "装修公司", "设计方"];
const SEAL: Record<string, "pass" | "stop" | "pend"> = { 草稿: "pend", 待预算定价: "pend", 待业主签认: "pend", 已生效: "pass", 已驳回: "stop" };
const FIELD_LABELS: Record<string, string> = {
  reasonCategory: "原因类别", content: "变更内容", workItemIds: "受影响工作项（至少 1 个）",
  needsNewDrawing: "是否需要新版图纸", builtBeforeSign: "现场是否已按此施工", fileIds: "附件",
};
const MAX_FILE = 50 * 1024 * 1024;

const fmtFee = (v: number) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toLocaleString("zh-CN");
const fmtDays = (v: number) => (v > 0 ? `+${v}` : v < 0 ? `−${Math.abs(v)}` : "0");
const amtCls = (v: number) => (v > 0 ? "amt-plus" : v < 0 ? "amt-minus" : "");
const t16 = (s: string | null | undefined) => (s ? s.slice(0, 16).replace("T", " ") : "");
const names = (xs: string[]) => xs.join("、");

function eventText(e: CoEvent, all: CoEvent[]) {
  const p = e.payload as Record<string, string | number | boolean | null>;
  switch (e.kind) {
    case "created": return { cls: "ok", t: `发起${p.builtBeforeSign ? "（后补变更）" : ""}，已通知预算专员定价` };
    case "priced": return { cls: "ok", t: `定价：费用 ${fmtFee(Number(p.priceDelta))} 元 · 工期 ${fmtDays(Number(p.scheduleDeltaDays))} 天 · 承担方 ${p.costBearer}` };
    case "signed": return { cls: "ok", t: "业主签认，变更单生效" };
    case "rejected": return { cls: "bad", t: `业主驳回，已退回项目经理。理由：${p.reason}` };
    case "resubmitted": {
      const n = all.filter((x) => x.kind === "resubmitted" && x.id <= e.id).length + 1;
      return { cls: "ok", t: `修改后重新提交（第 ${n} 次提交），回到待预算定价` };
    }
    default: return { cls: "", t: e.kind };
  }
}

/* ——— 发起 / 补齐草稿 / 修改后重新提交 共用表单 ——— */
function CoForm({ pid, mode, co }: { pid: string; mode: "new" | "draft" | "resubmit"; co?: CoDetail }) {
  const nav = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();
  const { me } = useSession();
  const opts = useQuery({ queryKey: ["co-wi-options", pid], queryFn: () => api<{ items: WiOption[] }>(`/projects/${pid}/change-orders/work-item-options`) });
  const [reason, setReason] = useState(co?.reasonCategory || "");
  const [content, setContent] = useState(co?.content || "");
  const [sp] = useSearchParams();
  // 从导入结果「发起变更单」跳转时带 ?item=<工作项 ID>，预选该工作项
  const [sel, setSel] = useState<number[]>(co?.workItems.map((w) => w.id) || (Number(sp.get("item")) ? [Number(sp.get("item"))] : []));
  const [initialSel] = useState(() => new Set(co?.workItems.map((w) => w.id) || []));  // 预填的工作项排在最前
  const [needs, setNeeds] = useState<boolean | null>(mode === "resubmit" ? co?.needsNewDrawing ?? null : null);
  const [built, setBuilt] = useState<boolean | null>(mode === "resubmit" ? co?.builtBeforeSign ?? null : null);
  const [files, setFiles] = useState<UploadedFile[]>(co?.files || []);
  const [kw, setKw] = useState("");
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  const touch = () => setDirty(true);

  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && !done.current && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (blocker.state === "blocked") {
      if (window.confirm("发起表单还有未提交的内容，确定离开吗？")) blocker.proceed();
      else blocker.reset();
    }
  }, [blocker]);
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  const optMap = useMemo(() => new Map((opts.data?.items || []).map((o) => [o.id, o.label])), [opts.data]);
  const labelOf = (id: number) => optMap.get(id) || co?.workItems.find((w) => w.id === id)?.label || `工作项 ${id}`;
  const shown = (opts.data?.items || []).filter((o) => !kw.trim() || o.label.includes(kw.trim()) || sel.includes(o.id))
    .sort((a, b) => Number(initialSel.has(b.id)) - Number(initialSel.has(a.id)));

  function check() {
    const e: Record<string, string> = {};
    if (!reason) e.reasonCategory = "请选择原因类别";
    if (!content.trim()) e.content = "请填写变更内容";
    if (!sel.length) e.workItemIds = "请至少选择 1 个受影响工作项";
    if (needs === null) e.needsNewDrawing = "请选择是否需要新版图纸";
    if (built === null) e.builtBeforeSign = "请选择现场是否已按此施工";
    return e;
  }
  const body = () => ({ reasonCategory: reason, content: content.trim(), title: mode === "new" ? undefined : co?.title,
    workItemIds: sel, needsNewDrawing: needs, builtBeforeSign: built, fileIds: files.map((f) => f.id) });

  async function send() {
    setBusy(true);
    try {
      const path = mode === "new" ? `/projects/${pid}/change-orders` : `/projects/${pid}/change-orders/${co!.id}/${mode === "draft" ? "submit" : "resubmit"}`;
      const r = await api<CoDetail>(path, { body: body(), headers: { "Idempotency-Key": idemKey() } });
      done.current = true;
      qc.invalidateQueries({ queryKey: ["change-orders", pid] });
      qc.invalidateQueries({ queryKey: ["change-order", pid] });
      qc.invalidateQueries({ queryKey: ["todo-count"] });
      if (mode === "resubmit") toast(`已重新提交 ${r.code}，状态：待预算定价，已通知预算专员`);
      else toast(`已生成变更单 ${r.code}，状态：待预算定价，已通知预算专员`);
      nav(`/p/${pid}/changes/${r.id}`, { replace: true });
    } catch (ex) {
      const e = ex as ApiError;
      setConfirm(false);
      if (e.fields?.length) setErrs(e.fieldMap());
      else toast(e.message || "提交失败");
    } finally {
      setBusy(false);
    }
  }

  function submit(ev: FormEvent) {
    ev.preventDefault();
    const e = check();
    setErrs(e);
    if (Object.keys(e).length) {
      document.getElementById("co-missing")?.scrollIntoView({ block: "center" });
      return;
    }
    if (mode === "resubmit") setConfirm(true);
    else send();
  }

  async function addFiles(list: FileList | null) {
    for (const f of Array.from(list || [])) {
      if (f.size > MAX_FILE) { toast(`${f.name}：超过 50MB，未上传`); continue; }
      try {
        const u = await uploadFile(pid, f);
        setFiles((x) => [...x, u]);
        touch();
      } catch (ex) {
        toast((ex as ApiError).message || `${f.name}：上传失败`);
      }
    }
    if (fileRef.current) fileRef.current.value = "";
  }

  const missing = Object.entries(errs);
  const title = mode === "resubmit" ? "修改后重新提交" : "发起变更单";
  const noTag = mode === "resubmit" ? `编号不变 ${co!.code}` : mode === "draft" ? `草稿 ${co!.code}` : "提交后生成编号";
  const lastReject = co?.rejects[co.rejects.length - 1];

  return (
    <section className="card" aria-labelledby="nTitle">
      <div className="card-hd" style={{ flexWrap: "wrap" }}>
        <h2 id="nTitle">{title}</h2><span className="tag">{noTag}</span><span className="spacer" />
        <span className="muted" style={{ fontSize: "var(--text-xs)" }}>发起人：{(mode === "new" ? me?.name : co?.createdBy?.name) || ""}（项目经理）</span>
      </div>
      <form className="card-bd co-form" onSubmit={submit} noValidate>
        {mode === "resubmit" && lastReject && (
          <div className="note bad"><Icon name="alert" /><span>上次驳回：{lastReject.by?.name}（业主）{t16(lastReject.at)}，理由：{lastReject.reason} 请按驳回理由修改后重新提交；重新提交后回到「待预算定价」，需预算专员重新定价。</span></div>
        )}
        {mode === "draft" && co?.source && (
          <div className="note info"><Icon name="doc" /><span>草稿由 {co.source.label} 生成，已预填内容与附件；提交前请补齐其余字段。</span></div>
        )}
        {missing.length > 0 && (
          <div className="note bad" id="co-missing" role="alert"><Icon name="alert" /><span>还缺 {missing.length} 项，不能提交：{missing.map(([k]) => FIELD_LABELS[k] || k).join("、")}</span></div>
        )}
        <Field label="原因类别" required error={errs.reasonCategory}>
          <div className="radios" role="radiogroup" aria-label="原因类别">
            {REASONS.map((r) => <label key={r} className="radio"><input type="radio" name="cat" checked={reason === r} onChange={() => { setReason(r); touch(); }} />{r}</label>)}
          </div>
        </Field>
        <Field label="变更内容" required error={errs.content}>
          <textarea className="textarea" rows={4} value={content} onChange={(e) => { setContent(e.target.value); touch(); }} placeholder="写清在哪里、改什么、改成什么，例如：一楼厨房烟道包封位置西移 120mm" aria-label="变更内容" />
        </Field>
        <Field label={`受影响工作项（至少 1 个，已选 ${sel.length} 个）`} required error={errs.workItemIds}>
          <input className="input" type="search" placeholder="按楼层、房间或工作项名称搜索" aria-label="搜索受影响工作项" value={kw} onChange={(e) => setKw(e.target.value)} />
          <div className="picker" role="group" aria-label="受影响工作项">
            {opts.isLoading ? <div className="hint" style={{ padding: "var(--space-3)" }}>加载工作项…</div>
              : shown.length === 0 ? <div className="hint" style={{ padding: "var(--space-3)" }}>没有匹配的工作项</div>
              : shown.map((o) => (
                <label key={o.id}><input type="checkbox" checked={sel.includes(o.id)} onChange={(e) => { setSel((s) => e.target.checked ? [...s, o.id] : s.filter((x) => x !== o.id)); touch(); }} />{o.label}</label>
              ))}
          </div>
        </Field>
        <div className="grid-2f">
          <Field label="是否需要新版图纸" required error={errs.needsNewDrawing}>
            <div className="radios" role="radiogroup" aria-label="是否需要新版图纸">
              <label className="radio"><input type="radio" name="draw" checked={needs === true} onChange={() => { setNeeds(true); touch(); }} />需要</label>
              <label className="radio"><input type="radio" name="draw" checked={needs === false} onChange={() => { setNeeds(false); touch(); }} />不需要</label>
            </div>
          </Field>
          <Field label="现场是否已按此施工" required error={errs.builtBeforeSign}>
            <div className="radios" role="radiogroup" aria-label="现场是否已按此施工">
              <label className="radio"><input type="radio" name="late" checked={built === true} onChange={() => { setBuilt(true); touch(); }} />已施工</label>
              <label className="radio"><input type="radio" name="late" checked={built === false} onChange={() => { setBuilt(false); touch(); }} />未施工</label>
            </div>
          </Field>
        </div>
        {built === true && <div className="note warn"><Icon name="alert" /><span>将标记为「后补变更」：计入「变更先签后做比例」的分母，不计入分子。</span></div>}
        <Field label="附件（选填，单个不超过 50MB）" error={errs.fileIds}>
          <div className="attach">
            {files.length ? files.map((f) => (
              <span key={f.id} className="tag">{f.name}
                <button type="button" className="link-btn" style={{ marginLeft: 6 }} aria-label={`移除 ${f.name}`} onClick={() => { setFiles((x) => x.filter((y) => y.id !== f.id)); touch(); }}>×</button>
              </span>
            )) : <span className="muted" style={{ fontSize: "var(--text-sm)" }}>暂无附件</span>}
          </div>
          <div><button type="button" className="btn sm" onClick={() => fileRef.current?.click()}><Icon name="upload" />添加附件</button></div>
          <input ref={fileRef} type="file" multiple hidden onChange={(e) => addFiles(e.target.files)} />
        </Field>
        <div className="actions-bar">
          <button type="submit" className="btn primary" disabled={busy}>{busy ? "提交中…" : mode === "resubmit" ? "重新提交变更单" : "提交变更单"}</button>
          {mode === "resubmit"
            ? <Link className="btn" to={`/p/${pid}/changes/${co!.id}`}>取消</Link>
            : <Link className="btn" to={`/p/${pid}/changes`}>取消</Link>}
        </div>
      </form>
      {confirm && co && (
        <ConfirmDialog title={`重新提交变更单 ${co.code}`} confirmText="确认重新提交" busy={busy} onClose={() => setConfirm(false)} onConfirm={send}
          warn="提交后不可撤回；驳回记录不会被修改或删除。"
          summary={[
            ["编号", `${co.code}（不变）`], ["原因类别", reason], ["变更内容", content.trim()],
            ["受影响工作项", sel.map(labelOf).join("；")], ["需要新版图纸", needs ? "需要" : "不需要"],
            ["现场是否已施工", built ? "已施工（后补变更）" : "未施工"],
            ["提交后", `状态回到「待预算定价」，原定价作废，向预算专员${co.budgetNames.length ? " " + names(co.budgetNames) : ""} 生成待办`],
            ["历史", `原驳回记录与理由（${t16(lastReject?.at)}）保留在流转记录中`],
          ]} />
      )}
    </section>
  );
}

/* ——— 预算定价 ——— */
function PriceCard({ pid, co, canPrice }: { pid: string; co: CoDetail; canPrice: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [fee, setFee] = useState("");
  const [days, setDays] = useState("");
  const [bearer, setBearer] = useState("");
  const [errs, setErrs] = useState<Record<string, string>>({});
  const m = useMutation({
    mutationFn: () => api<CoDetail>(`/projects/${pid}/change-orders/${co.id}/price`, { body: { priceDelta: Number(fee), scheduleDeltaDays: Number(days), costBearer: bearer }, headers: { "Idempotency-Key": idemKey() } }),
    onSuccess: (d) => {
      qc.setQueryData(["change-order", pid, String(co.id)], d);
      qc.invalidateQueries({ queryKey: ["change-orders", pid] });
      qc.invalidateQueries({ queryKey: ["todo-count"] });
      toast("已提交定价，已通知业主签认");
    },
    onError: (e: ApiError) => (e.fields?.length ? setErrs(e.fieldMap()) : toast(e.message)),
  });
  const priced = co.priceDelta !== null;
  function submit(ev: FormEvent) {
    ev.preventDefault();
    const e: Record<string, string> = {};
    if (fee.trim() === "" || Number.isNaN(Number(fee))) e.priceDelta = "请填写费用增减";
    if (days.trim() === "" || !Number.isInteger(Number(days))) e.scheduleDeltaDays = "请填写工期影响（整数天）";
    if (!bearer) e.costBearer = "请选择费用承担方";
    setErrs(e);
    if (!Object.keys(e).length) m.mutate();
  }
  if (co.status === "草稿") return null;
  return (
    <section className="card" aria-labelledby="pTitle">
      <div className="card-hd"><h2 id="pTitle">预算定价</h2><span className="spacer" />{priced && co.pricedBy && <span className="muted" style={{ fontSize: "var(--text-xs)" }}>定价：{co.pricedBy.name} · {t16(co.pricedAt)}</span>}</div>
      <div className="card-bd">
        {priced ? (
          <div className="price">
            <div><div className="l">费用增减（元）</div><div className={`v ${amtCls(co.priceDelta!)}`}>{fmtFee(co.priceDelta!)}</div></div>
            <div><div className="l">工期影响（天）</div><div className="v">{fmtDays(co.scheduleDeltaDays!)}</div></div>
            <div><div className="l">费用承担方</div><div className="v" style={{ fontSize: "var(--text-xl)" }}>{co.costBearer}</div></div>
          </div>
        ) : co.status === "待预算定价" && canPrice ? (
          <form className="co-form" onSubmit={submit} noValidate>
            <div className="grid-3f">
              <Field label="费用增减（元）" required error={errs.priceDelta}>
                <input className="input num" type="number" step="1" inputMode="numeric" placeholder="增加填正数，减少填负数" aria-label="费用增减（元）" value={fee} onChange={(e) => setFee(e.target.value)} />
              </Field>
              <Field label="工期影响（天）" required error={errs.scheduleDeltaDays}>
                <input className="input num" type="number" step="1" inputMode="numeric" placeholder="可填 0 或负数" aria-label="工期影响（天）" value={days} onChange={(e) => setDays(e.target.value)} />
              </Field>
              <Field label="费用承担方" required error={errs.costBearer}>
                <div className="radios" role="radiogroup" aria-label="费用承担方">
                  {BEARERS.map((b) => <label key={b} className="radio"><input type="radio" name="payer" checked={bearer === b} onChange={() => setBearer(b)} />{b}</label>)}
                </div>
              </Field>
            </div>
            <div className="actions-bar"><button type="submit" className="btn primary" disabled={m.isPending}>{m.isPending ? "提交中…" : "提交定价"}</button></div>
          </form>
        ) : co.status === "待预算定价" ? (
          <div className="note warn"><Icon name="alert" /><span>等待预算专员{co.budgetNames.length ? " " + names(co.budgetNames) : ""} 定价。定价后进入「待业主签认」。</span></div>
        ) : (
          <div className="note"><span>{co.status === "已驳回" ? "本轮定价已随驳回作废，重新提交后由预算专员重新定价。" : "尚未定价。"}</span></div>
        )}
      </div>
    </section>
  );
}

export default function ChangeDetail() {
  const { pid = "", coid = "" } = useParams();
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const onErr = useApiError();
  const { project, can } = useProject(pid);
  const isNew = coid === "new";
  const q = useQuery({ queryKey: ["change-order", pid, coid], queryFn: () => api<CoDetail>(`/projects/${pid}/change-orders/${coid}`), enabled: !isNew && /^\d+$/.test(coid) });
  const [justStamp, setJustStamp] = useState(false);
  const [signOpen, setSignOpen] = useState(false);
  const [rejOpen, setRejOpen] = useState(false);
  const [rejReason, setRejReason] = useState("");
  const [rejErr, setRejErr] = useState("");

  const after = (d: CoDetail, msg: string) => {
    qc.setQueryData(["change-order", pid, coid], d);
    qc.invalidateQueries({ queryKey: ["change-orders", pid] });
    qc.invalidateQueries({ queryKey: ["todo-count"] });
    setJustStamp(true);
    toast(msg);
  };
  const sign = useMutation({
    mutationFn: () => api<CoDetail>(`/projects/${pid}/change-orders/${coid}/sign`, { body: {}, headers: { "Idempotency-Key": idemKey() } }),
    onSuccess: (d) => { setSignOpen(false); after(d, `已签认，变更单 ${d.code} 生效`); },
    onError: (e: ApiError) => { setSignOpen(false); onErr(e); q.refetch(); },
  });
  const reject = useMutation({
    mutationFn: () => api<CoDetail>(`/projects/${pid}/change-orders/${coid}/reject`, { body: { reason: rejReason.trim() }, headers: { "Idempotency-Key": idemKey() } }),
    onSuccess: (d) => {
      setRejOpen(false);
      const pm = d.createdBy?.name || "";
      after(d, `已驳回，已通知项目经理${pm ? " " + pm : ""}`);
    },
    onError: (e: ApiError) => { if (e.fields?.length) setRejErr(e.fieldMap().reason || e.message); else { setRejOpen(false); onErr(e); q.refetch(); } },
  });

  const sub = `${project?.name || ""} · 发起、定价、签认全程留痕`;
  const back = <Link className="back" to={`/p/${pid}/changes`}><Icon name="back" />返回变更单列表</Link>;

  if (isNew) {
    if (sp.get("draft")) return <Navigate to={`/p/${pid}/changes/${sp.get("draft")}`} replace />;
    return (
      <Shell title="发起变更单" sub={sub}>
        <div className="pg-f0702">
          {back}
          <div style={{ marginTop: "var(--space-3)" }}>
            {!project ? <Loading /> : can("change.create") ? <CoForm pid={pid} mode="new" /> : (
              <section className="card"><div className="state"><div className="ic"><Icon name="lock" /></div><h3>仅项目经理可以发起变更单</h3><p>你可以在变更单列表查看已有变更单。</p><Link className="btn" to={`/p/${pid}/changes`}>返回变更单列表</Link></div></section>
            )}
          </div>
        </div>
      </Shell>
    );
  }

  const err = q.error as ApiError | null;
  if (err?.status === 403) return <Navigate to="/forbidden" replace />;
  const co = q.data;
  const title = co ? `变更单 ${co.code}` : "变更单详情";
  let body;
  if (!/^\d+$/.test(coid) || err?.status === 404) {
    body = <section className="card" style={{ marginTop: "var(--space-3)" }}><div className="state"><div className="ic"><Icon name="doc" /></div><h3>找不到这张变更单</h3><p>编号可能有误，请从变更单列表重新进入。</p><Link className="btn" to={`/p/${pid}/changes`}>返回变更单列表</Link></div></section>;
  } else if (q.isLoading) {
    body = <div style={{ marginTop: "var(--space-3)" }}><Loading rows={6} /></div>;
  } else if (err || !co) {
    body = <section className="card" style={{ marginTop: "var(--space-3)" }}><div className="state"><div className="ic"><Icon name="alert" /></div><h3>变更单加载失败（网络中断）</h3><p>请检查网络后重试。</p><button type="button" className="btn" onClick={() => q.refetch()}>重新加载</button></div></section>;
  } else if ((co.status === "草稿" || (co.status === "已驳回" && sp.get("resubmit") === "1")) && can("change.create")) {
    body = <div style={{ marginTop: "var(--space-3)" }}><CoForm key={`${co.id}-${co.roundNo}-${co.status}`} pid={pid} mode={co.status === "草稿" ? "draft" : "resubmit"} co={co} /></div>;
  } else {
    const pm = co.createdBy?.name || "";
    const dm = names(co.drawing.designManagers);
    const histRejects = co.rejects.filter((r) => co.status !== "已驳回" || r.roundNo !== co.roundNo);
    const curReject = co.status === "已驳回" ? co.rejects.find((r) => r.roundNo === co.roundNo) : undefined;
    const isOwner = can("change.sign");
    const linked = co.drawing.linkedVersions;
    let drawText = `生效后将向设计经理${dm ? " " + dm : ""} 生成「按变更单出新版图纸」待办，发布新版时可关联本变更单。`;
    if (co.status === "已生效") drawText = linked.length
      ? `设计经理已发布「${linked.map((v) => `${v.setName} V${v.versionNo}`).join("、")}」并关联本变更单（${linked[0].at.slice(0, 10)}）。`
      : `已向设计经理${dm ? " " + dm : ""} 生成「按变更单出新版图纸」待办，等待发布新版并关联本变更单。`;
    if (co.status === "已驳回") drawText = "变更单已驳回，不需要出新版图纸。";
    body = (
      <div className="layout">
        <div>
          <section className="card hd-card" aria-labelledby="dTitle">
            <div className="card-bd">
              <div className="hd-row">
                <div><div className="muted" style={{ fontSize: "var(--text-sm)" }}><span className="mono" style={{ fontSize: "var(--text-sm)" }}>{co.code}</span> · {co.reasonCategory || "草稿"}</div><h2 id="dTitle">{co.title}</h2></div>
                <Seal kind={SEAL[co.status] || "pend"} just={justStamp}>{co.status}</Seal>
              </div>
              {(co.isLate || co.needsNewDrawing) && (
                <div className="row" style={{ gap: "var(--space-2)", flexWrap: "wrap" }}>
                  {co.isLate && <span className="tag warn">后补变更 · 不计入先签后做</span>}
                  {co.needsNewDrawing && <span className="tag brand">需新版图纸</span>}
                </div>
              )}
              <dl className="co-kv">
                <div><dt>发起人</dt><dd>{pm}（项目经理）</dd></div>
                <div><dt>发起时间</dt><dd>{t16(co.events.find((e) => e.kind === "created")?.at || co.createdAt)}</dd></div>
                <div><dt>需要新版图纸</dt><dd>{co.needsNewDrawing === null ? "—" : co.needsNewDrawing ? "需要" : "不需要"}</dd></div>
                <div><dt>现场是否已施工</dt><dd>{co.builtBeforeSign === null ? "—" : co.builtBeforeSign ? "已施工（后补）" : "未施工"}</dd></div>
              </dl>
              {co.source && <div className="note"><span>来源：{co.source.label}</span></div>}
            </div>
          </section>
          <section className="card" aria-labelledby="cTitle">
            <div className="card-hd"><h2 id="cTitle">变更内容</h2></div>
            <div className="card-bd">
              <p className="content">{co.content}</p>
              {co.files.length > 0 && (
                <div className="attach" style={{ marginTop: "var(--space-3)" }}>
                  {co.files.map((f) => <a key={f.id} className="tag" href={f.url} target="_blank" rel="noreferrer">{f.name}</a>)}
                </div>
              )}
            </div>
          </section>
          <section className="card" aria-labelledby="wTitle">
            <div className="card-hd"><h2 id="wTitle">受影响工作项</h2><span className="tag">{co.workItems.length} 项</span></div>
            <div className="card-bd">
              {co.workItems.map((w) => (
                <div className="wi" key={w.id}><Icon name="list" /><Link to={`/p/${pid}/work-items/${w.id}`}>{w.label}</Link><span className="muted">{w.revision ? "基线已追加修订" : "基线未变"}</span></div>
              ))}
            </div>
          </section>
          <PriceCard pid={pid} co={co} canPrice={can("change.price")} />
          <section className="card" aria-labelledby="sTitle">
            <div className="card-hd"><h2 id="sTitle">业主签认</h2></div>
            <div className="card-bd stack">
              {co.status === "待业主签认" && (isOwner ? (
                <div>
                  <p className="muted" style={{ fontSize: "var(--text-sm)", marginBottom: "var(--space-3)" }}>签认后变更单立即生效，并在每个受影响工作项的基线中追加一条引用本变更单的修订；驳回须填写理由。</p>
                  <div className="actions-bar">
                    <button type="button" className="btn primary" onClick={() => setSignOpen(true)}>签认变更单</button>
                    <button type="button" className="btn danger" onClick={() => { setRejReason(""); setRejErr(""); setRejOpen(true); }}>驳回</button>
                  </div>
                </div>
              ) : <div className="note warn"><span>等待业主签认。</span></div>)}
              {co.status === "待预算定价" && <div className="note"><span>定价完成后由业主签认。</span></div>}
              {co.status === "已生效" && <div className="note ok"><Icon name="check" /><span>{co.signedBy?.name}（业主）已于 {t16(co.signedAt)} 签认，变更单已生效。</span></div>}
              {curReject && <div className="note bad"><Icon name="alert" /><span>{curReject.by?.name}（业主）于 {t16(curReject.at)} 驳回，理由：{curReject.reason} 已退回项目经理{pm ? " " + pm : ""} 处理，可修改后重新提交。</span></div>}
              {co.status === "已驳回" && can("change.create") && (
                <div className="actions-bar"><button type="button" className="btn primary" onClick={() => nav(`/p/${pid}/changes/${co.id}?resubmit=1`)}>修改后重新提交</button></div>
              )}
              {histRejects.length > 0 && (
                <div className="note"><span>历史驳回 {histRejects.length} 次（记录保留）：{histRejects.map((r, i) => `第 ${i + 1} 次 ${r.by?.name} ${t16(r.at)}，理由：${r.reason}`).join("；")}</span></div>
              )}
              {co.status === "已生效" && (
                <div>
                  <h3 style={{ fontSize: "var(--text-sm)", color: "var(--fg-2)", marginBottom: "var(--space-2)" }}>基线追加修订</h3>
                  {co.workItems.map((w) => (
                    <div className="wi" key={w.id}>{w.label}<span className="muted">{w.revision ? `追加修订 R${w.revision.revNo} · 引用 ${co.code} · ${t16(w.revision.at)}` : "—"}</span></div>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
        <aside>
          {co.needsNewDrawing && (
            <section className="card" aria-labelledby="drTitle">
              <div className="card-hd"><h2 id="drTitle">新版图纸</h2></div>
              <div className="card-bd stack">
                <div className="note info"><Icon name="map" /><span>{drawText}</span></div>
                {co.status === "已生效" && <Link className="btn sm" to={`/p/${pid}/drawings`} style={{ alignSelf: "flex-start" }}>查看图纸分册</Link>}
              </div>
            </section>
          )}
          <section className="card" aria-labelledby="tlTitle">
            <div className="card-hd"><h2 id="tlTitle">流转记录</h2></div>
            <div className="card-bd">
              {co.events.length === 0 ? <p className="hint">草稿尚未提交。</p> : (
                <ol className="tl">
                  {co.events.map((e) => {
                    const x = eventText(e, co.events);
                    return <li key={e.id} className={x.cls}><div className="t">{x.t}</div><div className="m">{e.actor?.name}（{e.actorRole}）· {t16(e.at)}</div></li>;
                  })}
                  {co.status === "已生效" && co.needsNewDrawing && <li className="ok"><div className="t">已向设计经理生成「按变更单出新版图纸」待办</div><div className="m">系统 · {t16(co.signedAt)}</div></li>}
                </ol>
              )}
              <p className="muted" style={{ fontSize: "var(--text-xs)" }}>流转与签认记录只能追加，不能修改或删除。</p>
            </div>
          </section>
        </aside>
        {signOpen && (
          <ConfirmDialog title={`签认变更单 ${co.code}`} confirmText="确认签认" busy={sign.isPending} onClose={() => setSignOpen(false)} onConfirm={() => sign.mutate()}
            summary={[
              ["变更单", `${co.code} ${co.title}`], ["原因类别", co.reasonCategory], ["费用增减", `${fmtFee(co.priceDelta || 0)} 元`],
              ["工期影响", `${fmtDays(co.scheduleDeltaDays || 0)} 天`], ["费用承担方", co.costBearer],
              ["受影响工作项", co.workItems.map((w) => w.label).join("；")],
              ["签认后", `变更单生效；以上 ${co.workItems.length} 个工作项的基线各追加一条引用 ${co.code} 的修订${co.needsNewDrawing ? `；提醒设计经理${dm}出新版图纸` : ""}`],
            ]} />
        )}
        {rejOpen && (
          <Modal title={`驳回变更单 ${co.code}`} onClose={() => setRejOpen(false)} footer={<>
            <button type="button" className="btn" onClick={() => setRejOpen(false)}>取消</button>
            <button type="button" className="btn danger" disabled={reject.isPending} onClick={() => { if (!rejReason.trim()) { setRejErr("请填写驳回理由"); return; } reject.mutate(); }}>{reject.isPending ? "提交中…" : "确认驳回"}</button>
          </>}>
            <dl className="confirm-summary">
              {([["变更单", `${co.code} ${co.title}`], ["费用增减", `${fmtFee(co.priceDelta || 0)} 元`], ["费用承担方", co.costBearer], ["驳回后", `状态变为「已驳回」，退回项目经理${pm ? " " + pm : ""}`]] as [string, string][]).map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{v}</dd></div>
              ))}
            </dl>
            <div className={`field rj-field${rejErr ? " invalid" : ""}`}>
              <label htmlFor="rjReason">驳回理由<span className="req"> *</span></label>
              <textarea id="rjReason" className="textarea" rows={3} value={rejReason} onChange={(e) => { setRejReason(e.target.value); setRejErr(""); }} placeholder="写清不同意的原因，项目经理会据此修改后重新提交" />
              {rejErr && <span className="err">{rejErr}</span>}
            </div>
          </Modal>
        )}
      </div>
    );
  }

  return (
    <Shell title={title} sub={sub}>
      <div className="pg-f0702">
        {back}
        {body}
      </div>
    </Shell>
  );
}
