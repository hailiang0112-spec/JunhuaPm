// PAGE-F05-01 · 工作项详情：基线（编辑、提交、重签）、检查点列表与新建、修订与签认历史、进度、资料。
// AC-F05-01、AC-F05-02、AC-F05-06、AC-F05-08、AC-F05-10、AC-F06-01、AC-F06-16、AC-F09-04、AC-F12-01~03
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, idemKey, type UploadedFile } from "../api";
import { Shell } from "../layout/Shell";
import { useProject, useSession } from "../session";
import { ConfirmDialog, ErrorState, Field, Icon, Loading, Modal, money, Seal, useApiError, useToast } from "../ui";
import { DrawingStage, fileSize, fmtDate, fmtTime, IC, Svg, type DrawingSet, type Version, type VersionBrief } from "./draw-kit";
import "../styles/pages/PAGE-F05-01.css";

type Content = {
  drawingVersionId: number | null; drawingSetName: string; drawingVersionNo: number | null; description: string; acceptanceCriteria: string;
  cost: string | null; plannedFinish: string | null; qcUserId: number | null; qcUserName: string; checkpoints: { id: number; code: string; point: string; isConcealed: boolean }[];
};
type Rev = { id: number; revNo: number; kind: string; createdAt: string; actor: string; content: Content; signedBy: string | null; signedAt: string | null };
type Attachment = UploadedFile & { attachmentId: number; uploaderId: number | null; uploaderName: string; isVoided: boolean; voidedBy: string | null; voidedAt: string | null; refs: { kind: string; id: number; label: string }[] };
type Detail = {
  workItem: {
    id: number; name: string; phaseId: number; phaseName: string; floorName: string; roomName: string; weight: number; progress: number; actualFinish: string | null;
    description: string; acceptanceCriteria: string; cost: string | null; plannedFinish: string | null; qcUserId: number | null; qcUserName: string; drawingVersion: VersionBrief | null; checkpointHints?: { point: string; isConcealed: boolean }[];
  };
  baseline: {
    id: number; status: string; returnReason: string; currentRevision: Rev | null; signedRevision: Rev | null; effectiveRevision: Rev | null; isResign: boolean;
    baseDrawingVersion: VersionBrief | null; resign: { newVersion: VersionBrief; oldVersion: VersionBrief | null; at: string } | null; soon: boolean;
  };
  history: { at: string; kind: string; text: string; changeOrder?: { id: number; code: string } | null; checkpointId?: number | null }[];
  attachments: Attachment[]; attachmentCount: number; voidedCount: number; checkpointCount: number;
  qcCandidates: { id: number; name: string }[]; ownerNames: string[];
};
type Cp = { id: number; code: string; point: string; isConcealed: boolean; status: string; labels: string[]; isDraft?: boolean; latestCheck: { no: number; conclusion: string } | null; waitingHours?: number | null };
type Suggestion = { id: number; status: string; checkPoint: string };

const LOCKED_MSG = "已签认，请发起变更单或等待新版图纸重签";
const PENDING_MSG = "基线待业主签认，需业主退回后才能修改";
const ATTACH_EXT = [".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf", ".doc", ".docx", ".xls", ".xlsx"];
const MAX = 50 * 1024 * 1024;
const EXP_TAG: Record<string, string> = { 已验证: "ok", 历史观察: "brand", 未验证经验: "" };

