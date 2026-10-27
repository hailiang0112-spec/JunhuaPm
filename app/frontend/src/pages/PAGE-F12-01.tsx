// PAGE-F12-01 · 档案资料（REQ-F12-03：布局图 / 效果图 / 合同三个专区的分类；合同专区仅业主、项目经理、预算专员、公司管理员可见）
import { useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type UploadedFile } from "../api";
import { Card, Shell } from "../layout/Shell";
import { useProject } from "../session";
import { ConfirmDialog, ErrorState, Field, Icon, Loading, Modal, useApiError, useToast } from "../ui";
import "../styles/pages/PAGE-F12-01.css";

type Zone = "layout" | "render" | "contract";
const ZONES: [Zone, string][] = [["layout", "平面布局图"], ["render", "三维效果图"], ["contract", "装修合同"]];
const ZONE_NAME = Object.fromEntries(ZONES) as Record<Zone, string>;
type Folder = { id: number; zone: Zone; name: string; orderNo: number; fileCount: number };
type ArchiveFile = UploadedFile & {
  archiveFileId: number; folderId: number; uploaderName: string; uploadedOn: string; refs: string[];
  voidedByName: string | null; voidedAt: string | null; isMine: boolean; canVoid: boolean;
};
const ALLOWED = [".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf", ".doc", ".docx", ".xls", ".xlsx"];
const MAX = 50 * 1024 * 1024;

const fileSize = (n: number) => `${Math.max(0.1, n / 1024 / 1024).toFixed(1)}MB`;
const hm = (s: string | null) => (s ? `${s.slice(0, 10)} ${s.slice(11, 16)}` : "");
const ext = (name: string) => (name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "");

type Pending = { file: File; reason: string; state: "ready" | "done" | "bad" | "uploading" };

