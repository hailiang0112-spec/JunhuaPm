// PAGE-F04-01 · 图纸：分册列表与版本时间线、上传新版（设计经理）、签认版本（业主）。AC-F04-01~04、AC-F04-06、AC-F04-07
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Shell } from "../layout/Shell";
import { useProject, useSession } from "../session";
import { ConfirmDialog, Empty, ErrorState, Field, Icon, Loading, Modal, Seal, useApiError, useToast } from "../ui";
import { fileSize, fmtDate, fmtTime, IC, shaShort, Svg, type AffectedItem, type DrawingSet, type Version } from "./draw-kit";
import "../styles/pages/PAGE-F04-01.css";

const DRAW_EXT = [".pdf", ".jpg", ".jpeg", ".png"];
const CAD_EXT = [".dwg", ".dxf"];
const MAX = 50 * 1024 * 1024;
const ext = (n: string) => n.slice(n.lastIndexOf(".")).toLowerCase();

const BL_TAG: Record<string, [string, string]> = {
  已签认: ["ok", "基线已签认"], 待重签: ["warn", "待重签"], 待签认: ["", "基线待签认"], 草稿: ["", "基线草稿"], 已退回: ["bad", "基线已退回"],
};

type WorkItemRow = { id: number; name: string; floorName: string | null; roomName: string | null; baselineStatus: string; isDisabled: boolean };

export default function Drawings() {
  const { pid } = useParams();
  const [sp, setSp] = useSearchParams();
  const { project, can } = useProject(pid);
  const q = useQuery({ queryKey: ["drawing-sets", pid], queryFn: () => api<{ items: DrawingSet[] }>(`/projects/${pid}/drawing-sets`) });
  const [upload, setUpload] = useState(false);
  const [newSet, setNewSet] = useState(false);
  const [signing, setSigning] = useState<Version | null>(null);
  const [just, setJust] = useState<number | null>(null);

  const sets = q.data?.items || [];
  const volume = Number(sp.get("volume")) || (sets.find((s) => s.hasPending) || sets[0])?.id;
  const cur = sets.find((s) => s.id === volume) || sets[0];
  // 默认选中的分册写入地址栏，签认后「待签认」消失也不会跳到别的分册
  useEffect(() => { if (!sp.get("volume") && volume) setSp({ volume: String(volume) }, { replace: true }); }, [sp, volume, setSp]);

  return (
    <Shell title="图纸" sub={project ? `${project.name} · ${sets.length} 个分册 · 现场只按当前签认版施工` : undefined}>
      <div className="pg-f0401">
        {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} retry={() => q.refetch()} /> : !sets.length ? (
          <div className="card"><Empty text="还没有图纸分册。" action={can("drawing.upload") && <button type="button" className="btn" onClick={() => setNewSet(true)}><Icon name="plus" />新建分册</button>} /></div>
        ) : (
          <div className="dgrid">
            <section className="card" aria-label="图纸分册">
              <div className="vols" role="list">
                {sets.map((s) => (
                  <button key={s.id} type="button" role="listitem" className={`vol${s.id === cur?.id ? " on" : ""}`} aria-current={s.id === cur?.id || undefined}
                    onClick={() => setSp({ volume: String(s.id) }, { replace: true })}>
                    <span className="t">{s.name}{s.hasPending ? <Seal kind="pend">待签认</Seal> : s.currentSignedVersion ? <Seal kind="pass">已签认</Seal> : <span className="tag">暂无图纸</span>}</span>
                    <span className="m">{volMeta(s)}</span>
                  </button>
                ))}
              </div>
              {can("drawing.upload") && <div className="vols-ft"><button type="button" className="btn sm" onClick={() => setNewSet(true)}><Icon name="plus" />新建分册</button></div>}
            </section>
            {cur && <SetDetail s={cur} pid={pid!} canUpload={can("drawing.upload")} canSign={can("drawing.sign")} just={just} onUpload={() => setUpload(true)} onSign={setSigning} />}
          </div>
        )}
        {upload && cur && <UploadDialog pid={pid!} s={cur} onClose={() => setUpload(false)} />}
        {newSet && <NewSetDialog pid={pid!} onClose={() => setNewSet(false)} onDone={(id) => { setNewSet(false); setSp({ volume: String(id) }, { replace: true }); }} />}
        {signing && <SignDialog pid={pid!} v={signing} onClose={() => setSigning(null)} onDone={(id) => { setSigning(null); setJust(id); }} />}
      </div>
    </Shell>
  );
}