export default function WorkItemPage() {
  const { pid, wid } = useParams();
  const { can } = useProject(pid);
  const { me } = useSession();
  const toast = useToast();
  const q = useQuery({ queryKey: ["wi-detail", pid, wid], queryFn: () => api<Detail>(`/projects/${pid}/work-items/${wid}/detail`) });
  const cps = useQuery({ queryKey: ["wi-checkpoints", pid, wid], queryFn: () => api<{ items: Cp[] }>(`/projects/${pid}/work-items/${wid}/checkpoints`) });
  const [edit, setEdit] = useState(false);
  const [newCk, setNewCk] = useState(false);

  if (q.isLoading) return <Shell title="工作项详情"><Loading rows={6} /></Shell>;
  if (q.error || !q.data) return <Shell title="工作项详情"><ErrorState error={q.error} retry={() => q.refetch()} /></Shell>;
  const { workItem: wi, baseline: bl } = q.data;
  const st = bl.status;
  const locked = st === "已签认" || st === "待重签";
  const editable = st === "草稿" || st === "已退回";
  const canEdit = can("baseline.edit") || can("baseline.submit");
  const canSubmit = can("baseline.submit");
  const canCk = can("checkpoint.create");

  const c: Content = bl.effectiveRevision?.content || {
    drawingVersionId: wi.drawingVersion?.id ?? null, drawingSetName: wi.drawingVersion?.setName || "", drawingVersionNo: wi.drawingVersion?.versionNo ?? null,
    description: wi.description, acceptanceCriteria: wi.acceptanceCriteria, cost: wi.cost, plannedFinish: wi.plannedFinish, qcUserId: wi.qcUserId, qcUserName: wi.qcUserName, checkpoints: [],
  };
  const dwText = c.drawingVersionId
    ? `${c.drawingSetName} V${c.drawingVersionNo}${st === "待重签" ? "（原签认版）" : !bl.effectiveRevision && wi.drawingVersion && !wi.drawingVersion.isSigned ? "（待业主签认）" : ""}`
    : "未选择";
  const lockClick = () => toast(st === "待签认" ? PENDING_MSG : LOCKED_MSG);
  const openCk = () => {
    if (st === "待签认") return toast(PENDING_MSG);
    if (!bl.baseDrawingVersion) return toast("请先在基线中选择已签认的图纸版本");
    setNewCk(true);
  };
  const cur = bl.effectiveRevision;
  const addedIds = new Set(q.data.history.filter((h) => h.kind === "checkpoint_added").map((h) => h.checkpointId));
  const rows: [string, string][] = [
    ["图纸分册与版本", dwText], ["工作说明", c.description || "未填写"], ["验收标准", c.acceptanceCriteria || "未填写"], ["费用", money(c.cost)],
    ["计划完成日期", c.plannedFinish || "未填写"], ["质检人", c.qcUserName || "未选择"], ["检查点", `${q.data.checkpointCount} 个（见下方）`],
  ];

  return (
    <Shell activeNav={`/p/${pid}/phase/${wi.phaseId}`} title={wi.name} sub={`${wi.phaseName} · ${wi.floorName}${wi.roomName ? ` · ${wi.roomName}` : ""} · 权重 ${wi.weight} · 质检人 ${wi.qcUserName || "未指定"}`}
      crumb={<><Link to={`/p/${pid}/phase/${wi.phaseId}`}>{wi.phaseName}</Link><Icon name="right" /><Link to={`/p/${pid}/floors`}>{wi.floorName}</Link>{wi.roomName && <><Icon name="right" /><span>{wi.roomName}</span></>}</>}
      actions={<a className="btn" href="#files"><Icon name="folder" />资料 <b className="num">{q.data.attachmentCount}</b></a>}>
      <div className="pg-f0501">
        {st === "待重签" && bl.resign && (
          <div className="banner" role="note"><Icon name="alert" />
            <div><b>基线待重签。</b>{bl.resign.newVersion.setName} V{bl.resign.newVersion.versionNo} 已于 {fmtDate(bl.resign.newVersion.signedAt)} 签认，本工作项受影响。重签前现场仍按原签认版 V{bl.resign.oldVersion?.versionNo} 施工与核对。</div>
            <span className="act" style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
              {bl.resign.oldVersion && <Link className="btn sm" to={`/p/${pid}/drawings/${bl.resign.newVersion.id}?workItem=${wi.id}&compare=${bl.resign.oldVersion.id}`}>对比 V{bl.resign.oldVersion.versionNo} / V{bl.resign.newVersion.versionNo}</Link>}
              {canSubmit && <button type="button" className="btn sm primary" onClick={() => setEdit(true)}>更新图纸版本并重新提交</button>}
            </span>
          </div>
        )}
        {st === "已退回" && (
          <div className="banner bad" role="note"><Icon name="alert" /><div><b>基线已被业主退回。</b>退回理由：{bl.returnReason}</div>
            {canSubmit && <button type="button" className="btn sm primary act" onClick={() => setEdit(true)}>修改后重新提交</button>}</div>
        )}
        {st === "待签认" && <div className="banner note" role="note"><Icon name="alert" /><div><b>{bl.isResign ? "等待业主重签。" : "等待业主签认。"}</b>待签认期间基线锁定，需业主退回后才能修改；进度字段不受影响。</div></div>}
        {bl.soon && <div className="banner bad" role="note"><Icon name="alert" /><div><b>即将施工，基线未签认。</b>计划完成日期 {wi.plannedFinish}，距今不超过 7 天。</div></div>}

        <div className="wgrid">
          <div>
            <section className="card" aria-labelledby="hBase">
              <div className="card-hd"><h2 id="hBase">基线</h2>
                <span className="cur-rev">{cur ? `${st === "待签认" ? "待签认" : "当前生效"} r${cur.revNo} · ${fmtDate(cur.signedAt || cur.createdAt)}` : "尚未提交"}</span>
                <span className="spacer" /><BaselineSeal status={st} />
              </div>
              <div className="card-bd">
                <dl className="kv">
                  {rows.map(([k, v]) => (
                    <div key={k} style={{ display: "contents" }}>
                      <dt>{k}</dt>
                      <dd className="lk"><span>{k === "图纸分册与版本" && bl.baseDrawingVersion
                        ? <Link to={`/p/${pid}/drawings/${bl.baseDrawingVersion.id}?workItem=${wi.id}`}>{v}</Link> : v}</span>{canEdit && !editable && <button type="button" className="icon-btn ghost sm-ic" aria-label={`修改${k}`} onClick={lockClick}><Svg d={IC.lock} /></button>}</dd>
                    </div>
                  ))}
                </dl>
                <p className="fhint"><Svg d={IC.lock} /><span>{locked ? "已签认内容锁定，修订只能通过变更单或新版图纸重签；进度字段不受影响。"
                  : st === "待签认" ? "基线待业主签认，需业主退回后才能修改；进度字段不受影响。" : "填写 7 项必填内容并至少添加 1 个检查点后提交业主签认。"}</span></p>
                {editable && canEdit && (
                  <div className="row" style={{ marginTop: "var(--space-3)" }}>
                    <button type="button" className={`btn${canSubmit && st === "草稿" ? " primary" : ""}`} onClick={() => setEdit(true)}>{canSubmit ? "编辑并提交待签" : "编辑基线"}</button>
                  </div>
                )}
              </div>
            </section>

            <section className="card" aria-labelledby="hCk">
              <div className="card-hd"><h2 id="hCk">检查点</h2><span className="spacer" />{canCk && <button type="button" className="btn" onClick={openCk}><Icon name="plus" />新建检查点</button>}</div>
              <div className="card-bd cklist">
                {cps.isLoading ? <div className="skeleton" /> : cps.error ? <ErrorState error={cps.error} retry={() => cps.refetch()} />
                  : !cps.data?.items.length ? <p className="hint">还没有检查点。先在工作项基线里添加检查点。</p>
                    : cps.data.items.map((k) => (
                      <Link key={k.id} className="ckrow" to={`/p/${pid}/checkpoints/${k.id}`}>
                        <span className="idc">{k.code}</span>
                        <span className="t"><b>{k.point}</b><span>{ckText(k, addedIds.has(k.id))}</span></span>
                        <CkSeal k={k} />
                      </Link>
                    ))}
              </div>
            </section>

            <section className="card" aria-labelledby="hRev">
              <div className="card-hd"><h2 id="hRev">修订与签认历史</h2><span className="spacer" /><span className="muted" style={{ fontSize: "var(--text-xs)" }}>只追加，旧签认记录保留</span></div>
              <div className="card-bd">
                {!q.data.history.length ? <p className="hint">还没有提交记录。</p> : (
                  <ol className="revs">{q.data.history.map((h, i) => (
                    <li key={i}><span className="d">{fmtTime(h.at)}</span><span>{h.text}{h.changeOrder && <> · <Link to={`/p/${pid}/changes/${h.changeOrder.id}`}>{h.changeOrder.code}</Link></>}</span></li>
                  ))}</ol>
                )}
              </div>
            </section>
          </div>

          <div>
            <Progress pid={pid!} wi={wi} canSave={can("structure.edit")} />
            <Files pid={pid!} d={q.data} canUpload={can("file.upload")} meId={me?.id} />
          </div>
        </div>
        {edit && <EditDialog pid={pid!} d={q.data} cps={cps.data?.items || []} canSubmit={canSubmit} onClose={() => setEdit(false)} />}
        {newCk && bl.baseDrawingVersion && <NewCheckpoint pid={pid!} d={q.data} base={bl.baseDrawingVersion} onClose={() => setNewCk(false)} />}
      </div>
    </Shell>
  );
}

