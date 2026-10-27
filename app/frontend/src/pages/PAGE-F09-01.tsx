// PAGE-F09-01 · 公司经验库（REQ-F09-02 审核与状态、AC-F09-03 修改生成新版本；排序与 AC-F09-04 推荐一致）
import { useState, type ReactNode } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { bj } from "../time";
import { api, ApiError } from "../api";
import { Shell } from "../layout/Shell";
import { useSession } from "../session";
import { ConfirmDialog, Field, Icon, Modal, Seal, useToast } from "../ui";
import { StateCard } from "../acct";
import "../styles/pages/PAGE-F09-01.css";

type Entry = {
  id: number; status: string; verNo: number; phaseName: string; colorVar: string; process: string; issueType: string; checkPoint: string;
  countermeasure: string; photoCount: number; reviewer: string | null; reviewedAt: string | null; submitter: string; createdAt: string;
  canEdit: boolean; canReview: boolean;
};
type ListResp = {
  items: Entry[]; total: number; page: number; pageSize: number; reviewedTotal: number; pendingCount: number | null; isQc: boolean;
  phases: { name: string; colorVar: string }[]; statuses: string[]; issueTypes: string[];
};
type Ver = { verNo: number; phaseName: string; process: string; issueType: string; checkPoint: string; countermeasure: string; status: string; changeNote: string; author: string; at: string };

const STATUS_DESC: [string, string][] = [["未验证经验", "一次发现，尚未在其他工地复核"], ["历史观察", "多次出现过，但对策效果未系统验证"], ["已验证", "对策在多个工地复核有效"]];
const tm = (s: string | null) => (s ? bj(s).format("YYYY-MM-DD HH:mm") : "");

function StatusSeal({ st, just }: { st: string; just?: boolean }) {
  if (st === "已验证") return <Seal kind="pass" just={just}>{st}</Seal>;
  if (st === "历史观察") return <Seal kind="proxy" just={just}>{st}</Seal>;
  if (st === "待审核") return <Seal kind="pend" just={just}>{st}</Seal>;
  return <span className={`seal mute${just ? " just" : ""}`}>{st}</span>;
}

function EntryCard({ e, just, children, foot }: { e: Entry; just?: boolean; children?: ReactNode; foot: ReactNode }) {
  return (
    <article className="card entry">
      <div className="card-hd">
        <div className="proc"><i className="phase-dot" style={{ background: `var(${e.colorVar})` }} />{e.phaseName} · {e.process}</div>
        <StatusSeal st={e.status} just={just} />
      </div>
      <div className="card-bd">
        <div><span className="tag">{e.issueType}</span></div>
        <div><div className="lbl">检查要点</div><div className="txt">{e.checkPoint}</div></div>
        <div><div className="lbl">对策</div><div className="txt">{e.countermeasure}</div></div>
        {children}
      </div>
      <div className="ft">{foot}</div>
    </article>
  );
}

