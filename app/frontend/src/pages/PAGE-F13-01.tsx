// PAGE-F13-01 · 补充事项（REQ-F13-01：登记口头约定与待办，状态待处理 / 处理中 / 已完成，未完成在前；项目经理可转为变更单）
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, uploadFile, type UploadedFile } from "../api";
import { Shell } from "../layout/Shell";
import { useProject } from "../session";
import { ErrorState, Field, Icon, Modal, Seal, useApiError, useToast } from "../ui";
import "../styles/pages/PAGE-F13-01.css";

type Item = {
  id: number; code: string; title: string; note: string; raisedOn: string; dueOn: string; ownerName: string;
  status: "待处理" | "处理中" | "已完成"; files: UploadedFile[]; changeOrder: { id: number; code: string } | null; canConvert: boolean;
};
type Data = { items: Item[]; counts: { undone: number; done: number }; members: string[]; today: string };
const STATUSES: Item["status"][] = ["待处理", "处理中", "已完成"];
const EMPTY = { title: "", note: "", raisedOn: "", dueOn: "", ownerName: "" };

export default function Supplements() {
  const { pid } = useParams();
  const { project, can } = useProject(pid);
  const toast = useToast();
  const onErr = useApiError();
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["supplements", pid], queryFn: () => api<Data>(`/projects/${pid}/supplements`), enabled: !!pid });
  const canEdit = can("supplement.edit");
  const [just, setJust] = useState<number | null>(null);

  const setStatus = useMutation({
    mutationFn: ({ it, status }: { it: Item; status: string }) => api<Item>(`/projects/${pid}/supplements/${it.id}/status`, { body: { status } }),
    onSuccess: (it) => {
      toast(`${it.code} 状态改为「${it.status}」`);
      setJust(it.id);
      qc.invalidateQueries({ queryKey: ["supplements", pid] });
    },
    onError: onErr,
  });
  const toChange = useMutation({
    mutationFn: (it: Item) => api<Item>(`/projects/${pid}/supplements/${it.id}/to-change`, { body: {} }),
    onSuccess: (it) => {
      qc.invalidateQueries({ queryKey: ["supplements", pid] });
      qc.invalidateQueries({ queryKey: ["change-orders"] });
      toast(`已生成变更单草稿 ${it.changeOrder!.code}，来源 ${it.code}`);
      nav(`/p/${pid}/changes/${it.changeOrder!.id}`);
    },
    onError: onErr,
  });

  // 登记弹窗
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const openAdd = () => { setForm({ ...EMPTY, raisedOn: q.data?.today || "" }); setErrs({}); setFiles([]); setOpen(true); };
  const create = useMutation({
    mutationFn: () => api<Item>(`/projects/${pid}/supplements`, { body: { ...form, fileIds: files.map((f) => f.id) } }),
    onSuccess: (it) => { toast(`已登记 ${it.code}，状态：待处理`); setOpen(false); qc.invalidateQueries({ queryKey: ["supplements", pid] }); },
    onError: (e) => { const m = (e as ApiError).fieldMap?.(); if (m && Object.keys(m).length) setErrs(m); else onErr(e); },
  });
  const submit = () => {
    const e: Record<string, string> = {};
    if (!form.title.trim()) e.title = "请填写标题";
    if (!form.raisedOn) e.raisedOn = "请选择提出日期";
    if (!form.dueOn) e.dueOn = "请选择约定完成日期";
    else if (form.raisedOn && form.dueOn < form.raisedOn) e.dueOn = "约定完成日期不能早于提出日期";
    if (!form.ownerName) e.ownerName = "请选择责任人";
    setErrs(e);
    if (!Object.keys(e).length) create.mutate();
  };
  async function addFiles(fl: FileList | null) {
    if (!fl) return;
    setUploading(true);
    for (const f of Array.from(fl)) {
      try {
        const up = await uploadFile(pid!, f);
        setFiles((x) => [...x, up]);
      } catch (e) {
        toast((e as ApiError).message);
      }
    }
    setUploading(false);
  }
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const data = q.data;
  return (
    <Shell title="补充事项" sub={`${project?.name || ""} · 口头约定、增项和待办登记成台账`}
      actions={canEdit && <button className="btn primary" type="button" onClick={openAdd}><Icon name="plus" />登记补充事项</button>}>
      <section className="card" aria-labelledby="lTitle">
        <div className="card-hd" style={{ flexWrap: "wrap" }}>
          <h2 id="lTitle">补充事项台账</h2>
          {data && <><span className="tag warn">未完成 {data.counts.undone}</span><span className="tag ok">已完成 {data.counts.done}</span></>}
          <span className="spacer" /><span className="muted" style={{ fontSize: "var(--text-xs)" }}>未完成的排在前面</span>
        </div>
        {q.isLoading ? (
          <div className="card-bd" aria-busy="true"><div className="skeleton" style={{ width: "40%", marginBottom: 12 }} /><div className="skeleton" style={{ marginBottom: 12 }} /><div className="skeleton" style={{ width: "65%" }} /></div>
        ) : q.error ? (
          <ErrorState error={q.error} retry={() => q.refetch()} />
        ) : !data?.items.length ? (
          <div className="state sup-state">
            <div className="ic"><Icon name="list" /></div>
            <h3>还没有补充事项</h3><p>业主现场提出的口头约定、增项和待办，都可以登记成台账。</p>
            {canEdit && <button className="btn" type="button" onClick={openAdd}><Icon name="plus" />登记补充事项</button>}
          </div>
        ) : (
          <div className="items">
            {data.items.map((x) => (
              <article key={x.id} className={`it${x.status === "已完成" ? " done" : ""}`}>
                <div>
                  <div className="it-hd">
                    <span className="mono">{x.code}</span><span className="it-title">{x.title}</span>
                    <Seal kind={x.status === "已完成" ? "pass" : "pend"} just={just === x.id}>{x.status}</Seal>
                  </div>
                  {x.note && <p className="it-desc">{x.note}</p>}
                  <div className="it-meta">
                    <span>提出 <b>{x.raisedOn}</b></span><span>约定完成 <b>{x.dueOn}</b></span><span>责任人 <b>{x.ownerName}</b></span>
                    {x.changeOrder && <span>已转变更单 <Link to={`/p/${pid}/changes/${x.changeOrder.id}`}>{x.changeOrder.code}</Link></span>}
                  </div>
                  {x.files.length > 0 && (
                    <div className="att">
                      {x.files.map((f) => <a key={f.id} className="tag" href={f.url} target="_blank" rel="noreferrer"><Icon name="doc" />{f.name}</a>)}
                    </div>
                  )}
                </div>
                <div className="it-side">
                  {canEdit && (
                    <div className="seg" role="group" aria-label={`${x.code} 状态`}>
                      {STATUSES.map((s) => (
                        <button key={s} type="button" aria-pressed={s === x.status} disabled={setStatus.isPending}
                          onClick={() => s !== x.status && setStatus.mutate({ it: x, status: s })}>{s}</button>
                      ))}
                    </div>
                  )}
                  {x.canConvert && (
                    <button className="btn sm" type="button" disabled={toChange.isPending} onClick={() => toChange.mutate(x)}><Icon name="doc" />转为变更单</button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {open && (
        <Modal title="登记补充事项" onClose={() => setOpen(false)} footer={<>
          <button className="btn" type="button" onClick={() => setOpen(false)}>取消</button>
          <button className="btn primary" type="button" disabled={create.isPending || uploading} onClick={submit}>保存</button>
        </>}>
          <div className="form-grid">
            <Field label="标题" required error={errs.title} full>
              <input className="input" maxLength={100} value={form.title} onChange={set("title")} placeholder="例如：二楼次卧加装窗帘盒" />
            </Field>
            <Field label="说明" full>
              <textarea className="textarea" rows={3} value={form.note} onChange={set("note")} placeholder="写清谁提出、在哪里、约定了什么" />
            </Field>
            <Field label="提出日期" required error={errs.raisedOn}><input className="input" type="date" value={form.raisedOn} onChange={set("raisedOn")} /></Field>
            <Field label="约定完成日期" required error={errs.dueOn}><input className="input" type="date" value={form.dueOn} onChange={set("dueOn")} /></Field>
            <Field label="责任人" required error={errs.ownerName}>
              <select className="select" value={form.ownerName} onChange={set("ownerName")}>
                <option value="">请选择</option>
                {(data?.members || []).map((m) => <option key={m}>{m}</option>)}
              </select>
            </Field>
            <Field label="附件" error={errs.fileIds}>
              <div className="row">
                <input ref={picker} className="hidden-input" type="file" multiple aria-label="添加附件" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
                <button className="btn sm" type="button" disabled={uploading} onClick={() => picker.current?.click()}><Icon name="plus" />添加附件</button>
                <span className="muted" style={{ fontSize: "var(--text-xs)" }}>{uploading ? "上传中…" : files.length ? `已添加 ${files.length} 个` : "未添加"}</span>
              </div>
              {files.length > 0 && <div className="att">{files.map((f) => <span key={f.id} className="tag"><Icon name="doc" />{f.name}</span>)}</div>}
            </Field>
          </div>
        </Modal>
      )}
    </Shell>
  );
}