function BaselineSeal({ status }: { status: string }) {
  if (status === "已签认") return <Seal kind="pass">已签认</Seal>;
  if (status === "待签认" || status === "待重签") return <Seal kind="pend">{status}</Seal>;
  if (status === "已退回") return <span className="tag bad">已退回</span>;
  return <span className="tag">草稿</span>;
}

function ckText(k: Cp, added: boolean) {
  const parts = [k.isConcealed ? "隐蔽" : "非隐蔽"];
  if (k.status === "未核对") parts.push("待质检核对");
  else if (k.latestCheck) parts.push(`结论${k.latestCheck.conclusion}`, k.status === "待放行" && k.waitingHours != null ? `待放行已等 ${k.waitingHours} 小时` : k.status);
  else parts.push(k.status);
  if (k.isDraft) parts.push("编辑稿 · 随基线提交生效");
  else if (added) parts.push("已生效 · 已知会业主");
  return parts.join(" · ");
}

function CkSeal({ k }: { k: Cp }) {
  for (const l of ["放行后发现不一致", "不一致", "未放行先覆盖", "超时"]) if (k.status === l || k.labels.includes(l)) return <Seal kind="stop">{l}</Seal>;
  if (k.status === "待放行") return <Seal kind="pend">待放行</Seal>;
  if (k.labels.includes("不得覆盖")) return <Seal kind="stop">不得覆盖</Seal>;
  if (k.status === "已放行") return <Seal kind="pass">已放行</Seal>;
  return <span className="tag">{k.status}</span>;
}

