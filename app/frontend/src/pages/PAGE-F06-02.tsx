// PAGE-F06-02 · 检查点详情：图上钉点、对图核对（本机草稿、逐张上传与重传）、放行、标记已覆盖、修正发现时点
import { bj } from "../time";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { del, get, set } from "idb-keyval";
import { api, ApiError, idemKey, uploadFile, type UploadedFile } from "../api";
import { Shell } from "../layout/Shell";
import { useProject, useSession } from "../session";
import { ConfirmDialog, ErrorState, Field, Icon, Loading, Modal, Seal, useToast } from "../ui";
import "../styles/pages/PAGE-F06-02.css";

type SealKind = "pass" | "stop" | "pend" | "proxy";
type UserBrief = { id: number; name: string } | null;
type Drawing = {
  id: number; setId: number; setName: string; versionNo: number; label: string; file: UploadedFile | null; isCurrentSigned: boolean;
  pages: { pageNo: number; imageUrl: string; width: number; height: number }[];
};
type CheckRec = {
  id: number; no: number; conclusion: string; checker: UserBrief; checkedAt: string; drawingVersionId: number; drawingLabel: string;
  wasLatestSigned: boolean; wasCovered: boolean; note: string; photos: { id: number; file: UploadedFile; pinX: number; pinY: number }[];
  changeOrder: { id: number; code: string; title: string; status: string } | null; discoveryPhase: string; inferredDiscoveryPhase: string;
  inferBasis?: string; corrections: { id: number; before: string; after: string; reason: string; actor: UserBrief; at: string }[];
  issue: { id: number; code: string; status: string; description: string } | null;
};
type Detail = {
  id: number; code: string; point: string; isConcealed: boolean; status: string; isDraft: boolean; labels: string[]; seal: string; sealKind: SealKind | null;
  pageNo: number; x: number; y: number;
  workItem: { id: number; name: string; phaseName: string; floorName: string; roomName: string; qcUser: UserBrief; baselineStatus: string };
  pinDrawing: Drawing | null; baseDrawing: Drawing | null;
  resign: { newVersionId: number; newLabel: string; oldLabel: string; oldVersionNo: number; signedOn: string } | null;
  latestCheck: { id: number; no: number; conclusion: string; checkedAt: string; checker: UserBrief } | null; nextCheckNo: number;
  checks: CheckRec[]; releases: { id: number; releaser: UserBrief; isProxy: boolean; releasedAt: string; basisCheckId: number; basisNo: number }[];
  coverEvents: { id: number; source: string; recorder: UserBrief; at: string; wasUnreleased: boolean }[];
  coveredAt: string | null; unreleasedCover: boolean; waitingHours: number | null; releaseTimeoutHours: number; handoverDate: string; handoverKind: string;
};
type ChangeOrderOpt = { id: number; code: string; title: string; status: string };

type PhotoSt = "up" | "ok" | "fail";
type Photo = { key: string; name: string; blob: Blob; status: PhotoSt; fileId?: number; url: string; err?: string };
type Draft = { photos: { key: string; name: string; blob: Blob; status: PhotoSt; fileId?: number }[]; conclusion: string; cover: string; changeOrderId: string; savedAt: string };

const t16 = (s?: string | null) => (s ? s.slice(0, 16).replace("T", " ") : "");
const PHASES = ["覆盖前", "覆盖后", "交房后"];
const concTag = (c: string) => (c === "一致" ? "ok" : c === "不一致" ? "bad" : "warn");