export default function Experience() {
  const { me } = useSession();
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"list" | "queue">("list");
  const [phase, setPhase] = useState("");
  const [status, setStatus] = useState("");
  const [kw, setKw] = useState("");
  const [page, setPage] = useState(1);
  const [justId, setJustId] = useState(0);
  const [reviewing, setReviewing] = useState<Entry | null>(null);
  const [editing, setEditing] = useState<Entry | null>(null);
  const [history, setHistory] = useState<Entry | null>(null);
  const params = new URLSearchParams({ page: String(page) });
  if (phase) params.set("phase", phase);
  if (status) params.set("status", status);
  if (kw.trim()) params.set("q", kw.trim());
  const list = useQuery({ queryKey: ["experience", "list", params.toString()], queryFn: () => api<ListResp>(`/experience?${params}`), placeholderData: keepPreviousData });
  const isQc = !!list.data?.isQc;
  const queue = useQuery({ queryKey: ["experience", "queue"], queryFn: () => api<ListResp>("/experience?tab=pending&pageSize=50"), enabled: isQc });
  const refresh = () => qc.invalidateQueries({ queryKey: ["experience"] });

  const d = list.data;
  const filtered = !!(phase || status || kw.trim());
  const pages = d ? Math.max(1, Math.ceil(d.total / d.pageSize)) : 1;
  const sub = `全公司项目可见 · 已脱敏，不含业主姓名、项目地址和照片${d ? ` · 已审核 ${d.reviewedTotal} 条` : ""}`;

  return (
    <Shell title="公司经验库" sub={sub}>
      <div className="pg-exp">
        {list.isLoading ? (
          <div className="card"><div className="card-bd" style={{ display: "grid", gap: "var(--space-3)" }}>{[40, 100, 85, 70, 90].map((w, i) => <div key={i} className="skeleton" style={{ width: `${w}%` }} />)}</div></div>
        ) : list.isError || !d ? (
          <StateCard icon="alert" title="经验库加载失败（网络中断），请重试" action={<button type="button" className="btn" onClick={() => list.refetch()}>重试</button>} />
        ) : (
          <>
            <div className="tabs" role="tablist" aria-label="经验库">
              <button type="button" role="tab" aria-selected={tab === "list"} className={`chip${tab === "list" ? " on" : ""}`} onClick={() => setTab("list")}>经验条目</button>
              {isQc && (
                <button type="button" role="tab" aria-selected={tab === "queue"} className={`chip${tab === "queue" ? " on" : ""}`} onClick={() => setTab("queue")}>
                  待审核{!!d.pendingCount && <span className="badge">{d.pendingCount}</span>}
                </button>
              )}
            </div>
            {tab === "list" ? (
              <>
                <div className="card">
                  <div className="fbar">
                    <div className="row" role="toolbar" aria-label="按工段筛选">
                      <span className="lb">工段</span>
                      {[{ name: "", colorVar: "" }, ...d.phases].map((p) => (
                        <button key={p.name || "all"} type="button" className={`chip${phase === p.name ? " on" : ""}`} aria-pressed={phase === p.name} onClick={() => { setPhase(p.name); setPage(1); }}>
                          {p.name ? <><i className="phase-dot" style={{ background: `var(${p.colorVar})`, marginRight: 6 }} />{p.name}</> : "全部"}
                        </button>
                      ))}
                    </div>
                    <div className="row" role="toolbar" aria-label="按状态筛选">
                      <span className="lb">状态</span>
                      {["", ...d.statuses].map((s) => (
                        <button key={s || "all"} type="button" className={`chip${status === s ? " on" : ""}`} aria-pressed={status === s} onClick={() => { setStatus(s); setPage(1); }}>{s || "全部"}</button>
                      ))}
                    </div>
                    <div className="search"><input className="input" placeholder="搜索工序、检查要点或对策" aria-label="搜索" value={kw} onChange={(e) => { setKw(e.target.value); setPage(1); }} /></div>
                  </div>
                </div>
                {d.items.length ? (
                  <>
                    <div className="entries">
                      {d.items.map((e) => (
                        <EntryCard key={e.id} e={e} just={e.id === justId} foot={<>
                          <span className="mono">v{e.verNo}</span>
                          <span>· {e.reviewer} 审核 · {tm(e.reviewedAt)}</span>
                          {e.photoCount > 0 && <span>· <Icon name="camera" /> 附 {e.photoCount} 张照片</span>}
                          <span className="spacer" />
                          <button type="button" className="btn sm" onClick={() => setHistory(e)}>版本历史</button>
                          {e.canEdit && <button type="button" className="btn sm" onClick={() => setEditing(e)}>修改</button>}
                        </>} />
                      ))}
                    </div>
                    <div className="pager">
                      <span>共 {d.total} 条 · 每页 {d.pageSize} 条 · 第 {d.page} 页</span>
                      <button type="button" className="btn sm" disabled={d.page <= 1} onClick={() => setPage(d.page - 1)}>上一页</button>
                      <button type="button" className="btn sm" disabled={d.page >= pages} onClick={() => setPage(d.page + 1)}>下一页</button>
                    </div>
                  </>
                ) : filtered ? (
                  <div className="card"><div className="state"><h3>没有符合条件的条目</h3><p>换个工段或状态试试。</p><button type="button" className="btn" onClick={() => { setPhase(""); setStatus(""); setKw(""); }}>清除筛选</button></div></div>
                ) : (
                  <StateCard icon="book" title="还没有经验条目" text="质检可在问题页把已闭环的不一致问题提交到经验库。" />
                )}
              </>
            ) : (
              <>
                <div className="notice plain" style={{ marginBottom: "var(--space-4)" }}><span>待审核条目来自已闭环的不一致问题，提交时已自动脱敏。审核通过并选择状态后，条目对公司全部项目的成员可见。</span></div>
                {queue.data?.items.length ? (
                  <div className="entries">
                    {queue.data.items.map((e) => (
                      <EntryCard key={e.id} e={e} foot={<>
                        <span>提交人 {e.submitter} · {tm(e.createdAt)} · 来自已闭环的不一致问题</span>
                        <span>· {e.photoCount ? `附 ${e.photoCount} 张照片` : "未附带照片"}</span>
                        <span className="spacer" />
                        <button type="button" className="btn sm" onClick={() => setReviewing(e)}><Icon name="check" />审核</button>
                      </>} />
                    ))}
                  </div>
                ) : queue.isLoading ? null : <StateCard icon="check" title="没有待审核的条目" />}
              </>
            )}
          </>
        )}
      </div>
      {reviewing && me && (
        <ReviewFlow e={reviewing} reviewer={me.name} onClose={() => setReviewing(null)} onDone={(x) => {
          setReviewing(null);
          setJustId(x.id);
          toast("已审核，全公司项目可见");
          refresh();
        }} />
      )}
      {editing && d && (
        <EditDialog e={editing} issueTypes={d.issueTypes} onClose={() => setEditing(null)} onDone={(x) => {
          setEditing(null);
          setJustId(x.id);
          toast(`已保存为 v${x.verNo}，旧版本保留可查`);
          refresh();
        }} />
      )}
      {history && <HistoryDialog e={history} onClose={() => setHistory(null)} />}
    </Shell>
  );
}