function Progress({ pid, wi, canSave }: { pid: string; wi: Detail["workItem"]; canSave: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const onErr = useApiError();
  const [pct, setPct] = useState(String(wi.progress));
  const [actual, setActual] = useState(wi.actualFinish || "");
  const n = Math.min(100, Math.max(0, Number(pct) || 0));
  const m = useMutation({
    mutationFn: () => api(`/projects/${pid}/work-items/${wi.id}`, { method: "PATCH", body: { progress: n, actualFinish: actual || null } }),
    onSuccess: () => { toast(`进度已保存（完成度 ${n}%）`); qc.invalidateQueries({ queryKey: ["wi-detail", pid] }); qc.invalidateQueries({ queryKey: ["work-items", pid] }); },
    onError: onErr,
  });
  return (
    <section className="card" aria-labelledby="hProg">
      <div className="card-hd"><h2 id="hProg">进度</h2></div>
      <div className="card-bd">
        <div className="prog">
          <Field label="完成度（%）"><input className="input num" type="number" min={0} max={100} value={pct} disabled={!canSave} onChange={(e) => setPct(e.target.value)} /></Field>
          <Field label="实际完成日期"><input className="input" type="date" value={actual} disabled={!canSave} onChange={(e) => setActual(e.target.value)} /></Field>
        </div>
        <div className="pbar" style={{ margin: "var(--space-3) 0" }} aria-hidden="true"><i style={{ width: `${n}%` }} /></div>
        {canSave && <button type="button" className="btn" disabled={m.isPending} onClick={() => m.mutate()}>保存进度</button>}
      </div>
    </section>
  );
}

function Files({ pid, d, canUpload, meId }: { pid: string; d: Detail; canUpload: boolean; meId?: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ ok: number; rej: string[] } | null>(null);
  const [showVoid, setShowVoid] = useState(false);
  const [big, setBig] = useState<Attachment | null>(null);
  const [voiding, setVoiding] = useState<Attachment | null>(null);
  const refused = (a: Attachment, label?: string) => toast(`「${a.name}」被${label || a.refs[0]?.label}引用，不能作废`);
  const voidM = useMutation({
    mutationFn: (a: Attachment) => api(`/projects/${pid}/attachments/${a.attachmentId}/void`, { body: {}, headers: { "Idempotency-Key": idemKey() } }),
    onSuccess: () => { toast("已作废"); setVoiding(null); qc.invalidateQueries({ queryKey: ["wi-detail", pid] }); },
    onError: (e, a) => {
      setVoiding(null);
      const refs = (e as ApiError).details?.refs as { label: string }[] | undefined;
      if (refs?.length) refused(a, refs[0].label); else toast((e as Error).message);
    },
  });
  const upload = async (list: FileList | null) => {
    if (!list?.length) return;
    setBusy(true);
    let ok = 0;
    const rej: string[] = [];
    for (const f of Array.from(list)) {
      const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
      if (!ATTACH_EXT.includes(ext)) { rej.push(`${f.name}：格式不支持，未上传`); continue; }
      if (f.size > MAX) { rej.push(`${f.name}：超过 50MB，未上传`); continue; }
      const form = new FormData();
      form.append("file", f);
      try { await api(`/projects/${pid}/work-items/${d.workItem.id}/attachments`, { form }); ok += 1; } catch (e) { rej.push((e as Error).message || `${f.name}：上传失败，请重试`); }
    }
    setRes({ ok, rej });
    setBusy(false);
    qc.invalidateQueries({ queryKey: ["wi-detail", pid] });
  };
  const list = d.attachments.filter((a) => showVoid || !a.isVoided);
  return (
    <section className="card" aria-labelledby="hFiles" id="files">
      <div className="card-hd"><h2 id="hFiles">资料</h2><span className="spacer" />
        {canUpload && <label className="btn upbtn"><Icon name="upload" />{busy ? "上传中…" : "上传"}<input type="file" multiple disabled={busy} accept={ATTACH_EXT.join(",")} onChange={(e) => { upload(e.target.files); e.target.value = ""; }} /></label>}
      </div>
      <div className="card-bd">
        {res && <>{res.ok > 0 && <p className="upok">已上传 {res.ok} 个文件</p>}{res.rej.length > 0 && <div className="uprej" role="alert">{res.rej.map((r) => <div key={r}>{r}</div>)}</div>}</>}
        <div className="flist">
          {!list.length ? <p className="hint">还没有资料。</p> : list.map((a) => (
            <div key={a.attachmentId} className={`frow${a.isVoided ? " void" : ""}`}>
              {a.isImage && a.thumbUrl ? <button type="button" className="fi" aria-label={`放大 ${a.name}`} onClick={() => setBig(a)}><img src={a.thumbUrl} alt="" /></button>
                : <a className="fi" href={a.url} target="_blank" rel="noreferrer" aria-label={`打开 ${a.name}`}><Icon name="doc" /></a>}
              <div className="fn"><b>{a.name}</b>
                <span>{a.uploaderName} · {fmtTime(a.uploadedAt)} · {fileSize(a.size)}{a.refs.length ? ` · 被${a.refs.map((r) => r.label).join("、")}引用` : ""}{a.isVoided ? ` · ${a.voidedBy} 于 ${fmtTime(a.voidedAt)} 作废` : ""}</span></div>
              <div className="fa">
                <a className="btn sm" href={a.url} download={a.name}>下载</a>
                {!a.isVoided && a.uploaderId === meId && <button type="button" className="btn sm danger" onClick={() => (a.refs.length ? refused(a) : setVoiding(a))}>作废</button>}
              </div>
            </div>
          ))}
        </div>
        <label className="rad" style={{ marginTop: "var(--space-2)", fontSize: "var(--text-sm)" }}><input type="checkbox" checked={showVoid} onChange={(e) => setShowVoid(e.target.checked)} />显示已作废（{d.voidedCount}）</label>
        <p className="hint" style={{ fontSize: "var(--text-xs)" }}>图片、PDF、Word、Excel，单个不超过 50MB，可一次选择多个。</p>
      </div>
      {big && <Modal title={big.name} onClose={() => setBig(null)}><img className="bigph" src={big.url} alt={big.name} /></Modal>}
      {voiding && <ConfirmDialog cancelText="返回修改" title="作废资料" danger confirmText="确认作废" busy={voidM.isPending} onClose={() => setVoiding(null)} onConfirm={() => voidM.mutate(voiding)}
        summary={[["文件", `${voiding.name} · ${fileSize(voiding.size)}`], ["上传", `${voiding.uploaderName} · ${fmtTime(voiding.uploadedAt)}`], ["作废后", "从默认列表隐藏，记录作废人与时间，文件不会被物理删除"]]} />}
    </section>
  );
}

function EditDialog({ pid, d, cps, canSubmit, onClose }: { pid: string; d: Detail; cps: Cp[]; canSubmit: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { workItem: wi, baseline: bl } = d;
  const resign = bl.status === "待重签";
  const sets = useQuery({ queryKey: ["drawing-sets", pid], queryFn: () => api<{ items: DrawingSet[] }>(`/projects/${pid}/drawing-sets`) });
  const versions = useMemo(() => (sets.data?.items || []).flatMap((s) => s.versions), [sets.data]);
  const [f, setF] = useState({
    drawingVersionId: resign ? "" : String(wi.drawingVersion?.id ?? ""), description: wi.description, acceptanceCriteria: wi.acceptanceCriteria,
    cost: wi.cost ?? "", plannedFinish: wi.plannedFinish ?? "", qcUserId: String(wi.qcUserId ?? ""),
  });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [formErr, setFormErr] = useState("");
  const set = (k: keyof typeof f, v: string) => { setF((x) => ({ ...x, [k]: v })); setErrs((e) => ({ ...e, [k]: "" })); };
  const pickVersion = (id: string) => {
    const v = versions.find((x) => String(x.id) === id);
    if (v && v.status !== "已签认") { setErrs((e) => ({ ...e, drawingVersionId: "该版本尚未签认" })); setF((x) => ({ ...x, drawingVersionId: "" })); return; }
    set("drawingVersionId", id);
  };
  const body = () => ({ drawingVersionId: f.drawingVersionId ? Number(f.drawingVersionId) : null, description: f.description, acceptanceCriteria: f.acceptanceCriteria,
    cost: f.cost === "" ? null : f.cost, plannedFinish: f.plannedFinish || null, qcUserId: f.qcUserId ? Number(f.qcUserId) : null });
  const fail = (e: unknown) => { const ae = e as ApiError; setErrs(ae.fieldMap ? ae.fieldMap() : {}); setFormErr(ae.message); };
  const submit = useMutation({
    mutationFn: () => api(`/projects/${pid}/work-items/${wi.id}/baseline/submit`, { body: body() }),
    onSuccess: () => { toast(resign ? "已提交，等待业主重签" : "已提交，等待业主签认"); qc.invalidateQueries({ queryKey: ["wi-detail", pid] }); qc.invalidateQueries({ queryKey: ["wi-checkpoints", pid] }); qc.invalidateQueries({ queryKey: ["baselines-pending", pid] }); onClose(); },
    onError: fail,
  });
  const save = useMutation({
    mutationFn: () => api(`/projects/${pid}/work-items/${wi.id}`, { method: "PATCH", body: body() }),
    onSuccess: () => { toast("基线草稿已保存"); qc.invalidateQueries({ queryKey: ["wi-detail", pid] }); onClose(); },
    onError: fail,
  });
  const vLabel = (v: Version) => `${v.setName} V${v.versionNo} · ${v.status === "已签认" ? (v.isCurrentSigned ? "已签认（当前签认版）" : resign && bl.baseDrawingVersion?.id === v.id ? "已签认（原签认版）" : "已签认") : "待业主签认"}`;
  const title = resign ? "更新基线并提交重签" : bl.status === "已退回" ? "修改基线并重新提交" : "编辑基线";
  return (
    <Modal title={title} wide onClose={onClose} footer={<>
      <button type="button" className="btn" onClick={onClose}>取消</button>
      {!resign && <button type="button" className="btn" disabled={save.isPending} onClick={() => save.mutate()}>保存草稿</button>}
      {canSubmit && <button type="button" className="btn primary" disabled={submit.isPending} onClick={() => { setFormErr(""); submit.mutate(); }}>{submit.isPending ? "提交中…" : "提交业主签认"}</button>}
    </>}>
      {formErr && <div className="formerr" role="alert">{formErr}</div>}
      {resign && <p className="hint">已预填当前生效内容；图纸版本需重新选择已签认的新版本。</p>}
      <div className="fgrid">
        <Field label="签认版图纸分册与版本" required full error={errs.drawingVersionId}>
          <select className="select" value={f.drawingVersionId} onChange={(e) => pickVersion(e.target.value)}>
            <option value="">请选择</option>
            {versions.map((v) => <option key={v.id} value={v.id}>{vLabel(v)}</option>)}
          </select>
        </Field>
        <Field label="工作说明" required full error={errs.description}><textarea className="textarea" rows={2} value={f.description} onChange={(e) => set("description", e.target.value)} /></Field>
        <Field label="验收标准" required full error={errs.acceptanceCriteria}><textarea className="textarea" rows={2} value={f.acceptanceCriteria} onChange={(e) => set("acceptanceCriteria", e.target.value)} /></Field>
        <Field label="费用（元）" required error={errs.cost}><input className="input num" type="number" min={0} step="0.01" value={f.cost} onChange={(e) => set("cost", e.target.value)} /></Field>
        <Field label="计划完成日期" required error={errs.plannedFinish}><input className="input" type="date" value={f.plannedFinish} onChange={(e) => set("plannedFinish", e.target.value)} /></Field>
        <Field label="质检人" required error={errs.qcUserId}>
          <select className="select" value={f.qcUserId} onChange={(e) => set("qcUserId", e.target.value)}>
            <option value="">请选择</option>{d.qcCandidates.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </Field>
        <Field label="检查点（至少 1 个）" required full error={errs.checkpoints}>
          {cps.length ? <ul className="ckdraft">{cps.map((k) => <li key={k.id}><span className="idc">{k.code}</span>{k.point} · {k.isConcealed ? "隐蔽" : "非隐蔽"}</li>)}</ul>
            : <span className="hint">还没有检查点，请先关闭本窗口，在「检查点」卡片中新建。</span>}
        </Field>
      </div>
    </Modal>
  );
}

function NewCheckpoint({ pid, d, base, onClose }: { pid: string; d: Detail; base: VersionBrief; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const st = d.baseline.status;
  const effective = st === "已签认" || st === "待重签";
  const v = useQuery({ queryKey: ["drawing-version", pid, String(base.id)], queryFn: () => api<Version>(`/projects/${pid}/drawing-versions/${base.id}`) });
  const sug = useQuery({ queryKey: ["exp-suggest", pid, d.workItem.phaseId], queryFn: () => api<{ phaseName: string; items: Suggestion[] }>(`/projects/${pid}/experience/suggestions?phaseId=${d.workItem.phaseId}`) });
  const [point, setPoint] = useState("");
  const [hid, setHid] = useState<"" | "是" | "否">("");
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [pageNo, setPageNo] = useState(1);
  const [err, setErr] = useState<string[]>([]);
  const [confirm, setConfirm] = useState(false);
  const page = v.data?.pages?.find((p) => p.pageNo === pageNo) || v.data?.pages?.[0];
  const m = useMutation({
    mutationFn: () => api<{ code: string }>(`/projects/${pid}/work-items/${d.workItem.id}/checkpoints`, { body: { point: point.trim(), isConcealed: hid === "是", x: pos!.x, y: pos!.y, pageNo: page?.pageNo || 1 }, headers: { "Idempotency-Key": idemKey() } }),
    onSuccess: (r) => {
      toast(effective ? `检查点 ${r.code} 已生效，已通知业主` : `检查点 ${r.code} 已加入基线编辑稿`);
      qc.invalidateQueries({ queryKey: ["wi-detail", pid] });
      qc.invalidateQueries({ queryKey: ["wi-checkpoints", pid] });
      onClose();
    },
    onError: (e) => { setConfirm(false); setErr([(e as Error).message]); },
  });
  const save = () => {
    const e: string[] = [];
    if (!point.trim()) e.push("检查要点");
    if (!hid) e.push("是否隐蔽");
    if (!pos) e.push("图上位置");
    setErr(e.length ? [`请补充：${e.join("、")}`] : []);
    if (e.length) return;
    if (effective) setConfirm(true); else m.mutate();
  };
  const addExp = (t: string) => setPoint((p) => (p.trim() ? `${p.trim()}；${t}` : t));
  const baseText = `底图：${base.setName} V${base.versionNo}（基线引用的签认版）`;
  return (
    <>
      <Modal title="新建检查点" wide onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>取消</button><button type="button" className="btn primary" disabled={m.isPending} onClick={save}>保存检查点</button></>}>
        {err.length > 0 && <div className="formerr" role="alert">{err.join("；")}</div>}
        <Field label="检查要点" required><textarea className="textarea" rows={2} value={point} placeholder="例如：南墙新增插座底盒与原底盒水平间距、标高一致" onChange={(e) => setPoint(e.target.value)} /></Field>
        <Field label="是否隐蔽" required>
          <div className="rad" role="radiogroup">
            <label><input type="radio" name="hid" checked={hid === "是"} onChange={() => setHid("是")} />是（未放行不得覆盖）</label>
            <label><input type="radio" name="hid" checked={hid === "否"} onChange={() => setHid("否")} />否</label>
          </div>
        </Field>
        <Field label="在图纸上点选位置" required>
          <span className="hint" style={{ fontSize: "var(--text-xs)" }}>{baseText}{pos ? ` · 坐标 (${pos.x.toFixed(3)}, ${pos.y.toFixed(3)})` : ""} · {effective ? "基线已签认，新检查点保存后立即生效，不改变签认状态，并通知业主；已有检查点仍不可修改或删除" : "新检查点进入基线编辑稿，随基线一起提交签认"}</span>
          {(v.data?.pages?.length || 0) > 1 && <div className="chips">{v.data!.pages!.map((p) => <button key={p.pageNo} type="button" className={`chip${p.pageNo === page?.pageNo ? " on" : ""}`} onClick={() => { setPageNo(p.pageNo); setPos(null); }}>第 {p.pageNo} 页</button>)}</div>}
          <div className="pickmap">{v.isLoading ? <div className="skeleton" style={{ height: 200 }} /> : <DrawingStage className="pickwrap" page={page} onPick={(x, y) => setPos({ x, y })} picked={pos} />}</div>
        </Field>
        {!!d.workItem.checkpointHints?.length && (
          <Field label="公司模板检查点">
            <ul className="expl">{d.workItem.checkpointHints.map((h, i) => <li key={i}><span className="tag">{h.isConcealed ? "隐蔽" : "非隐蔽"}</span><p>{h.point}</p><button type="button" className="btn sm" onClick={() => { setPoint(h.point); setHid(h.isConcealed ? "是" : "否"); }}>填入</button></li>)}</ul>
          </Field>
        )}
        <Field label={`${sug.data?.phaseName || d.workItem.phaseName}工段经验推荐（已审核）`}>
          {sug.isLoading ? <div className="skeleton" /> : sug.error ? <span className="hint">经验推荐暂不可用</span> : !sug.data?.items.length ? <span className="hint">本工段还没有已审核的经验条目。</span> : (
            <ul className="expl">{sug.data.items.map((s) => <li key={s.id}><span className={`tag ${EXP_TAG[s.status] ?? ""}`}>{s.status}</span><p>{s.checkPoint}</p><button type="button" className="btn sm" onClick={() => addExp(s.checkPoint)}>加入要点</button></li>)}</ul>
          )}
        </Field>
      </Modal>
      {confirm && pos && (
        <ConfirmDialog cancelText="返回修改" title="确认新增检查点" confirmText="确认新增" busy={m.isPending} onClose={() => setConfirm(false)} onConfirm={() => m.mutate()}
          summary={[["工作项", d.workItem.name], ["检查要点", point.trim()], ["是否隐蔽", hid === "是" ? "是（未放行不得覆盖）" : "否"],
            ["底图与坐标", `${base.setName} V${base.versionNo} · 第 ${page?.pageNo || 1} 页 · (${pos.x.toFixed(3)}, ${pos.y.toFixed(3)})`],
            ["生效方式", `立即生效，基线保持「${st}」`], ["知会对象", `业主 ${d.ownerNames.join("、") || "—"}`]]}
          warn="保存后不可修改或删除。" />
      )}
    </>
  );
}
