// PAGE-F01-01 · 项目管理（REQ-F01-01：从公司模板新建项目；AC-F01-04 公司管理员看到全部项目）
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { bj } from "../time";
import { api, ApiError } from "../api";
import { Shell } from "../layout/Shell";
import { useSession } from "../session";
import { Field, Icon, Modal, Seal, useToast } from "../ui";
import { AdminOnly, StateCard } from "../acct";
import "../styles/pages/PAGE-F01-01.css";

type Proj = {
  id: number; name: string; address: string; status: string; plannedStart: string; plannedHandover: string; actualHandover: string | null;
  pmNames: string[]; ownerNames: string[]; memberCount: number; progress: number;
};
type Tpl = { id: number; name: string; stats: { phases: number; floors: number; rooms: number; workItems: number; rules: number }; lastSaved: { at: string; by: string } | null };
const STATUSES = ["全部", "筹备", "施工中", "已交房"];
const PAGE = 20;

function StatusSeal({ st, just }: { st: string; just?: boolean }) {
  if (st === "施工中") return <span className="seal plain">{st}</span>;
  return <Seal kind={st === "已交房" ? "pass" : "pend"} just={just}>{st}</Seal>;
}

function NewProject({ onClose, onDone }: { onClose: () => void; onDone: (p: Proj) => void }) {
  const tpls = useQuery({ queryKey: ["admin-templates"], queryFn: () => api<{ items: Tpl[] }>("/admin/templates") });
  const [f, setF] = useState({ name: "", address: "", plannedStart: "", plannedHandover: "", templateId: 0 });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const tplId = f.templateId || tpls.data?.items[0]?.id || 0;
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (!f.name.trim()) er.name = "请填写项目名称";
    if (!f.address.trim()) er.address = "请填写项目地址";
    if (!f.plannedStart) er.plannedStart = "请选择计划开工日期";
    if (!f.plannedHandover) er.plannedHandover = "请选择计划交房日期";
    else if (f.plannedStart && f.plannedHandover < f.plannedStart) er.plannedHandover = "计划交房日期不能早于计划开工日期";
    if (!tplId) er.templateId = "请选择公司模板";
    setErrs(er);
    if (Object.keys(er).length) return;
    setBusy(true);
    try {
      onDone(await api<Proj>("/projects", { body: { ...f, name: f.name.trim(), address: f.address.trim(), templateId: tplId } }));
    } catch (ex) {
      const a = ex as ApiError;
      if (a.fields.length) setErrs(a.fieldMap());
      else setErrs({ _: a.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="新建项目" onClose={onClose} footer={<>
      <button type="button" className="btn" onClick={onClose}>取消</button>
      <button type="submit" form="newForm" className="btn primary" disabled={busy}>{busy ? "创建中…" : "创建项目"}</button>
    </>}>
      <form id="newForm" className="new-project" noValidate onSubmit={submit} style={{ display: "grid", gap: "var(--space-3)" }}>
        <Field label="项目名称" required error={errs.name}><input className="input" id="nName" placeholder="例如：云栖台 · 合院别墅装修工程" value={f.name} onChange={set("name")} /></Field>
        <Field label="项目地址" required error={errs.address}><input className="input" id="nAddr" placeholder="例如：云栖台 7 号院" value={f.address} onChange={set("address")} /></Field>
        <div className="row2">
          <Field label="计划开工日期" required error={errs.plannedStart}><input className="input" id="nStart" type="date" value={f.plannedStart} onChange={set("plannedStart")} /></Field>
          <Field label="计划交房日期" required error={errs.plannedHandover}><input className="input" id="nEnd" type="date" value={f.plannedHandover} onChange={set("plannedHandover")} /></Field>
        </div>
        <fieldset className={`field${errs.templateId ? " invalid" : ""}`}>
          <label>公司模板 <span className="req">*</span></label>
          <div className="tpl">
            {(tpls.data?.items || []).map((t) => (
              <label key={t.id}>
                <input type="radio" name="tpl" checked={t.id === tplId} onChange={() => setF((x) => ({ ...x, templateId: t.id }))} />
                <span><b>{t.name}</b><small>{t.stats.phases} 个工段 · {t.stats.floors} 层 {t.stats.rooms} 个房间 · {t.stats.workItems} 项工作 · {t.stats.rules} 条工序规则{t.lastSaved ? ` · ${bj(t.lastSaved.at).format("YYYY-MM-DD")} ${t.lastSaved.by}修改` : ""}</small></span>
              </label>
            ))}
          </div>
          {errs.templateId && <span className="err">{errs.templateId}</span>}
        </fieldset>
        <div className="notice plain"><span>创建后状态为「筹备」，将复制所选模板的工段、楼层、房间、工作项和工序说明。之后修改模板不影响本项目。</span></div>
        {errs._ && <div className="notice bad" role="alert"><span>{errs._}</span></div>}
      </form>
    </Modal>
  );
}

export default function Projects() {
  const { me } = useSession();
  const toast = useToast();
  const qc = useQueryClient();
  const admin = !!me?.isCompanyAdmin;
  const q = useQuery({ queryKey: ["projects"], queryFn: () => api<{ items: Proj[] }>("/projects"), enabled: admin });
  const [st, setSt] = useState("全部");
  const [kw, setKw] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [justId, setJustId] = useState(0);

  if (!admin) return <Shell title="项目管理"><AdminOnly /></Shell>;
  const all = q.data?.items || [];
  const list = all.filter((p) => (st === "全部" || p.status === st) && (!kw.trim() || p.name.includes(kw.trim())));
  const pages = Math.max(1, Math.ceil(list.length / PAGE));
  const cur = Math.min(page, pages);
  const shown = list.slice((cur - 1) * PAGE, cur * PAGE);
  const newBtn = <button type="button" className="btn primary" onClick={() => setCreating(true)}><Icon name="plus" />新建项目</button>;

  return (
    <Shell title="项目管理" sub={q.data ? `公司全部项目 ${all.length} 个` : "公司全部项目"} actions={all.length ? newBtn : undefined}>
      <div className="pg-projects">
        {q.isLoading ? (
          <div className="card"><div className="card-bd" style={{ display: "grid", gap: "var(--space-3)" }}>{[40, 100, 85, 70, 90].map((w, i) => <div key={i} className="skeleton" style={{ width: `${w}%` }} />)}</div></div>
        ) : q.isError ? (
          <StateCard icon="alert" title="项目加载失败（网络中断），请重试" action={<button type="button" className="btn" onClick={() => q.refetch()}>重试</button>} />
        ) : !all.length ? (
          <StateCard icon="briefcase" title="还没有项目" text="从公司模板新建第一个工地。" action={newBtn} />
        ) : (
          <div className="card">
            <div className="toolbar">
              <div className="row" role="toolbar" aria-label="按状态筛选">
                {STATUSES.map((s) => <button key={s} type="button" className={`chip${s === st ? " on" : ""}`} aria-pressed={s === st} onClick={() => { setSt(s); setPage(1); }}>{s}</button>)}
              </div>
              <div className="search"><input className="input" placeholder="搜索项目名称" aria-label="搜索项目名称" value={kw} onChange={(e) => { setKw(e.target.value); setPage(1); }} /></div>
            </div>
            {list.length ? (
              <div className="scroll-x">
                <table className="ptable">
                  <thead><tr><th>项目名称 / 地址</th><th>状态</th><th>计划工期</th><th>实际交房</th><th>项目经理</th><th>业主</th><th className="num">成员</th><th>进度</th><th>操作</th></tr></thead>
                  <tbody>
                    {shown.map((p) => (
                      <tr key={p.id}>
                        <td className="wrap"><div className="pname">{p.name}</div><div className="paddr">{p.address || "未填写地址"}</div></td>
                        <td><StatusSeal st={p.status} just={p.id === justId} /></td>
                        <td className="mono">{p.plannedStart} ~ {p.plannedHandover}<div className="paddr">{dayjs(p.plannedHandover).diff(dayjs(p.plannedStart), "day") + 1} 天</div></td>
                        <td className="mono">{p.actualHandover || "—"}</td>
                        <td>{p.pmNames.join("、") || "—"}</td>
                        <td>{p.ownerNames.join("、") || "—"}</td>
                        <td className="num">{p.memberCount}</td>
                        <td><div className="pct"><div className="pbar"><i style={{ width: `${Math.round(p.progress)}%` }} /></div><span className="mono">{Math.round(p.progress)}%</span></div></td>
                        <td><div className="row" style={{ flexWrap: "nowrap" }}>
                          <Link className="btn sm" to={`/p/${p.id}`}>进入</Link>
                          <Link className="btn sm" to={`/p/${p.id}/members`}><Icon name="users" />成员</Link>
                        </div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="state"><h3>没有符合条件的项目</h3><p>换个筛选条件试试。</p><button type="button" className="btn" onClick={() => { setSt("全部"); setKw(""); }}>清除筛选</button></div>
            )}
            <div className="pager">
              <span>共 {list.length} 个项目 · 每页 {PAGE} 条 · 第 {cur} 页</span>
              <button type="button" className="btn sm" disabled={cur <= 1} onClick={() => setPage(cur - 1)}>上一页</button>
              <button type="button" className="btn sm" disabled={cur >= pages} onClick={() => setPage(cur + 1)}>下一页</button>
            </div>
          </div>
        )}
      </div>
      {creating && (
        <NewProject onClose={() => setCreating(false)} onDone={(p) => {
          setCreating(false);
          setSt("全部");
          setKw("");
          setJustId(p.id);
          toast(`已创建「${p.name}」，状态：筹备。下一步：在成员与项目页邀请成员`);
          qc.invalidateQueries({ queryKey: ["projects"] });
        }} />
      )}
    </Shell>
  );
}