function PlanMap({ d, drawing }: { d: Detail; drawing: Drawing | null }) {
  const { pid } = useParams();
  const remote = useQuery({
    queryKey: ["drawing-version", pid, drawing?.id],
    queryFn: () => api<{ pages?: { pageNo: number; imageUrl: string; width: number; height: number }[] }>(`/projects/${pid}/drawing-versions/${drawing!.id}`),
    enabled: !!drawing, retry: false,
  });
  const pages = remote.data?.pages?.length ? remote.data.pages : drawing?.pages || [];
  const page = pages.find((p) => p.pageNo === d.pageNo) || pages[0];
  const img = page?.imageUrl || (drawing?.file?.isImage ? drawing.file.url : null);
  const w = page?.width || 800, h = page?.height || 520;
  const cls = d.sealKind === "pass" ? "s-pass" : d.sealKind === "proxy" ? "s-proxy" : d.status === "待放行" ? "s-pend" : d.status === "未核对" ? "s-none" : "s-stop";
  return (
    <>
      <div className="mapbox">
        {img ? <img src={img} alt={`${drawing?.label || "图纸"}，${d.code} 钉点`} /> : (
          <svg className="ph-plan" viewBox="0 0 800 520" role="img" aria-label={`${drawing?.label || "图纸"}（底图暂不可预览），${d.code} 钉点`}>
            <rect className="plan-bg" width="800" height="520" />
            <path className="plan-grid" d={Array.from({ length: 15 }, (_, i) => `M${(i + 1) * 50} 0 V520`).join(" ") + " " + Array.from({ length: 10 }, (_, i) => `M0 ${(i + 1) * 50} H800`).join(" ")} />
            <text className="plan-txt" x="400" y="40">{drawing?.label || "图纸"} · 底图暂不可预览，请在查看器中打开</text>
          </svg>
        )}
        <span className={`pinmark ${cls}`} style={{ left: `${d.x * 100}%`, top: `${d.y * 100}%` }} role="img" aria-label={`${d.code} ${d.point}，当前检查点`}>{d.code.slice(3)}</span>
      </div>
      <div className="maphint"><Icon name="map" /><span>底图：{drawing?.label || "—"}（本工作项基线引用的签认版）· 第 {d.pageNo} 页 · 坐标 ({Math.round(d.x * w)}, {Math.round(d.y * h)})</span></div>
    </>
  );
}

