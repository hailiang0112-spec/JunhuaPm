// PAGE-F03-03 · 数据导入导出：Excel 计划模板与导出、上传逐行校验、确认导入与结果、原型 v1.20 备份导入。
// AC-F03-07 ~ AC-F03-10、AC-F18-01 ~ AC-F18-03；DEC-310（确认摘要）、DEC-311（原型门槛）、DEC-312（区块可见性）
import { useState, type DragEvent } from "react";
import { Link, Navigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Shell } from "../layout/Shell";
import { useProject } from "../session";
import { ConfirmDialog, ErrorState, Icon, Loading, Seal, useToast } from "../ui";
import "../styles/pages/PAGE-F03-03.css";

type Signed = { row: number; name: string; workItemId: number; changes: string[]; baselineStatus: string; note: string };
type Preview = { add: number; update: number; signed: Signed[]; same: number; phaseChanges: { phaseId: number; name: string; fields: string[] }[] };
type Batch = {
  id: number; status: string; fileName: string; createdAt: string; createdBy: string; sheets: number | null; taskRows: number | null;
  errors: { sheet: string; row: number; column: string; message: string }[]; preview: Preview | null;
  result: { added: number; updated: number; signed: Signed[]; same: number; errorRows: number; phaseLogs: number; supplementsAdded: number } | null;
};
type Proto = {
  id: number; status: string; fileName: string; createdAt: string; createdBy: string; projectStatus: string | null; message: string | null;
  counts: Record<string, number> | null; missing: { name: string; location: string; workItemId?: number; zone?: string }[];
};
const COUNT_LABEL: [string, string, string][] = [["workItems", "工作事项", ""], ["issues", "问题", ""], ["attendance", "人工出勤登记", " 天"], ["planLogs", "计划变更留档", ""], ["supplements", "补充事项", ""], ["notices", "公告留言", ""], ["photos", "验收图片", ""]];
const t16 = (s: string) => s.slice(0, 16).replace("T", " ");
const SHEETS: [string, string][] = [["施工阶段", "工段名称、计划起止、班组负责人、权重、施工范围"], ["工作事项", "工段、楼层、房间、名称、计划日期、负责人、权重、完成度、工作说明、验收标准"], ["补充事项", "补充事项台账"], ["填写说明", "每列的含义与取值范围"], ["取值", "工段名、楼层与房间对照、状态等可选值"]];

async function download(path: string) {
  const res = await fetch("/api" + path, { credentials: "same-origin" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body);
  }
  const cd = res.headers.get("Content-Disposition") || "";
  const name = decodeURIComponent(cd.split("filename*=UTF-8''")[1] || "计划.xlsx");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  return name;
}

