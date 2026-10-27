// PAGE-F15-01 · 付款节点（REQ-F15-01/02：预算专员维护；每个节点显示关联工段未放行检查点数与未闭环不一致数；只提示不拦截）
import { useState } from "react";
import { Link, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, idemKey } from "../api";
import { Shell } from "../layout/Shell";
import { useProject } from "../session";
import { ConfirmDialog, ErrorState, Field, Icon, Modal, Seal, useApiError, useToast } from "../ui";
import "../styles/pages/PAGE-F15-01.css";

type Node = {
  id: number; name: string; amount: number | string; plannedOn: string; phases: { id: number; name: string; colorVar: string }[];
  unreleased: number; openIssues: number; status: "未付" | "已付"; paidAt: string | null; paidBy: string | null; paidConfirmedUnreleased: number | null;
};
type Data = { items: Node[]; total: number; paidCount: number };
const yuan = (v: number | string) => Number(v).toLocaleString("zh-CN");
const hm = (s: string | null) => (s ? `${s.slice(0, 10)} ${s.slice(11, 16)}` : "");
const EMPTY = { name: "", amount: "", plannedOn: "", phaseIds: [] as number[] };

export default function Payments() {
  const { pid } = useParams();
  const { project, can } = useProject(pid);
  const toast = useToast();
  const onErr = useApiError();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["payments", pid], queryFn: () => api<Data>(`/projects/${pid}/payments`), enabled: !!pid });
  const canPay = can("payment.edit");
  const [just, setJust] = useState<number | null>(null);
  const [paying, setPaying] = useState<Node | null>(null);

  const markPaid = useMutation({
    mutationFn: (n: Node) => api<Node>(`/projects/${pid}/payments/${n.id}/mark-paid`, { body: { confirmUnreleased: n.unreleased }, headers: { "Idempotency-Key": idemKey() } }),
    onSuccess: (n) => {
      setPaying(null);
      setJust(n.id);
      toast(`${n.name} 已标记为已付`);
      qc.invalidateQueries({ queryKey: ["payments", pid] });
    },
    onError: (e, n) => {
      const err = e as ApiError;
      if (err.code === "CONFIRM_UNRELEASED") {
        // 确认期间未放行数变化：按服务端最新的 N 重新确认
        setPaying({ ...n, unreleased: Number(err.details.unreleased), openIssues: Number(err.details.openIssues) });
        toast(err.message);
        return;
      }
      setPaying(null);
      onErr(e);
    },
  });

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: () => api<Node>(`/projects/${pid}/payments`, { body: { ...form, amount: Number(form.amount) } }),
    onSuccess: () => { setOpen(false); toast("已保存付款节点，状态：未付"); qc.invalidateQueries({ queryKey: ["payments", pid] }); },
    onError: (e) => { const m = (e as ApiError).fieldMap?.(); if (m && Object.keys(m).length) setErrs(m); else onErr(e); },
  });
  const submit = () => {
    const e: Record<string, string> = {};
    if (!form.name.trim()) e.name = "请填写节点名称";
    const am = Number(form.amount);
    if (!(am > 0) || !Number.isInteger(am)) e.amount = "请填写大于 0 的金额";
    if (!form.plannedOn) e.plannedOn = "请选择计划日期";
    if (!form.phaseIds.length) e.phaseIds = "请至少选择 1 个关联工段";
    setErrs(e);
    if (!Object.keys(e).length) create.mutate();
  };
  const togglePhase = (id: number) => setForm((f) => ({ ...f, phaseIds: f.phaseIds.includes(id) ? f.phaseIds.filter((x) => x !== id) : [...f.phaseIds, id] }));
  const openAdd = () => { setForm(EMPTY); setErrs({}); setOpen(true); };

  const phasesHtml = (n: Node) => n.phases.map((p) => <span key={p.id} className="ph"><span className="phase-dot" style={{ background: `var(${p.colorVar})` }} />{p.name}</span>);
  const cnt = (v: number, to: string, label: string) => <Link className={`cnt ${v ? "hot" : "zero"}`} to={to} aria-label={`${label} ${v}`}>{v}</Link>;
  const seal = (n: Node) => (
    <>
      <Seal kind={n.status === "已付" ? "pass" : "pend"} just={just === n.id}>{n.status}</Seal>
      {n.status === "已付" && <div className="paid-meta">{n.paidBy} · {hm(n.paidAt)}{n.paidConfirmedUnreleased ? ` · 确认时未放行 ${n.paidConfirmedUnreleased} 个` : ""}</div>}
    </>
  );
  const cpLink = `/p/${pid}/checkpoints`;
  const issueLink = `/p/${pid}/issues`;
  const data = q.data;

  return (
    <Shell title="付款节点" sub={`${project?.name || ""} · 付款前看清证据链是否齐全`}
      actions={canPay && <button className="btn primary" type="button" onClick={openAdd}><Icon name="plus" />录入付款节点</button>}>
      <div className="notice info pay-note"><Icon name="alert" /><span>付款节点只做提示，不拦截付款：每个节点显示关联工段内未放行的检查点数和未闭环的不一致问题数，付款前看清证据链是否齐全。</span></div>
      <section className="card" aria-labelledby="ndTitle">
        <div className="card-hd" style={{ flexWrap: "wrap" }}><h2 id="ndTitle">付款节点</h2>{data && <span className="tag">共 {data.total} 个 · 已付 {data.paidCount}</span>}</div>
        {q.isLoading ? (
          <div className="card-bd" aria-busy="true"><div className="skeleton" style={{ width: "45%", marginBottom: 12 }} /><div className="skeleton" style={{ marginBottom: 12 }} /><div className="skeleton" style={{ width: "60%" }} /></div>
        ) : q.error || !data ? (
          <ErrorState error={q.error} retry={() => q.refetch()} />
        ) : !data.items.length ? (
          <div className="state pay-state">
            <div className="ic"><Icon name="money" /></div>
            <h3>还没有付款节点</h3><p>按合同录入付款节点后，这里会显示每个节点关联工段的证据链情况。</p>
            {canPay && <button className="btn" type="button" onClick={openAdd}><Icon name="plus" />录入付款节点</button>}
          </div>
        ) : (
          <>
            <div className="nd-table scroll-x">
              <table>
                <thead><tr><th>节点</th><th className="num">金额（元）</th><th>计划日期</th><th>关联工段</th><th className="num">未放行检查点</th><th className="num">未闭环不一致</th><th>状态</th>{canPay && <th />}</tr></thead>
                <tbody>
                  {data.items.map((n) => (
                    <tr key={n.id}>
                      <td><div className="nd-name">{n.name}</div></td>
                      <td className="num">{yuan(n.amount)}</td>
                      <td className="num">{n.plannedOn}</td>
                      <td>{phasesHtml(n)}</td>
                      <td className="num">{cnt(n.unreleased, cpLink, "未放行检查点")}</td>
                      <td className="num">{cnt(n.openIssues, issueLink, "未闭环不一致")}</td>
                      <td>{seal(n)}</td>
                      {canPay && <td>{n.status === "未付" && <button className="btn sm" type="button" onClick={() => setPaying(n)}>标记已付</button>}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="nd-cards">
              {data.items.map((n) => (
                <div key={n.id} className="nd-card">
                  <div className="l1"><div><div className="nd-name">{n.name}</div><div className="nd-sub">计划 {n.plannedOn}</div></div><div style={{ textAlign: "right" }}>{seal(n)}</div></div>
                  <div className="amt">{yuan(n.amount)} 元</div>
                  <div>{phasesHtml(n)}</div>
                  <div className="stats">
                    <div className="stat">未放行检查点{cnt(n.unreleased, cpLink, "未放行检查点")}</div>
                    <div className="stat">未闭环不一致{cnt(n.openIssues, issueLink, "未闭环不一致")}</div>
                  </div>
                  {canPay && n.status === "未付" && <button className="btn block" type="button" onClick={() => setPaying(n)}>标记已付</button>}
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      {paying && (
        <ConfirmDialog title={paying.unreleased ? `还有 ${paying.unreleased} 个检查点未放行，确认标记已付？` : "确认标记已付？"}
          confirmText="确认标记已付" busy={markPaid.isPending} onClose={() => setPaying(null)} onConfirm={() => markPaid.mutate(paying)}
          warn={paying.unreleased ? "付款提示不拦截：仍可标记已付，本次确认会记入留痕。" : undefined}
          summary={[["付款节点", paying.name], ["金额", `${yuan(paying.amount)} 元`], ["关联工段", paying.phases.map((p) => p.name).join("、")],
            ["未放行检查点", `${paying.unreleased} 个`], ["未闭环不一致问题", `${paying.openIssues} 个`], ["标记后", "状态改为「已付」并留痕，不可撤回"]]} />
      )}
      {open && (
        <Modal title="录入付款节点" onClose={() => setOpen(false)} footer={<>
          <button className="btn" type="button" onClick={() => setOpen(false)}>取消</button>
          <button className="btn primary" type="button" disabled={create.isPending} onClick={submit}>保存</button>
        </>}>
          <div className="form-grid">
            <Field label="节点名称" required error={errs.name} full>
              <input className="input" maxLength={60} value={form.name} placeholder="例如：水电完工款" onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label="金额（元）" required error={errs.amount}>
              <input className="input num" type="number" min={1} step={1} inputMode="numeric" placeholder="例如 253600" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
            </Field>
            <Field label="计划日期" required error={errs.plannedOn}>
              <input className="input" type="date" value={form.plannedOn} onChange={(e) => setForm({ ...form, plannedOn: e.target.value })} />
            </Field>
            <Field label="关联工段（可多选）" required error={errs.phaseIds} full>
              <div className="phs">
                {(project?.phases || []).map((p) => (
                  <label key={p.id} className="phchk"><input type="checkbox" checked={form.phaseIds.includes(p.id)} onChange={() => togglePhase(p.id)} />
                    <span className="phase-dot" style={{ background: `var(${p.colorVar})` }} />{p.name}</label>
                ))}
              </div>
            </Field>
          </div>
        </Modal>
      )}
    </Shell>
  );
}