function ReviewFlow({ e, reviewer, onClose, onDone }: { e: Entry; reviewer: string; onClose: () => void; onDone: (x: Entry) => void }) {
  const toast = useToast();
  const [st, setSt] = useState("");
  const [err, setErr] = useState("");
  const [step, setStep] = useState<1 | 2>(1);
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try {
      onDone(await api<Entry>(`/experience/${e.id}/review`, { body: { status: st } }));
    } catch (ex) {
      toast((ex as ApiError).message);
      onClose();
    } finally {
      setBusy(false);
    }
  }
  if (step === 2) {
    return (
      <ConfirmDialog title="确认审核" confirmText="审核通过" busy={busy} onConfirm={submit} onClose={onClose}
        summary={[["条目", `${e.phaseName} · ${e.process}`], ["状态", st], ["审核人", reviewer], ["时间", bj().format("YYYY-MM-DD HH:mm")], ["可见范围", "审核后对公司全部项目成员可见"]]} />
    );
  }
  return (
    <Modal title="审核经验条目" onClose={onClose} footer={<>
      <button type="button" className="btn" onClick={onClose}>取消</button>
      <button type="button" className="btn primary" onClick={() => (st ? setStep(2) : setErr("请选择一个状态"))}>下一步</button>
    </>}>
      <div className="exp-dlg" style={{ display: "grid", gap: "var(--space-3)" }}>
        <dl className="ro">
          <dt>工段 · 工序</dt><dd>{e.phaseName} · {e.process}</dd>
          <dt>问题类型</dt><dd>{e.issueType}</dd>
          <dt>检查要点</dt><dd>{e.checkPoint}</dd>
          <dt>对策</dt><dd>{e.countermeasure}</dd>
          <dt>提交</dt><dd>{e.submitter} · {tm(e.createdAt)} · {e.photoCount ? `附 ${e.photoCount} 张照片` : "未附带照片"}</dd>
        </dl>
        <fieldset className={`field${err ? " invalid" : ""}`}>
          <label>审核结论：选择状态 <span className="req">*</span></label>
          <div className="radios">
            {STATUS_DESC.map(([k, v]) => (
              <label key={k}><input type="radio" name="rvSt" checked={st === k} onChange={() => { setSt(k); setErr(""); }} /><span><b>{k}</b><small>{v}</small></span></label>
            ))}
          </div>
          {err && <span className="err">{err}</span>}
        </fieldset>
      </div>
    </Modal>
  );
}