function volMeta(s: DrawingSet) {
  const c = s.currentSignedVersion;
  const pend = s.versions.filter((v) => v.status === "待业主签认");
  if (!s.versions.length) return "尚未上传版本";
  if (pend.length) return `${c ? `当前签认 V${c.versionNo}` : "尚无签认版"} · ${pend.map((v) => `V${v.versionNo}`).join("、")} 待业主签认`;
  return c ? `当前签认 V${c.versionNo} · ${fmtDate(c.signedAt)}` : "";
}

function SetDetail({ s, pid, canUpload, canSign, just, onUpload, onSign }: {
  s: DrawingSet; pid: string; canUpload: boolean; canSign: boolean; just: number | null; onUpload: () => void; onSign: (v: Version) => void;
}) {
  const c = s.currentSignedVersion;
  return (
    <section className="card" aria-labelledby="volH">
      <div className="card-hd vhead">
        <h2 id="volH">{s.name}</h2>
        <span className="info">{c ? `当前签认版 V${c.versionNo}（${fmtDate(c.signedAt)}）` : "尚无签认版"}</span>
        <span className="spacer" />
        {canUpload && <button type="button" className="btn" onClick={onUpload}><Icon name="upload" />{s.versions.length ? "上传新版" : "上传首版"}</button>}
      </div>
      <div className="card-bd">
        <p className="ro" style={{ marginBottom: "var(--space-4)" }}><Svg d={IC.lock} />已发布的版本只读，任何角色都不能删除或替换版本文件与改动说明。</p>
        {!s.versions.length ? <Empty text="该分册还没有图纸。" /> : (
          <ol className="tl">
            {s.versions.map((v, i) => {
              const signed = v.status === "已签认";
              const prev = s.versions[i + 1];
              const superseded = v.status === "已被新版取代";
              const canSignThis = canSign && v.status === "待业主签认";
              return (
                <li key={v.id} className={signed ? "pass" : superseded ? "" : "pend"}>
                  <div className="ver">
                    {v.thumbUrl ? <img className="thumb" src={v.thumbUrl} alt={`${s.name} V${v.versionNo} 缩略图`} loading="lazy" /> : <div className="thumb ph"><Icon name="map" /></div>}
                    <div>
                      <div className="vh"><b>V{v.versionNo}</b>{signed ? <Seal kind="pass" just={just === v.id}>已签认</Seal> : superseded ? <span className="tag">已被新版取代 · 未签认</span> : <Seal kind="pend">待签认</Seal>}<span className="muted" style={{ fontSize: "var(--text-sm)" }}>{v.createdBy} · {fmtDate(v.createdAt)} 发布</span></div>
                      <p className="note">{v.changeNote || "首版。"}</p>
                      <div className="files">
                        <a className="fchip" href={v.file.url} target="_blank" rel="noreferrer"><Icon name="doc" />{v.file.name} · {fileSize(v.file.size)}</a>
                        {v.cadFile && <a className="fchip" href={v.cadFile.url} download><Icon name="doc" />{v.cadFile.name} · CAD 附件</a>}
                      </div>
                      {signed && v.signSha256 && <p className="signrec">签认记录：{v.signedBy} · {fmtTime(v.signedAt)} · V{v.versionNo} · 文件摘要 SHA-256 {shaShort(v.signSha256)}</p>}
                      {v.affectedCount > 0 && <Affected v={v} />}
                      <div className="acts">
                        {canSignThis && <button type="button" className="btn primary" onClick={() => onSign(v)}><Icon name="stamp" />签认 V{v.versionNo}</button>}
                        <Link className="btn" to={`/p/${pid}/drawings/${v.id}`}><Svg d={IC.eye} />查看</Link>
                        {prev && <Link className="btn" to={`/p/${pid}/drawings/${v.id}?compare=${prev.id}`}><Svg d={IC.split} />与 V{prev.versionNo} 对比</Link>}
                      </div>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </section>
  );
}

function Affected({ v }: { v: Version }) {
  const signed = v.status === "已签认";
  const resign = v.affectedWorkItems.filter((w) => w.baselineStatus === "待重签").length;
  return (
    <details className="aff">
      <summary><Icon name="chevron" />受影响工作项 {v.affectedCount} 项{signed ? (resign ? ` · 其中 ${resign} 项待重签` : " · 签认后已处理") : `（其中基线已签认 ${v.affectedSignedCount} 项）`}</summary>
      <ul>{v.affectedWorkItems.map((w: AffectedItem) => {
        const [k, t] = BL_TAG[w.baselineStatus] || ["", w.baselineStatus];
        return <li key={w.id}><span>{w.name}</span><span className={`tag ${k}`}>{t}</span></li>;
      })}</ul>
    </details>
  );
}

function SignDialog({ pid, v, onClose, onDone }: { pid: string; v: Version; onClose: () => void; onDone: (id: number) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const onErr = useApiError();
  const { me } = useSession();
  const m = useMutation({
    mutationFn: () => api<{ resignCount: number }>(`/projects/${pid}/drawing-versions/${v.id}/sign`, { method: "POST", body: {} }),
    onSuccess: (r) => {
      toast(r.resignCount ? `V${v.versionNo} 已签认；${r.resignCount} 个工作项基线进入待重签` : `V${v.versionNo} 已签认`);
      qc.invalidateQueries({ queryKey: ["drawing-sets", pid] });
      qc.invalidateQueries({ queryKey: ["todo-count"] });
      onDone(v.id);
    },
    onError: (e) => { onErr(e); qc.invalidateQueries({ queryKey: ["drawing-sets", pid] }); onClose(); },
  });
  return (
    <ConfirmDialog cancelText="返回修改" title={`签认${v.setName} V${v.versionNo}`} confirmText="确认签认" busy={m.isPending} onClose={onClose} onConfirm={() => m.mutate()}
      summary={[["分册", v.setName], ["版本", `V${v.versionNo}（${v.file.name} · ${fileSize(v.file.size)}）`], ["文件摘要", <span className="mono">SHA-256 {v.file.sha256}</span>],
        ["改动说明", v.changeNote || "首版。"], ["签认人", `${me?.name || ""}（业主）`], ["签认时间", "以服务器时间为准"]]}
      warn={v.affectedCount ? `受影响的 ${v.affectedCount} 个工作项中，基线已签认的 ${v.affectedSignedCount} 项将变为「待重签」，并向项目经理和业主生成待办。` : undefined} />
  );
}

function NewSetDialog({ pid, onClose, onDone }: { pid: string; onClose: () => void; onDone: (id: number) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const m = useMutation({
    mutationFn: () => api<DrawingSet>(`/projects/${pid}/drawing-sets`, { body: { name } }),
    onSuccess: (s) => { toast(`已新建分册「${s.name}」`); qc.invalidateQueries({ queryKey: ["drawing-sets", pid] }); onDone(s.id); },
    onError: (e) => setErr((e as ApiError).fieldMap?.().name || (e as Error).message),
  });
  return (
    <Modal title="新建图纸分册" onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>取消</button><button type="button" className="btn primary" disabled={m.isPending} onClick={() => (name.trim() ? m.mutate() : setErr("请填写分册名称"))}>新建</button></>}>
      <Field label="分册名称" required error={err}><input className="input" value={name} maxLength={40} placeholder="例如：水电点位图" onChange={(e) => { setName(e.target.value); setErr(""); }} /></Field>
    </Modal>
  );
}

function UploadDialog({ pid, s, onClose }: { pid: string; s: DrawingSet; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [cad, setCad] = useState<File | null>(null);
  const [note, setNote] = useState("");
  const [picked, setPicked] = useState<number[]>([]);
  const [kw, setKw] = useState("");
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [formErr, setFormErr] = useState("");
  const [confirm, setConfirm] = useState(false);
  const no = s.nextVersionNo;
  const wis = useQuery({ queryKey: ["work-items", pid], queryFn: () => api<{ items: WorkItemRow[] }>(`/projects/${pid}/work-items`) });
  const list = useMemo(() => (wis.data?.items || []).filter((w) => !w.isDisabled && (!kw || `${w.floorName || ""}${w.roomName || ""}${w.name}`.includes(kw))), [wis.data, kw]);
  const byId = useMemo(() => new Map((wis.data?.items || []).map((w) => [w.id, w])), [wis.data]);

  const check = () => {
    const e: Record<string, string> = {};
    if (!file) e.file = cad ? "请同时上传 PDF 或图片版，CAD 仅作为附件" : "请上传 PDF 或图片版图纸";
    else if (!DRAW_EXT.includes(ext(file.name))) e.file = `${file.name}：格式不支持，仅支持 PDF、JPG、PNG`;
    else if (file.size > MAX) e.file = `${file.name}：超过 50MB，未上传`;
    if (cad && !CAD_EXT.includes(ext(cad.name))) e.cadFile = `${cad.name}：格式不支持，CAD 附件仅支持 DWG、DXF`;
    else if (cad && cad.size > MAX) e.cadFile = `${cad.name}：超过 50MB，未上传`;
    if (no >= 2 && !note.trim()) e.changeNote = "请说明本版改了什么";
    setErrs(e);
    setFormErr(Object.values(e).join("；"));
    return !Object.keys(e).length;
  };
  const m = useMutation({
    mutationFn: () => {
      const form = new FormData();
      if (file) form.append("file", file);
      if (cad) form.append("cadFile", cad);
      form.append("changeNote", note.trim());
      form.append("affectedWorkItemIds", picked.join(","));
      return api<Version>(`/projects/${pid}/drawing-sets/${s.id}/versions`, { form });
    },
    onSuccess: (v) => { toast(`已发布 ${s.name} V${v.versionNo}，等待业主签认`); qc.invalidateQueries({ queryKey: ["drawing-sets", pid] }); onClose(); },
    onError: (e) => {
      setConfirm(false);
      const ae = e as ApiError;
      setErrs(ae.fieldMap ? ae.fieldMap() : {});
      setFormErr(ae.status === 0 || !ae.status ? "上传失败（网络中断），请重试" : ae.message);
    },
  });
  const toggle = (id: number) => setPicked((x) => (x.includes(id) ? x.filter((i) => i !== id) : [...x, id]));
  const signedCount = picked.filter((id) => byId.get(id)?.baselineStatus === "已签认").length;

  return (
    <>
      <Modal title={`上传新版 · ${s.name} V${no}`} onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>取消</button><button type="button" className="btn primary" disabled={m.isPending} onClick={() => check() && setConfirm(true)}>{m.isPending ? "上传中" : "发布"}</button></>}>
        {formErr && <div className="err-box" role="alert">{formErr}</div>}
        <Field label="图纸文件（PDF、JPG 或 PNG，单个不超过 50MB）" required error={errs.file}>
          <input className="input" type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          <span className="fileline">作为现场查看与检查点钉点的底图</span>
        </Field>
        <Field label="CAD 附件（可选）" error={errs.cadFile}>
          <input className="input" type="file" accept=".dwg,.dxf" onChange={(e) => setCad(e.target.files?.[0] || null)} />
          <span className="fileline">CAD 仅作为附件，不能单独发布</span>
        </Field>
        <Field label="本版改了什么" required={no >= 2} error={errs.changeNote}>
          <textarea className="textarea" rows={3} value={note} placeholder="例如：二楼主卫、次卫给水改走顶面；一楼厨房烟道旁插座下移 300mm" onChange={(e) => setNote(e.target.value)} />
        </Field>
        <Field label={`受影响的工作项（已勾选 ${picked.length} 项）`} error={errs.affectedWorkItemIds}>
          <input className="input" placeholder="按楼层、房间或名称筛选" value={kw} onChange={(e) => setKw(e.target.value)} />
          <div className="pks" role="group" aria-label="受影响的工作项">
            {wis.isLoading ? <span className="hint">加载工作项…</span> : list.map((w) => (
              <label key={w.id} className="pk"><input type="checkbox" checked={picked.includes(w.id)} onChange={() => toggle(w.id)} /><span>{w.name}{w.baselineStatus === "已签认" && <span className="tag ok" style={{ marginLeft: 6 }}>已签认</span>}</span></label>
            ))}
          </div>
          <span className="fileline">新版签认后，其中已签认的基线变为待重签</span>
        </Field>
      </Modal>
      {confirm && (
        <ConfirmDialog cancelText="返回修改" title={`发布 ${s.name} V${no}`} confirmText="确认发布" busy={m.isPending} onClose={() => setConfirm(false)} onConfirm={() => m.mutate()}
          summary={[["版本", `V${no}（发布后状态：待业主签认）`], ["图纸文件", file ? `${file.name} · ${fileSize(file.size)}` : "—"], ["CAD 附件", cad ? cad.name : "无"],
            ["改动说明", note.trim() || "首版。"], ["受影响工作项", picked.length ? `${picked.length} 项（其中基线已签认 ${signedCount} 项）` : "无"]]}
          warn="发布后版本文件与改动说明只读，任何角色都不能删除或替换。" />
      )}
    </>
  );
}