export default function Archive() {
  const { pid } = useParams();
  const { project, can } = useProject(pid);
  const [sp, setSp] = useSearchParams();
  const zone = (ZONES.some(([z]) => z === sp.get("zone")) ? sp.get("zone") : "layout") as Zone;
  const catParam = sp.get("cat");
  const [showVoid, setShowVoid] = useState(false);
  const toast = useToast();
  const onErr = useApiError();
  const qc = useQueryClient();
  const denied = zone === "contract" && !!project && !can("contract.read");
  const canManage = can("archive.folder_manage");

  const folders = useQuery({
    queryKey: ["archive-folders", pid, zone],
    queryFn: () => api<{ items: Folder[] }>(`/projects/${pid}/archive/${zone}/folders`),
    enabled: !!pid && !!project && !denied,
  });
  const list = folders.data?.items || [];
  const current = useMemo(() => list.find((f) => f.name === catParam) || list.find((f) => f.fileCount > 0) || list[0], [list, catParam]);
  const files = useQuery({
    queryKey: ["archive-files", pid, current?.id, showVoid],
    queryFn: () => api<{ folder: Folder; items: ArchiveFile[] }>(`/projects/${pid}/archive/${zone}/folders/${current!.id}/files${showVoid ? "?showVoided=1" : ""}`),
    enabled: !!current,
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["archive-folders", pid] });
    qc.invalidateQueries({ queryKey: ["archive-files", pid] });
  };
  const go = (z: Zone, cat?: string) => setSp(cat ? { zone: z, cat } : { zone: z }, { replace: true });

  // 分类弹窗（新建 / 改名）
  const [catDlg, setCatDlg] = useState<null | "new" | "ren">(null);
  const [catName, setCatName] = useState("");
  const [catErr, setCatErr] = useState("");
  const saveCat = useMutation({
    mutationFn: (name: string) => catDlg === "ren"
      ? api<Folder>(`/projects/${pid}/archive/${zone}/folders/${current!.id}`, { method: "PATCH", body: { name } })
      : api<Folder>(`/projects/${pid}/archive/${zone}/folders`, { body: { name } }),
    onSuccess: (f) => {
      toast(catDlg === "ren" ? `已改名为「${f.name}」` : `已新建分类「${f.name}」`);
      setCatDlg(null);
      go(zone, f.name);
      refresh();
    },
    onError: (e) => {
      const m = (e as ApiError).fieldMap?.().name;
      if (m) setCatErr(m); else onErr(e);
    },
  });
  const submitCat = () => {
    const n = catName.trim();
    if (!n) { setCatErr("请填写分类名称"); return; }
    setCatErr("");
    saveCat.mutate(n);
  };

  const [delCat, setDelCat] = useState(false);
  const removeCat = useMutation({
    mutationFn: () => api(`/projects/${pid}/archive/${zone}/folders/${current!.id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast(`已删除空分类「${current!.name}」`);
      setDelCat(false);
      go(zone);
      qc.invalidateQueries({ queryKey: ["archive-folders", pid] });
    },
    onError: (e) => { setDelCat(false); onErr(e); },
  });
  const askDelete = () => {
    if (!current) return;
    if (current.fileCount > 0) { toast(`分类「${current.name}」下还有 ${current.fileCount} 个文件，请先移出文件`); return; }
    setDelCat(true);
  };

  // 作废、移动、预览
  const [voiding, setVoiding] = useState<ArchiveFile | null>(null);
  const voidFile = useMutation({
    mutationFn: (f: ArchiveFile) => api(`/projects/${pid}/archive-files/${f.archiveFileId}/void`, { body: {} }),
    onSuccess: (_d, f) => { toast(`已作废：${f.name}`); setVoiding(null); refresh(); },
    onError: (e) => { setVoiding(null); onErr(e); },
  });
  const askVoid = (f: ArchiveFile) => {
    if (f.refs.length) { toast(`该文件被${f.refs.join("、")}引用，不能作废`); return; }
    setVoiding(f);
  };
  const [moving, setMoving] = useState<ArchiveFile | null>(null);
  const [moveTo, setMoveTo] = useState<number | "">("");
  const moveFile = useMutation({
    mutationFn: () => api(`/projects/${pid}/archive-files/${moving!.archiveFileId}/move`, { body: { folderId: moveTo } }),
    onSuccess: () => { toast(`已移动到「${list.find((f) => f.id === moveTo)?.name}」`); setMoving(null); refresh(); },
    onError: onErr,
  });
  const [preview, setPreview] = useState<ArchiveFile | null>(null);

  // 上传：逐个上传，不合格的单独列出原因，同批其他文件照常上传（AC-F12-02）
  const [upOpen, setUpOpen] = useState(false);
  const [batch, setBatch] = useState<Pending[]>([]);
  const [uploading, setUploading] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const pick = (fl: FileList | null) => {
    if (!fl) return;
    setBatch(Array.from(fl).map((file) => {
      const reasons = [file.size > MAX ? "超过 50MB" : "", ALLOWED.includes(ext(file.name)) ? "" : "格式不在允许范围内"].filter(Boolean);
      return { file, reason: reasons.join("，且"), state: reasons.length ? "bad" : "ready" };
    }));
  };
  async function upload() {
    setUploading(true);
    const next = [...batch];
    for (let i = 0; i < next.length; i++) {
      if (next[i].state !== "ready") continue;
      next[i] = { ...next[i], state: "uploading" };
      setBatch([...next]);
      const form = new FormData();
      form.append("file", next[i].file);
      try {
        await api(`/projects/${pid}/archive/${zone}/folders/${current!.id}/files`, { form });
        next[i] = { ...next[i], state: "done" };
      } catch (e) {
        next[i] = { ...next[i], state: "bad", reason: (e as ApiError).message };
      }
      setBatch([...next]);
    }
    setUploading(false);
    const ok = next.filter((x) => x.state === "done").length;
    const bad = next.filter((x) => x.state === "bad").length;
    toast(`已上传 ${ok} 个文件` + (bad ? `，${bad} 个被拒绝` : ""));
    refresh();
    if (!bad) setUpOpen(false);
  }

  const visible = ZONES.filter(([z]) => z !== "contract" || can("contract.read"));
  const forbidden = denied || (folders.error as ApiError | null)?.status === 403;

  return (
    <Shell title="档案资料" sub={`${project?.name || ""} · 布局图、效果图和合同集中存放`}>
      <div className="zones" role="tablist" aria-label="档案专区">
        {visible.map(([z, name]) => (
          <button key={z} className="zone" role="tab" type="button" aria-selected={z === zone} onClick={() => go(z)}>
            <Icon name={z === "contract" ? "lock" : z === "layout" ? "map" : "grid"} />{name}
          </button>
        ))}
      </div>

      {forbidden ? (
        <Card>
          <div className="state arch-state">
            <div className="ic"><Icon name="lock" /></div>
            <h3>无权查看合同资料</h3>
            <p>装修合同专区仅业主、项目经理、预算专员和公司管理员可以查看。</p>
            <button className="btn" type="button" onClick={() => go("layout")}>查看平面布局图</button>
          </div>
        </Card>
      ) : folders.isLoading || !project ? (
        <Loading />
      ) : folders.error ? (
        <Card><ErrorState error={folders.error} retry={() => folders.refetch()} /></Card>
      ) : (
        <div className="arch">
          <section className="card" aria-label="分类">
            <div className="cats" role="list">
              {list.map((f) => (
                <button key={f.id} role="listitem" type="button" className={`cat${f.id === current?.id ? " on" : ""}`} onClick={() => go(zone, f.name)}>
                  <Icon name="folder" />{f.name}<span className="n">{f.fileCount}</span>
                </button>
              ))}
            </div>
            {canManage && (
              <div className="cat-tools">
                <button className="btn sm" type="button" onClick={() => { setCatName(""); setCatErr(""); setCatDlg("new"); }}><Icon name="plus" />新建分类</button>
                <button className="btn sm" type="button" disabled={!current} onClick={() => { setCatName(current?.name || ""); setCatErr(""); setCatDlg("ren"); }}><Icon name="doc" />改名</button>
                <button className="btn sm danger" type="button" disabled={!current} onClick={askDelete}><Icon name="close" />删除</button>
              </div>
            )}
          </section>
          <section className="card" aria-labelledby="catTitle">
            <div className="card-hd" style={{ flexWrap: "wrap" }}>
              <h2 id="catTitle">{current ? `${ZONE_NAME[zone]} · ${current.name}` : ZONE_NAME[zone]}</h2>
              {current && <span className="tag">{current.fileCount} 个文件</span>}
              <span className="spacer" />
              <label className="chk"><input type="checkbox" checked={showVoid} onChange={(e) => setShowVoid(e.target.checked)} />显示已作废</label>
              {can("archive.upload") && current && (
                <button className="btn" type="button" onClick={() => { setBatch([]); setUpOpen(true); }}><Icon name="upload" />上传文件</button>
              )}
            </div>
            <div className="card-bd">
              {!current ? (
                <div className="state arch-state"><h3>这个专区还没有分类</h3><p>公司管理员或项目经理可以新建分类。</p></div>
              ) : files.isLoading ? (
                <div aria-busy="true"><div className="skeleton" style={{ width: "40%", marginBottom: 12 }} /><div className="skeleton" /></div>
              ) : files.error ? (
                <ErrorState error={files.error} retry={() => files.refetch()} />
              ) : !files.data?.items.length ? (
                <div className="state arch-state">
                  <div className="ic"><Icon name="folder" /></div>
                  <h3>这个分类还没有文件</h3><p>上传布局图、效果图或合同扫描件后，业主可随时在这里查看。</p>
                </div>
              ) : (
                <div className="files">
                  {files.data.items.map((f) => {
                    const voided = f.status === "voided";
                    return (
                      <div key={f.archiveFileId} className={`fcard${voided ? " voided" : ""}`}>
                        <button className="thumb" type="button" aria-label={`预览 ${f.name}`} onClick={() => setPreview(f)}>
                          {f.thumbUrl ? <img src={f.thumbUrl} alt="" loading="lazy" /> : <><Icon name="doc" />{ext(f.name).slice(1).toUpperCase()}</>}
                        </button>
                        <div className="fbody">
                          <div className="fname">{f.name}</div>
                          <div className="fmeta">{fileSize(f.size)} · {f.uploaderName} · {f.uploadedOn}</div>
                          {f.refs.length > 0 && <div><span className="tag brand">被{f.refs.join("、")}引用</span></div>}
                          {voided && <div><span className="seal void">已作废</span> <span className="fmeta">{f.voidedByName} · {hm(f.voidedAt)}</span></div>}
                        </div>
                        {!voided && (
                          <div className="fact">
                            <a className="btn sm" href={f.url} download={f.name}>下载</a>
                            {canManage && <button className="btn sm" type="button" onClick={() => { setMoving(f); setMoveTo(""); }}>移动</button>}
                            {f.isMine && <button className="btn sm danger" type="button" onClick={() => askVoid(f)}>作废</button>}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </section>
        </div>
      )}

      {catDlg && (
        <Modal title={catDlg === "new" ? "新建分类" : "分类改名"} onClose={() => setCatDlg(null)} footer={<>
          <button className="btn" type="button" onClick={() => setCatDlg(null)}>取消</button>
          <button className="btn primary" type="button" disabled={saveCat.isPending} onClick={submitCat}>保存</button>
        </>}>
          <form onSubmit={(e) => { e.preventDefault(); submitCat(); }}>
            <Field label="分类名称" required error={catErr}>
              <input className="input" autoFocus maxLength={20} value={catName} placeholder="例如：地下室车库" onChange={(e) => setCatName(e.target.value)} />
            </Field>
          </form>
        </Modal>
      )}
      {delCat && current && (
        <ConfirmDialog title="删除分类" danger confirmText="确认删除" busy={removeCat.isPending} onClose={() => setDelCat(false)} onConfirm={() => removeCat.mutate()}
          summary={[["专区", ZONE_NAME[zone]], ["分类", current.name], ["文件数", "0（空分类）"]]} />
      )}
      {voiding && (
        <ConfirmDialog title="作废文件" danger confirmText="确认作废" busy={voidFile.isPending} onClose={() => setVoiding(null)} onConfirm={() => voidFile.mutate(voiding)}
          summary={[["文件", voiding.name], ["位置", `${ZONE_NAME[zone]} · ${current?.name || ""}`], ["作废人", voiding.uploaderName],
            ["作废后", "从默认列表隐藏，勾选「显示已作废」仍可查看，作废记录保留"]]} />
      )}
      {moving && (
        <Modal title="移动到分类" onClose={() => setMoving(null)} footer={<>
          <button className="btn" type="button" onClick={() => setMoving(null)}>取消</button>
          <button className="btn primary" type="button" disabled={!moveTo || moveFile.isPending} onClick={() => moveFile.mutate()}>移动</button>
        </>}>
          <p className="hint">把「{moving.name}」移动到{ZONE_NAME[zone]}的其他分类。</p>
          <Field label="目标分类">
            <select className="select" value={moveTo} onChange={(e) => setMoveTo(e.target.value ? Number(e.target.value) : "")}>
              <option value="">请选择</option>
              {list.filter((f) => f.id !== current?.id).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          </Field>
        </Modal>
      )}
      {preview && (
        <Modal title={preview.name} wide onClose={() => setPreview(null)} footer={<a className="btn primary" href={preview.url} download={preview.name}><Icon name="download" />下载原件</a>}>
          <div className="pv">{preview.isImage ? <img src={preview.url} alt={preview.name} /> : <><Icon name="doc" /><span>{ext(preview.name).slice(1).toUpperCase()} 文件，下载后查看</span></>}</div>
          <div className="fmeta">{ZONE_NAME[zone]} · {current?.name} · {fileSize(preview.size)} · 上传：{preview.uploaderName} {preview.uploadedOn}{preview.refs.length ? ` · 被${preview.refs.join("、")}引用` : ""}</div>
        </Modal>
      )}
      {upOpen && current && (
        <Modal title="上传文件" onClose={() => !uploading && setUpOpen(false)} footer={<>
          <button className="btn" type="button" disabled={uploading} onClick={() => setUpOpen(false)}>取消</button>
          <button className="btn primary" type="button" disabled={uploading || !batch.some((b) => b.state === "ready")} onClick={upload}>{uploading ? "上传中…" : "上传合格文件"}</button>
        </>}>
          <div className="notice plain"><Icon name="upload" /><span>上传到「<b>{ZONE_NAME[zone]} · {current.name}</b>」。可一次选择多个图片、PDF、Word 或 Excel 文件，单个不超过 50MB；不合格的文件会被拒绝，同批其他文件照常上传。</span></div>
          <div>
            <input ref={picker} className="hidden-input" type="file" multiple aria-label="选择文件" onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
            <button className="btn" type="button" disabled={uploading} onClick={() => picker.current?.click()}><Icon name="plus" />选择文件</button>
          </div>
          {batch.length > 0 && (
            <ul className="up-list">
              {batch.map((b, i) => (
                <li key={i} className={b.state === "bad" ? "bad" : b.state === "done" || b.state === "ready" ? "ok" : ""}>
                  <span className="nm">{b.file.name}</span><span className="fmeta">{fileSize(b.file.size)}</span>
                  <span className="r">{b.state === "bad" ? `已拒绝：${b.reason}` : b.state === "done" ? "已上传" : b.state === "uploading" ? "上传中…" : "可上传"}</span>
                </li>
              ))}
            </ul>
          )}
        </Modal>
      )}
    </Shell>
  );
}