export default function CheckpointDetail() {
  const { pid, cid } = useParams();
  const { me } = useSession();
  const { can, has } = useProject(pid);
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["checkpoint", pid, cid], queryFn: () => api<Detail>(`/projects/${pid}/checkpoints/${cid}`) });
  const canCheck = can("checkpoint.check");
  const canRelease = can("checkpoint.release");
  const canCover = can("checkpoint.mark_covered");
  const canCorrect = can("discovery.correct");
  const isProxy = has("owner_agent") && !has("owner");
  const cos = useQuery({
    queryKey: ["change-orders", pid, "已生效"],
    queryFn: () => api<{ items: ChangeOrderOpt[] }>(`/projects/${pid}/change-orders?status=${encodeURIComponent("已生效")}`),
    enabled: canCheck, retry: false,
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["checkpoint", pid, cid] });
    qc.invalidateQueries({ queryKey: ["checkpoints", pid] });
    qc.invalidateQueries({ queryKey: ["todo-count"] });
  };

  // —— 核对表单与本机草稿（DEC-204）——
  const draftKey = `jh-check-draft:${pid}:${cid}:${me?.id ?? 0}`;
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [conclusion, setConclusion] = useState("");
  const [cover, setCover] = useState("");
  const [coId, setCoId] = useState("");
  const [savedAt, setSavedAt] = useState("");
  const [restored, setRestored] = useState(false);
  const [formErrs, setFormErrs] = useState<string[]>([]);
  const [invalid, setInvalid] = useState<Record<string, boolean>>({});
  const photosRef = useRef<Photo[]>([]);
  photosRef.current = photos;

  useEffect(() => () => photosRef.current.forEach((p) => URL.revokeObjectURL(p.url)), []);

  useEffect(() => {
    if (!canCheck || !me || restored) return;
    get<Draft>(draftKey).then((dr) => {
      if (dr) {
        setPhotos(dr.photos.map((p) => ({ ...p, status: p.status === "ok" && p.fileId ? "ok" : "fail", url: URL.createObjectURL(p.blob) })));
        setConclusion(dr.conclusion); setCover(dr.cover); setCoId(dr.changeOrderId); setSavedAt(dr.savedAt);
      }
    }).catch(() => undefined).finally(() => setRestored(true));
  }, [canCheck, me, draftKey, restored]);

  useEffect(() => {
    if (!restored) return;
    if (!photos.length && !conclusion && !cover && !coId) return;
    const stamp = bj().format("YYYY-MM-DD HH:mm");
    const dr: Draft = { photos: photos.map(({ key, name, blob, status, fileId }) => ({ key, name, blob, status, fileId })), conclusion, cover, changeOrderId: coId, savedAt: stamp };
    set(draftKey, dr).then(() => setSavedAt(stamp)).catch(() => undefined);
  }, [photos, conclusion, cover, coId, restored, draftKey]);

  const resetForm = useCallback(() => {
    photosRef.current.forEach((p) => URL.revokeObjectURL(p.url));
    setPhotos([]); setConclusion(""); setCover(""); setCoId(""); setSavedAt(""); setFormErrs([]); setInvalid({});
    del(draftKey).catch(() => undefined);
  }, [draftKey]);

  const doUpload = useCallback(async (key: string, blob: Blob, name: string) => {
    setPhotos((ps) => ps.map((p) => (p.key === key ? { ...p, status: "up", err: undefined } : p)));
    try {
      const f = await uploadFile(pid!, new File([blob], name, { type: blob.type || "image/jpeg" }));
      setPhotos((ps) => ps.map((p) => (p.key === key ? { ...p, status: "ok", fileId: f.id } : p)));
    } catch (e) {
      setPhotos((ps) => ps.map((p) => (p.key === key ? { ...p, status: "fail", err: (e as ApiError)?.message } : p)));
    }
  }, [pid]);

  const addFiles = (list: FileList | null) => {
    if (!list?.length) return;
    setInvalid((v) => ({ ...v, photos: false }));
    const added = Array.from(list).map((f) => ({ key: idemKey(), name: f.name || "现场照片.jpg", blob: f as Blob, status: "up" as PhotoSt, url: URL.createObjectURL(f) }));
    setPhotos((ps) => [...ps, ...added]);
    added.forEach((p) => doUpload(p.key, p.blob, p.name));
  };
  const removePhoto = (key: string) => setPhotos((ps) => {
    const p = ps.find((x) => x.key === key);
    if (p) URL.revokeObjectURL(p.url);
    return ps.filter((x) => x.key !== key);
  });

  const [confirm, setConfirm] = useState<null | "check" | "release" | "cover" | "fix">(null);
  const [stamped, setStamped] = useState(false);
  const [fixFor, setFixFor] = useState<CheckRec | null>(null);
  const [fixVal, setFixVal] = useState("");
  const [fixReason, setFixReason] = useState("");
  const [fixErr, setFixErr] = useState("");

  const checkMut = useMutation({
    mutationFn: () => api<{ check: CheckRec; status: string; issue: { id: number; code: string } | null }>(`/projects/${pid}/checkpoints/${cid}/checks`, {
      body: { conclusion, wasCovered: cover === "已被覆盖", changeOrderId: conclusion === "已变更" ? Number(coId) : null, photos: photos.map((p) => ({ fileId: p.fileId })) },
    }),
    onSuccess: (r) => {
      setConfirm(null); resetForm(); refresh();
      toast(r.issue ? `核对已保存，已生成问题 ${r.issue.code}` : `核对 #${r.check.no} 已保存`);
    },
    onError: (e) => { setConfirm(null); setFormErrs([(e as ApiError).message || "提交失败"]); },
  });
  const releaseMut = useMutation({
    mutationFn: () => api(`/projects/${pid}/checkpoints/${cid}/release`, { body: {}, headers: { "Idempotency-Key": idemKey() } }),
    onSuccess: () => { setConfirm(null); setStamped(true); refresh(); toast("已放行，记录已生成"); },
    onError: (e) => { setConfirm(null); refresh(); toast((e as ApiError).message || "放行失败"); },
  });
  const coverMut = useMutation({
    mutationFn: () => api<{ coverEvent: { wasUnreleased: boolean } }>(`/projects/${pid}/checkpoints/${cid}/cover`, { body: {}, headers: { "Idempotency-Key": idemKey() } }),
    onSuccess: (r) => { setConfirm(null); refresh(); toast(r.coverEvent.wasUnreleased ? "已记录覆盖，并生成「未放行先覆盖」事件" : "已标记覆盖"); },
    onError: (e) => { setConfirm(null); refresh(); toast((e as ApiError).message || "操作失败"); },
  });
  const fixMut = useMutation({
    mutationFn: () => api(`/projects/${pid}/checks/${fixFor!.id}/discovery-corrections`, { body: { after: fixVal, reason: fixReason.trim() } }),
    onSuccess: () => { setConfirm(null); setFixFor(null); setFixReason(""); refresh(); toast("发现时点已修正并留痕"); },
    onError: (e) => { setConfirm(null); setFixErr((e as ApiError).message || "修正失败"); },
  });

  if (q.error instanceof ApiError && (q.error.status === 403)) return <Navigate to="/forbidden" replace />;
  const d = q.data;
  if (!d) {
    return <Shell title="检查点详情">{q.error ? <ErrorState error={q.error} retry={() => q.refetch()} /> : <Loading rows={6} />}</Shell>;
  }

  const wi = d.workItem;
  const released = d.status === "已放行";
  const lastRel = d.releases[d.releases.length - 1];
  const lc = d.latestCheck;
  const lcFull = d.checks.find((c) => c.id === lc?.id);
  const covered = !!d.coveredAt;
  const timeout = d.labels.includes("超时");
  const placeTxt = [wi.floorName, wi.roomName].filter(Boolean).join(" · ");
  const failed = photos.filter((p) => p.status !== "ok").length;
  const coOpts = cos.data?.items || [];
  const relSeal: [SealKind, string] = released ? (lastRel?.isProxy ? ["proxy", "代理放行"] : ["pass", "已放行"])
    : d.status === "待放行" ? (timeout ? ["stop", "超时"] : ["pend", "待放行"]) : ["stop", lc?.conclusion || "未核对"];
  // 检查点卡印章（原型 headSeal）：超时只在放行卡体现，检查点卡突出「不得覆盖」
  const headSeal: [SealKind | null, string] = d.status === "放行后发现不一致" ? ["stop", "放行后发现不一致"]
    : d.status === "不一致" ? ["stop", "不一致"]
    : d.labels.includes("未放行先覆盖") ? ["stop", "未放行先覆盖"]
    : !released && d.isConcealed && !covered ? ["stop", "不得覆盖"]
    : released ? relSeal
    : d.status === "待放行" ? ["pend", "待放行"] : [null, d.seal];

  const submitCheck = () => {
    const errs: string[] = []; const inv: Record<string, boolean> = {};
    if (!photos.length) { errs.push("至少上传 1 张现场照片"); inv.photos = true; }
    else if (failed) { errs.push(`还有 ${failed} 张照片未上传成功，请重传后再提交（已保存在本机草稿）`); inv.photos = true; }
    if (!conclusion) { errs.push("请选择结论"); inv.conclusion = true; }
    if (conclusion === "已变更" && !coId) { errs.push("请关联已生效的变更单"); inv.co = true; }
    if (!cover) { errs.push("请选择核对时是否已被覆盖"); inv.cover = true; }
    setFormErrs(errs); setInvalid(inv);
    if (!errs.length) setConfirm("check");
  };
  const inferPhase = () => {
    const today = bj().format("YYYY-MM-DD");
    if (today >= d.handoverDate) return `系统推断为「交房后」（核对日期不早于${d.handoverKind}交房日期 ${d.handoverDate}）`;
    return `系统推断为「${cover === "已被覆盖" || covered ? "覆盖后" : "覆盖前"}」（核对日期早于${d.handoverKind}交房日期 ${d.handoverDate}）`;
  };
  const coLabel = coOpts.find((c) => String(c.id) === coId);

  type Hist = { at: string; key: string; node: ReactNode };
  const hist: Hist[] = [];
  d.checks.forEach((c) => hist.push({
    at: c.checkedAt, key: `c${c.id}`, node: (
      <article className="rec" key={`c${c.id}`}>
        <div className="rh"><b>核对 #{c.no}</b><span className={`tag ${concTag(c.conclusion)}`}>{c.conclusion}</span><span className="meta">{c.checker?.name} · {t16(c.checkedAt)}（服务器时间）</span></div>
        <dl className="kv">
          <dt>所用图纸</dt><dd>{c.drawingLabel}{!c.wasLatestSigned && "（核对时已有更新的签认版）"}</dd>
          <dt>覆盖状态</dt><dd>{c.wasCovered ? "已被覆盖" : "未覆盖"}</dd>
          <dt>照片</dt><dd>{c.photos.length} 张 · 钉在{placeTxt || "检查点位置"}</dd>
          {c.conclusion === "不一致" && <><dt>发现时点</dt><dd>{c.discoveryPhase}</dd></>}
          {c.issue && <><dt>生成问题</dt><dd><Link to={`/p/${pid}/issues`}>{c.issue.code} {c.note || d.point}</Link> · {c.issue.status}</dd></>}
          {c.changeOrder && <><dt>关联变更单</dt><dd><Link to={`/p/${pid}/changes/${c.changeOrder.id}`}>{c.changeOrder.code} {c.changeOrder.title}</Link> · {c.changeOrder.status}</dd></>}
        </dl>
        {!!c.photos.length && <div className="thumbs">{c.photos.map((p) => <a key={p.id} href={p.file.url} target="_blank" rel="noreferrer"><img src={p.file.thumbUrl || p.file.url} alt={`核对 #${c.no} 照片`} loading="lazy" /></a>)}</div>}
        {c.corrections.map((x) => <div className="fix" key={x.id}>修正：{x.before} → {x.after} · {x.actor?.name} · {t16(x.at)} · {x.reason}</div>)}
        {c.conclusion === "不一致" && canCorrect && (
          <div><button type="button" className="btn sm" onClick={() => { setFixFor(c); setFixVal(PHASES.find((p) => p !== c.discoveryPhase) || ""); setFixReason(""); setFixErr(""); }}><Icon name="doc" />修正发现时点</button></div>
        )}
      </article>
    ),
  }));
  d.releases.forEach((r) => hist.push({
    at: r.releasedAt, key: `r${r.id}`, node: (
      <article className="rec" key={`r${r.id}`}>
        <div className="rh"><b>放行</b><span className={`tag ${r.isProxy ? "brand" : "ok"}`}>{r.isProxy ? "代理放行" : "已放行"}</span><span className="meta">{r.releaser?.name} · {t16(r.releasedAt)}（服务器时间）</span></div>
        <div className="meta">依据核对 #{r.basisNo}</div>
      </article>
    ),
  }));
  d.coverEvents.forEach((e) => hist.push({
    at: e.at, key: `v${e.id}`, node: (
      <article className="rec event" key={`v${e.id}`}>
        <Icon name="alert" />
        <span><b>{e.wasUnreleased ? "未放行先覆盖" : "覆盖登记"}</b> · {e.recorder?.name}{e.source === "pm_mark" ? "标记已覆盖" : "核对时记录已被覆盖"} · {t16(e.at)}</span>
      </article>
    ),
  }));
  hist.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));

  return (
    <Shell
      title={`${d.code} ${d.point}`}
      sub={[wi.phaseName, wi.floorName, wi.roomName, d.isConcealed ? "隐蔽工序" : "非隐蔽", wi.qcUser ? `质检人 ${wi.qcUser.name}` : ""].filter(Boolean).join(" · ")}
      crumb={<><Link to={`/p/${pid}/checkpoints`}>检查点</Link><Icon name="right" /><Link to={`/p/${pid}/work-items/${wi.id}`}>{wi.name}</Link><Icon name="right" /><span>{d.code}</span></>}
    >
      <div className="ck-detail">
        {d.resign && (
          <div className="banner" role="note"><Icon name="alert" />
            <div><b>该工作项有新版图纸待重签。</b>{d.resign.newLabel} 已于 {d.resign.signedOn} 签认，本工作项基线尚未重签，核对仍以原签认版 <b>V{d.resign.oldVersionNo}</b> 为底图。</div>
            <Link className="btn sm act" to={`/p/${pid}/drawings/${d.resign.newVersionId}?workItem=${wi.id}&compare=${d.pinDrawing?.id ?? ""}`}>对比 V{d.resign.oldVersionNo} / {d.resign.newLabel.split(" ").pop()}</Link>
          </div>
        )}
        {d.isDraft && <div className="banner note" role="note"><Icon name="alert" /><div>该检查点在基线编辑稿中，随基线提交后生效。</div></div>}

        <div className="ck-grid">
          <div className="col">
            <section className="card ck-head o1" aria-labelledby="hHead">
              <div className="card-hd"><h2 id="hHead">检查点</h2><span className="spacer" />{headSeal[0] ? <Seal kind={headSeal[0]} just={stamped}>{headSeal[1]}</Seal> : <span className="tag">{headSeal[1]}</span>}</div>
              <div className="card-bd">
                <div className="lead"><p>{d.point}</p></div>
                <dl className="kv">
                  <dt>是否隐蔽</dt><dd>{d.isConcealed ? "是（未放行不得覆盖）" : "否"}</dd>
                  <dt>钉点图纸</dt><dd>{[d.pinDrawing?.label, placeTxt].filter(Boolean).join(" · ")}</dd>
                  <dt>当前结论</dt><dd>{lc ? `${lc.conclusion}（核对 #${lc.no} · ${t16(lc.checkedAt)}）` : "未核对"}</dd>
                  <dt>覆盖状态</dt><dd>{covered ? `已覆盖（${t16(d.coveredAt)}）` : "未覆盖"}</dd>
                  <dt>所属工作项</dt><dd><Link to={`/p/${pid}/work-items/${wi.id}`}>{wi.name}</Link></dd>
                </dl>
              </div>
            </section>

            <section className="card o3" aria-labelledby="hMap">
              <div className="card-hd"><h2 id="hMap">图上钉点</h2><span className="spacer" />{d.baseDrawing && <Link className="btn sm" to={`/p/${pid}/drawings/${d.baseDrawing.id}?workItem=${wi.id}`}><Icon name="map" />在查看器中打开</Link>}</div>
              <div className="card-bd"><PlanMap d={d} drawing={d.baseDrawing} /></div>
            </section>

            <section className="card o6" aria-labelledby="hHist">
              <div className="card-hd"><h2 id="hHist">核对与放行历史</h2><span className="spacer" /><span className="muted" style={{ fontSize: "var(--text-xs)" }}>只追加，不可修改</span></div>
              <div className="card-bd recs">{hist.length ? hist.map((h) => h.node) : <p className="muted">还没有核对记录</p>}</div>
            </section>
          </div>

          <div className="col">
            <section className="card o2" aria-labelledby="hRel">
              <div className="card-hd"><h2 id="hRel">业主放行</h2><span className="spacer" /><Seal kind={relSeal[0]} just={stamped && released}>{relSeal[1]}</Seal></div>
              <div className="card-bd">
                {d.status === "待放行" && lc && (
                  <>
                    <div className="wait"><Icon name="alert" /><span>待放行 · 已等 <b className="num">{d.waitingHours ?? 0}</b> 小时（项目时限 {d.releaseTimeoutHours} 小时；超时只提醒，不会自动放行）</span></div>
                    <div className="basis">依据 <b>核对 #{lc.no}</b> · {lc.checker?.name} · {t16(lc.checkedAt)} · 结论「{lc.conclusion}」· {lcFull?.photos.length ?? 0} 张照片</div>
                  </>
                )}
                {["未核对", "不一致", "放行后发现不一致"].includes(d.status) && (
                  <div className="blocked"><Icon name="alert" /><span>当前结论为「{lc?.conclusion || "未核对"}」，不能放行。质检复核为「一致」或「已变更」后才能放行。</span></div>
                )}
                {canRelease && d.status === "待放行" && (
                  <div>
                    <button type="button" className="btn primary block" onClick={() => setConfirm("release")}><Icon name="stamp" />放行</button>
                    {isProxy && <p className="fhint" style={{ marginTop: "var(--space-2)" }}>以业主代理人身份放行时，记录标注「代理放行」。</p>}
                  </div>
                )}
                {!canRelease && (has("owner_member")
                  ? <p className="fhint">业主方成员只能查看；被业主指定为业主代理人后才能放行。</p>
                  : <p className="fhint">只有业主或业主代理人可以放行。</p>)}
                {!!d.releases.length && (
                  <div style={{ marginTop: "var(--space-3)" }}>
                    {[...d.releases].reverse().map((r) => (
                      <div className="rel-rec" key={r.id}><Icon name="stamp" /><span><b>{r.releaser?.name}</b>{r.isProxy ? " · 代理放行" : ""} · {t16(r.releasedAt)} · 依据核对 #{r.basisNo}</span></div>
                    ))}
                  </div>
                )}
              </div>
            </section>

            {canCheck && (
              <section className="card o4" aria-labelledby="hForm">
                <div className="card-hd"><h2 id="hForm">对图核对 <span className="muted" style={{ fontSize: "var(--text-sm)", fontWeight: 400 }}>· 将追加为 #{d.nextCheckNo}</span></h2></div>
                <div className="card-bd form">
                  {savedAt && (
                    <div className="draft"><Icon name="check" /><span>已自动保存为本机草稿 · {savedAt}</span>
                      <button type="button" className="btn sm" onClick={() => { resetForm(); toast("已放弃本机草稿"); }}>放弃草稿</button></div>
                  )}
                  {!!formErrs.length && <div className="formerr" role="alert">无法提交：<ul className="err-list">{formErrs.map((x) => <li key={x}>{x}</li>)}</ul></div>}
                  <fieldset className={`seg${invalid.photos ? " invalid" : ""}`}>
                    <legend>现场照片 <span className="req">*</span> <span className="fhint">至少 1 张，全部上传成功后才能提交</span></legend>
                    <div className="photos">
                      {photos.map((p) => (
                        <div className="ptile" key={p.key}>
                          <img className="ph" src={p.url} alt={p.name} />
                          <button type="button" className="rm" aria-label={`移除 ${p.name}`} onClick={() => removePhoto(p.key)}><Icon name="close" /></button>
                          {p.status === "ok" ? <div className="pst ok"><Icon name="check" />已上传</div>
                            : p.status === "up" ? <div className="pst up"><span className="skeleton" style={{ flex: 1 }} />上传中</div>
                              : <div className="pst fail" title={p.err}><Icon name="alert" />上传失败<button type="button" className="btn sm retry" onClick={() => doUpload(p.key, p.blob, p.name)}><Icon name="upload" />重传</button></div>}
                        </div>
                      ))}
                      <label className="addtile"><Icon name="camera" />拍照<input type="file" accept="image/*" capture="environment" multiple onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} /></label>
                      <label className="addtile"><Icon name="folder" />相册<input type="file" accept="image/*" multiple onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} /></label>
                    </div>
                  </fieldset>
                  <p className="fhint"><Icon name="pin" /> 照片钉点：{placeTxt || "检查点位置"}（沿用检查点钉点，所用图纸 {d.baseDrawing?.label}）</p>
                  <fieldset className={`seg${invalid.conclusion ? " invalid" : ""}`}>
                    <legend>结论 <span className="req">*</span></legend>
                    <div className="opts">
                      {["一致", "不一致", "已变更"].map((c) => <label key={c}><input type="radio" name="conc" value={c} checked={conclusion === c} onChange={() => { setConclusion(c); setInvalid((v) => ({ ...v, conclusion: false })); }} /><span>{c}</span></label>)}
                    </div>
                  </fieldset>
                  {conclusion === "已变更" && (
                    <Field label="关联已生效的变更单" required error={invalid.co ? "请关联已生效的变更单" : undefined}>
                      <select className="select" value={coId} onChange={(e) => { setCoId(e.target.value); setInvalid((v) => ({ ...v, co: false })); }}>
                        <option value="">请选择</option>
                        {coOpts.map((c) => <option key={c.id} value={c.id}>{c.code} {c.title}</option>)}
                      </select>
                      <span className="fhint">{coOpts.length ? "只列出已由业主签认生效的变更单。" : "暂无已生效的变更单。"}</span>
                    </Field>
                  )}
                  <fieldset className={`seg${invalid.cover ? " invalid" : ""}`}>
                    <legend>核对时是否已被覆盖 <span className="req">*</span></legend>
                    <div className="opts two">
                      {["未覆盖", "已被覆盖"].map((c) => <label key={c}><input type="radio" name="cover" value={c} checked={cover === c} onChange={() => { setCover(c); setInvalid((v) => ({ ...v, cover: false })); }} /><span>{c}</span></label>)}
                    </div>
                    {cover === "已被覆盖" && d.isConcealed && !released && !covered && <p className="fwarn"><Icon name="alert" /><span>该检查点尚未放行，提交后将记录一条「未放行先覆盖」事件。</span></p>}
                  </fieldset>
                  <button type="button" className="btn primary block" onClick={submitCheck}><Icon name="check" />提交核对记录</button>
                </div>
              </section>
            )}

            {canCover && (
              <section className="card o5" aria-labelledby="hCover">
                <div className="card-hd"><h2 id="hCover">覆盖登记</h2></div>
                <div className="card-bd">
                  <div className="cover-row"><span>{covered ? `已覆盖（${t16(d.coveredAt)}，覆盖时间取最早一次记录）。` : "当前未覆盖。隐蔽工序被下一道工序盖住时，请标记已覆盖。"}</span></div>
                  {!covered && <button type="button" className="btn danger block" style={{ marginTop: "var(--space-3)" }} onClick={() => setConfirm("cover")}><Icon name="lock" />标记已覆盖</button>}
                </div>
              </section>
            )}
          </div>
        </div>
      </div>

      {confirm === "check" && (
        <ConfirmDialog cancelText="返回修改" title={`提交核对 #${d.nextCheckNo}`} confirmText="确认提交" busy={checkMut.isPending} onClose={() => setConfirm(null)} onConfirm={() => checkMut.mutate()}
          summary={[
            ["核对人", `${me?.name || ""}（质检）`], ["核对时间", "以服务器时间为准"],
            ["所用图纸", `${d.baseDrawing?.label || ""}${d.resign ? "（原签认版）" : ""}`],
            ["照片与钉点", `${photos.length} 张 · ${placeTxt || "检查点位置"}`],
            ["结论", conclusion + (conclusion === "已变更" && coLabel ? ` · 关联 ${coLabel.code}` : "")], ["覆盖状态", cover],
            ...(conclusion === "不一致" ? [["发现时点", inferPhase()], ["自动生成", "一条未闭环问题，带检查点、工作项、楼层、房间、照片和发现时点"]] as [string, string][] : []),
          ]}
          warn={conclusion === "不一致" && released ? "该检查点已放行，提交后状态变为「放行后发现不一致」，原放行记录保留。"
            : cover === "已被覆盖" && d.isConcealed && !released && !covered ? "该检查点尚未放行，将同时记录「未放行先覆盖」事件，计入指标并显示在业主待办中。" : undefined}>
          <p className="fhint">核对记录提交后不可修改；如需更正，请再次核对追加新记录。</p>
        </ConfirmDialog>
      )}
      {confirm === "release" && lc && (
        <ConfirmDialog cancelText="返回修改" title={`确认放行 ${d.code}`} confirmText="确认放行" busy={releaseMut.isPending} onClose={() => setConfirm(null)} onConfirm={() => releaseMut.mutate()}
          summary={[
            ["检查点", `${d.code} ${d.point}${placeTxt ? `（${placeTxt}）` : ""}`],
            ["依据核对", `#${lc.no} · ${lc.checker?.name} · 结论「${lc.conclusion}」`],
            ["放行人", `${me?.name || ""}${isProxy ? "（业主代理人，标注代理放行）" : "（业主）"}`],
            ["放行时间", "以服务器时间为准"],
          ]}>
          <p className="fhint">放行后记录不可撤回，下一道工序可以覆盖此处。</p>
        </ConfirmDialog>
      )}
      {confirm === "cover" && (
        <ConfirmDialog cancelText="返回修改" title={`标记 ${d.code} 已覆盖`} confirmText="确认已覆盖" danger busy={coverMut.isPending} onClose={() => setConfirm(null)} onConfirm={() => coverMut.mutate()}
          summary={[["检查点", `${d.code} ${d.point}`], ["放行状态", released ? `已放行（${lastRel?.releaser?.name || ""}）` : "未放行"], ["记录人", `${me?.name || ""}（项目经理）`], ["覆盖时间", "以服务器时间为准"]]}
          warn={d.isConcealed && !released ? "该检查点尚未放行。确认后将记录一条「未放行先覆盖」事件，计入指标并显示在业主待办中。" : undefined}>
          <p className="fhint">覆盖登记提交后不可撤回。</p>
        </ConfirmDialog>
      )}
      {fixFor && confirm !== "fix" && (
        <Modal title={`修正发现时点 · 核对 #${fixFor.no}`} onClose={() => setFixFor(null)} footer={<>
          <button type="button" className="btn" onClick={() => setFixFor(null)}>取消</button>
          <button type="button" className="btn primary" onClick={() => { if (!fixReason.trim()) { setFixErr("请填写修正理由"); return; } setFixErr(""); setConfirm("fix"); }}>下一步</button>
        </>}>
          <p className="fhint">系统推断：{fixFor.inferBasis} 修正后原值保留在历史中。</p>
          <Field label="修正为" required>
            <select className="select" value={fixVal} onChange={(e) => setFixVal(e.target.value)}>
              {PHASES.filter((p) => p !== fixFor.discoveryPhase).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </Field>
          <Field label="修正理由" required error={fixErr || undefined}>
            <textarea className="textarea" rows={3} value={fixReason} placeholder="例如：现场复看发现东墙已先行抹灰，核对时实际已被覆盖" onChange={(e) => setFixReason(e.target.value)} />
          </Field>
        </Modal>
      )}
      {confirm === "fix" && fixFor && (
        <ConfirmDialog cancelText="返回修改" title="确认修正发现时点" confirmText="确认修正" busy={fixMut.isPending} onClose={() => setConfirm(null)} onConfirm={() => fixMut.mutate()}
          summary={[["核对记录", `#${fixFor.no} · ${t16(fixFor.checkedAt)}`], ["修正前", `「${fixFor.discoveryPhase}」`], ["修正后", `「${fixVal}」`], ["修正人", me?.name || ""], ["理由", fixReason.trim()]]}>
          <p className="fhint">修正记录只追加，修正前的值保留可查。</p>
        </ConfirmDialog>
      )}
    </Shell>
  );
}