function EditDialog({ e, issueTypes, onClose, onDone }: { e: Entry; issueTypes: string[]; onClose: () => void; onDone: (x: Entry) => void }) {
  const [f, setF] = useState({ process: e.process, issueType: e.issueType, checkPoint: e.checkPoint, countermeasure: e.countermeasure, status: e.status, changeNote: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (ev: { target: { value: string } }) => setF((x) => ({ ...x, [k]: ev.target.value }));
  const types = issueTypes.includes(f.issueType) ? issueTypes : [f.issueType, ...issueTypes];
  async function save() {
    const er: Record<string, string> = {};
    if (!f.process.trim()) er.process = "请填写工序";
    if (!f.checkPoint.trim()) er.checkPoint = "请填写检查要点";
    if (!f.countermeasure.trim()) er.countermeasure = "请填写对策";
    if (!f.changeNote.trim()) er.changeNote = "请填写修改说明";
    setErrs(er);
    if (Object.keys(er).length) return;
    setBusy(true);
    try {
      onDone(await api<Entry>(`/experience/${e.id}/versions`, { body: f }));
    } catch (ex) {
      const a = ex as ApiError;
      setErrs(a.fields.length ? a.fieldMap() : { changeNote: a.message });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="修改经验条目" onClose={onClose} footer={<>
      <button type="button" className="btn" onClick={onClose}>取消</button>
      <button type="button" className="btn primary" disabled={busy} onClick={save}>保存为新版本</button>
    </>}>
      <div className="notice plain"><span>保存后生成新版本，旧版本保留可查。</span></div>
      <Field label="工序" required error={errs.process}><input className="input" value={f.process} onChange={set("process")} /></Field>
      <Field label="问题类型" required error={errs.issueType}>
        <select className="select" value={f.issueType} onChange={set("issueType")}>{types.map((t) => <option key={t}>{t}</option>)}</select>
      </Field>
      <Field label="检查要点" required error={errs.checkPoint}><textarea className="textarea" rows={3} value={f.checkPoint} onChange={set("checkPoint")} /></Field>
      <Field label="对策" required error={errs.countermeasure}><textarea className="textarea" rows={3} value={f.countermeasure} onChange={set("countermeasure")} /></Field>
      <Field label="状态" required error={errs.status}>
        <select className="select" value={f.status} onChange={set("status")}>{STATUS_DESC.map(([k]) => <option key={k}>{k}</option>)}</select>
      </Field>
      <Field label="修改说明" required error={errs.changeNote}><input className="input" placeholder="例如：三个工地复核有效，改为已验证" value={f.changeNote} onChange={set("changeNote")} /></Field>
    </Modal>
  );
}

function HistoryDialog({ e, onClose }: { e: Entry; onClose: () => void }) {
  const q = useQuery({ queryKey: ["experience", "versions", e.id], queryFn: () => api<{ items: Ver[]; current: number }>(`/experience/${e.id}/versions`) });
  return (
    <Modal title={`版本历史 · ${e.phaseName} · ${e.process}`} onClose={onClose} footer={<button type="button" className="btn" onClick={onClose}>关闭</button>}>
      <div className="exp-dlg">
        {q.isLoading ? <div className="skeleton" /> : q.isError ? <div className="notice bad"><span>版本历史加载失败，请重试</span></div> : (
          <ul className="vlist">
            {q.data!.items.map((v) => (
              <li key={v.verNo}>
                <div className="vh"><b>v{v.verNo}</b>{v.verNo === q.data!.current && <span className="tag brand">当前</span>}<StatusSeal st={v.status} /><span className="hint">{tm(v.at)} · {v.author}</span></div>
                {v.changeNote && <div className="hint" style={{ marginTop: "var(--space-1)" }}>{v.changeNote}</div>}
                <details>
                  <summary>查看该版本内容</summary>
                  <dl>
                    <dt>工序 · 问题类型</dt><dd>{v.process} · {v.issueType}</dd>
                    <dt>检查要点</dt><dd>{v.checkPoint}</dd>
                    <dt>对策</dt><dd>{v.countermeasure}</dd>
                  </dl>
                </details>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Modal>
  );
}