function Drop({ accept, label, hint, busy, onFile }: { accept: string; label: string; hint: string; busy?: boolean; onFile: (f: File) => void }) {
  const [over, setOver] = useState(false);
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) onFile(f); };
  return (
    <label className={`drop${over ? " over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop}>
      <Icon name="upload" /><span><b>{busy ? "上传校验中…" : label}</b>，或拖到这里</span><span style={{ fontSize: "var(--text-xs)" }}>{hint}</span>
      <input className="sr" style={{ position: "absolute", width: 1, height: 1, opacity: 0, overflow: "hidden", pointerEvents: "none" }} type="file" accept={accept} disabled={busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
    </label>
  );
}

function SignedTable({ pid, rows }: { pid: string; rows: Signed[] }) {
  if (!rows.length) return null;
  return (
    <div className="scroll-x"><table style={{ minWidth: 600 }}>
      <thead><tr><th>已签认工作项</th><th>文件中的修改</th><th>处理</th><th /></tr></thead>
      <tbody>{rows.map((s) => (
        <tr key={s.workItemId}><td><b>{s.name}</b></td><td>{s.changes.join("；")}</td><td><Seal kind="pend">{s.note}</Seal></td>
          <td style={{ textAlign: "right" }}><Link className="btn sm" to={`/p/${pid}/changes/new?item=${s.workItemId}`}>发起变更单</Link></td></tr>
      ))}</tbody>
    </table></div>
  );
}

export default function ImportExport() {
  const { pid = "" } = useParams();
  const toast = useToast();
  const qc = useQueryClient();
  const { project, can, isLoading } = useProject(pid);
  const canPlan = can("plan.import"), canProto = can("prototype.import");
  const batches = useQuery({ queryKey: ["plan-imports", pid], queryFn: () => api<{ items: Batch[] }>(`/projects/${pid}/plan/imports`), enabled: canPlan });
  const protos = useQuery({ queryKey: ["prototype-imports", pid], queryFn: () => api<{ items: Proto[]; projectStatus: string }>(`/projects/${pid}/prototype-imports`), enabled: canPlan || canProto });
  const [cur, setCur] = useState<Batch | null>(null);
  const [typeErr, setTypeErr] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [done, setDone] = useState("");

  const up = useMutation({
    mutationFn: (f: File) => { const form = new FormData(); form.append("file", f); return api<Batch>(`/projects/${pid}/plan/imports`, { form }); },
    onSuccess: (b) => { setCur(b); setDone(""); qc.invalidateQueries({ queryKey: ["plan-imports", pid] }); },
    onError: (e: ApiError) => { setCur(null); setTypeErr(e.message); },
  });
  const exec = useMutation({
    mutationFn: (id: number) => api<Batch>(`/projects/${pid}/plan/imports/${id}/execute`, { body: {} }),
    onSuccess: (b) => {
      setConfirm(false); setCur(null); setDone(b.fileName);
      const r = b.result!;
      toast(`导入完成：新增 ${r.added} 项，更新 ${r.updated} 项，${r.signed.length} 项已签认需走变更单`);
      ["plan-imports", "structure", "work-items-all", "overview", "floor-view", "phase-detail", "project"].forEach((k) => qc.invalidateQueries({ queryKey: [k, pid] }));
      setTimeout(() => document.getElementById("res-t")?.scrollIntoView({ behavior: "smooth" }), 50);
    },
    onError: (e: ApiError) => { setConfirm(false); toast(e.message); },
  });
  const proto = useMutation({
    mutationFn: (f: File) => { const form = new FormData(); form.append("file", f); return api<Proto>(`/projects/${pid}/prototype-imports`, { form }); },
    onSuccess: (r) => { toast(`原型备份已导入：工作事项 ${r.counts?.workItems ?? 0} 项`); qc.invalidateQueries({ queryKey: ["prototype-imports", pid] }); qc.invalidateQueries({ queryKey: ["structure", pid] }); },
    onError: (e: ApiError) => { toast(e.message); qc.invalidateQueries({ queryKey: ["prototype-imports", pid] }); },
  });
  const pick = (f: File) => {
    setTypeErr("");
    if (!/\.(xlsx|csv)$/i.test(f.name)) { setCur(null); setTypeErr("只支持 .xlsx 或 .csv 计划文件，请重新选择。"); return; }
    up.mutate(f);
  };
  const dl = (path: string) => download(path).then((n) => toast(`已生成 ${n}`)).catch((e: ApiError) => toast(e.message));

  if ((batches.error as ApiError | null)?.status === 403 && !canProto) return <Navigate to="/forbidden" replace />;
  const last = batches.data?.items.find((b) => b.status === "已导入");
  const pStatus = protos.data?.projectStatus || project?.status || "";

  return (
    <Shell title="数据导入导出" sub={`${project?.name || ""}　｜　Excel 计划整批导入导出，原型 v1.20 备份迁移`}>
      <div className="plan-pg pg-f0303">
        {isLoading && <Loading rows={4} />}
        {project && !canPlan && !canProto && <div className="card"><div className="state"><div className="ic"><Icon name="lock" /></div>
          <p><b style={{ color: "var(--fg)" }}>当前身份不能使用数据导入导出</b></p><p style={{ fontSize: "var(--text-sm)" }}>Excel 计划由项目经理导入导出，原型备份由公司管理员导入。</p>
          <p style={{ marginTop: "var(--space-3)" }}><Link className="btn" to={`/p/${pid}`}>返回项目总览</Link></p></div></div>}

        {canPlan && <>
          <section className="card" aria-labelledby="tpl-t">
            <div className="card-hd"><h2 id="tpl-t">Excel 计划模板与导出</h2><span className="desc">表结构沿用原型 v1.20</span></div>
            <div className="card-bd">
              <div className="row">
                <button className="btn" type="button" onClick={() => dl(`/projects/${pid}/plan/template.xlsx`)}><Icon name="download" />下载空白模板</button>
                <button className="btn" type="button" onClick={() => dl(`/projects/${pid}/plan/export.xlsx`)}><Icon name="grid" />导出当前计划</button>
                <span className="muted" style={{ fontSize: "var(--text-xs)" }}>生成 .xlsx：数值列为数字格式，日期列为文本格式</span>
              </div>
              <div className="sheets">{SHEETS.map(([n, d]) => <div key={n} className="sheet-i"><b><Icon name="grid" />{n}</b>{d}</div>)}</div>
            </div>
          </section>

          <section className="card" aria-labelledby="up-t">
            <div className="card-hd"><h2 id="up-t">上传计划文件</h2><span className="desc">按表头识别列，逐行校验；只新增工作项、更新未签认工作项</span></div>
            <div className="card-bd">
              <Drop accept=".xlsx,.csv" label="选择 .xlsx 或 .csv 文件" hint="上传后立即校验，校验全部通过才能执行导入" busy={up.isPending} onFile={pick} />
              {typeErr && <div className="bn bad" role="alert" style={{ marginTop: "var(--space-4)" }}><Icon name="alert" /><span>{typeErr}</span></div>}
              {up.isPending && <Loading rows={2} />}
              {done && <div className="bn ok" role="status" style={{ marginTop: "var(--space-4)" }}><Icon name="check" /><span>「{done}」已导入，结果见下方。</span></div>}
              {cur && <>
                <div className="filebar"><Icon name="grid" /><span className="nm">{cur.fileName}</span><span className="m">{cur.createdBy} 上传于 {t16(cur.createdAt)} · 识别工作表 {cur.sheets ?? 0} 个 · 工作事项 {cur.taskRows ?? 0} 行</span></div>
                {cur.errors.length ? <>
                  <div className="bn bad" role="alert"><Icon name="alert" /><span>发现 {cur.errors.length} 处错误。全部修正前不能执行导入，请在 Excel 中按下列位置修改后重新上传。</span></div>
                  <div className="scroll-x" style={{ marginTop: "var(--space-3)" }}><table className="errtbl" style={{ minWidth: 560 }}>
                    <thead><tr><th>工作表</th><th className="num">行号</th><th>列</th><th>问题</th></tr></thead>
                    <tbody>{cur.errors.map((e, i) => <tr key={i}><td className="nowrap">{e.sheet}</td><td className="num nowrap"><b>第 {e.row} 行</b></td><td className="nowrap">{e.column}</td><td>{e.message}</td></tr>)}</tbody>
                  </table></div>
                  <div className="acts-row"><span className="why">修正后点上方重新选择文件</span></div>
                </> : cur.preview && <>
                  <div className="bn ok" role="status"><Icon name="check" /><span>校验通过，没有错误行。</span></div>
                  <div className="stats"><div><b>{cur.preview.add}</b><span>新增工作项</span></div><div><b>{cur.preview.update}</b><span>更新未签认工作项</span></div><div><b>{cur.preview.signed.length}</b><span>已签认（不修改）</span></div><div><b>{cur.preview.same}</b><span>与当前一致</span></div></div>
                  <div className="acts-row"><button className="btn primary" type="button" onClick={() => setConfirm(true)}>执行导入</button>{cur.preview.signed.length > 0 && <span className="why">已签认的 {cur.preview.signed.length} 项不会被修改，导入后逐项列出</span>}</div>
                </>}
              </>}
            </div>
          </section>

          <section className="card" aria-labelledby="res-t">
            <div className="card-hd"><h2 id="res-t">导入结果</h2><span className="desc">{last ? `最近一次：${t16(last.createdAt)} · ${last.createdBy}` : ""}</span></div>
            <div className="card-bd">
              {batches.isLoading ? <Loading rows={2} /> : batches.error ? <ErrorState error={batches.error} retry={() => batches.refetch()} /> : last?.result ? <>
                <div className="filebar"><Icon name="grid" /><span className="nm">{last.fileName}</span><Seal kind="pass">已导入</Seal></div>
                <div className="stats"><div><b>{last.result.added}</b><span>新增工作项</span></div><div><b>{last.result.updated}</b><span>更新未签认工作项</span></div><div><b className="down">{last.result.signed.length}</b><span>已签认，需走变更单</span></div><div><b>{last.result.errorRows}</b><span>错误行</span></div></div>
                <SignedTable pid={pid} rows={last.result.signed} />
              </> : <p className="muted">还没有导入记录</p>}
            </div>
          </section>
        </>}

        {(canPlan || canProto) && <section className="card" aria-labelledby="js-t">
          <div className="card-hd"><h2 id="js-t">原型 v1.20 备份导入</h2><span className="desc">公司管理员把原型导出的 JSON 备份导入筹备中的项目</span></div>
          <div className="card-bd">
            {pStatus && pStatus !== "筹备" && <div className="bn warn" role="status"><Icon name="alert" /><span>当前项目状态为「{pStatus}」。原型备份只能导入「筹备」状态的项目。</span></div>}
            {pStatus === "筹备" && canProto && <Drop accept=".json" label="选择原型导出的 .json 备份" hint="导入的每条数据标注来源「原型导入」，不生成任何签认、核对或放行记录" busy={proto.isPending} onFile={(f) => proto.mutate(f)} />}
            {pStatus === "筹备" && !canProto && <p className="muted" style={{ fontSize: "var(--text-sm)" }}>原型备份由公司管理员导入。</p>}
            <h3 style={{ fontSize: "var(--text-base)", margin: "var(--space-4) 0 var(--space-2)" }}>导入记录</h3>
            {protos.isLoading && <Loading rows={2} />}
            {protos.data && !protos.data.items.length && <p className="muted" style={{ fontSize: "var(--text-sm)" }}>还没有原型备份导入记录。</p>}
            {protos.data?.items.map((h) => (
              <div key={h.id} className="hist">
                <div className="h">{h.status === "已导入" ? <Seal kind="pass">已导入</Seal> : <Seal kind="stop">已拒绝</Seal>}<b>{h.fileName}</b><span className="spacer" />
                  <span className="m">{t16(h.createdAt)} · {h.createdBy}{h.projectStatus ? ` · 项目当时为「${h.projectStatus}」` : ""}</span></div>
                {h.status === "已导入" ? <>
                  <div className="counts">{COUNT_LABEL.map(([k, l, u]) => <span key={k} className="tag">{l} {h.counts?.[k] ?? 0}{u}</span>)}</div>
                  <p className="m" style={{ marginTop: "var(--space-2)" }}>每条均标注来源「原型导入」；未生成任何签认、核对或放行记录。</p>
                  {h.missing.length > 0 && <>
                    <div className="bn bad" style={{ marginTop: "var(--space-3)" }}><Icon name="alert" /><span>{h.missing.length} 个资料文件只有元数据、没有文件本体，已标记「文件缺失，需重新上传」</span></div>
                    <ul className="miss">{h.missing.map((x, i) => (
                      <li key={i}><span className="tag bad">文件缺失，需重新上传</span>{x.name}<span className="muted" style={{ fontSize: "var(--text-xs)" }}>{x.location}</span>
                        {x.workItemId && canPlan && <Link className="btn sm" style={{ marginLeft: "auto" }} to={`/p/${pid}/work-items/${x.workItemId}#files`}>去补传</Link>}
                        {x.zone && <Link className="btn sm" style={{ marginLeft: "auto" }} to={`/p/${pid}/archive?zone=${x.zone}`}>去补传</Link>}</li>
                    ))}</ul>
                  </>}
                </> : <p style={{ fontSize: "var(--text-sm)", marginTop: "var(--space-2)" }}>{h.message || "不是有效的原型备份文件。项目数据未改变。"}</p>}
              </div>
            ))}
          </div>
        </section>}

        {confirm && cur?.preview && (
          <ConfirmDialog title="确认导入计划" confirmText="确认导入" busy={exec.isPending} onClose={() => setConfirm(false)} onConfirm={() => exec.mutate(cur.id)}
            summary={[
              ["文件", cur.fileName], ["新增工作项", `${cur.preview.add} 项`], ["更新未签认工作项", `${cur.preview.update} 项`],
              ["已签认工作项", `${cur.preview.signed.length} 项不做任何修改，结果中列为「已签认，需走变更单」`],
              ["工段", cur.preview.phaseChanges.length ? `${cur.preview.phaseChanges.map((p) => p.name).join("、")} 计划有变化，将追加计划变更留档` : "施工阶段工作表与当前计划一致，不产生计划留档"],
            ]} />
        )}
      </div>
    </Shell>
  );
}
