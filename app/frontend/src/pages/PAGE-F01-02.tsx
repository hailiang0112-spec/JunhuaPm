// PAGE-F01-02 · 成员与项目（F01 成员角色、代理人、项目状态、放行时限；F02 邀请与重置密码）
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { bj } from "../time";
import { api, ApiError } from "../api";
import { Shell } from "../layout/Shell";
import { useProject, useSession } from "../session";
import { ConfirmDialog, Field, Icon, Modal, Seal, useToast } from "../ui";
import { fmtPhone, ROLE_OPTIONS, StateCard, useCopy } from "../acct";
import "../styles/pages/PAGE-F01-02.css";

type Member = { id: number; name: string; phone: string; roles: string[]; roleLabels: string[]; joinedAt: string; isAgent: boolean };
type Hist = { action: string; actor: string; at: string; label: string; before: Record<string, string> | null; after: Record<string, string> | null };
type MembersResp = {
  items: Member[]; phoneFull: boolean; agent: { id: number; name: string; grantedAt: string; grantedBy: string | null; proxyReleases: number } | null;
  agentHistory: Hist[]; statusHistory: Hist[];
};
type Inv = { id: number; phone: string; roles: string[]; roleLabels: string[]; state: string; createdBy: string; createdAt: string; expiresAt: string; canRevoke: boolean; link?: string };
type Confirm = { title: string; summary: [string, ReactNode][]; confirmText: string; danger?: boolean; run: () => Promise<void> };

const t = (s: string) => bj(s).format("YYYY-MM-DD HH:mm");
const INV_SEAL: Record<string, ["pass" | "stop" | "pend", string]> = { 有效: ["pend", "待使用"], 已使用: ["pass", "已使用"], 已过期: ["stop", "已过期"], 已撤销: ["stop", "已撤销"] };

function RoleTags({ m }: { m: Member }) {
  return (
    <div className="tags">
      {m.roles.map((r, i) => (
        <span key={r} className={`tag${r === "owner" ? " brand" : r === "owner_agent" ? " ok" : ""}`}>{m.roleLabels[i]}</span>
      ))}
    </div>
  );
}

function statusLine(h: Hist) {
  if (h.action === "project.create") return `${h.actor} 创建（筹备）`;
  const a = h.after || {};
  return `${h.actor} 推进为「${a.status}」` + (a.actualHandover ? `，实际交房 ${a.actualHandover}` : "");
}
function agentLine(h: Hist) {
  if (h.action === "agent.revoke") return `${h.actor} 撤销 ${h.before?.agent ?? ""} 的代理人身份`;
  return h.before?.agent ? `${h.actor} 将代理人由 ${h.before.agent} 更换为 ${h.after?.agent}` : `${h.actor} 指定 ${h.after?.agent} 为业主代理人`;
}

export default function Members() {
  const { pid = "" } = useParams();
  const { me } = useSession();
  const { project, can, error: projErr, isLoading: projLoading } = useProject(pid);
  const qc = useQueryClient();
  const toast = useToast();
  const { copy, dialog: copyDialog } = useCopy();
  const mq = useQuery({ queryKey: ["members", pid], queryFn: () => api<MembersResp>(`/projects/${pid}/members`), enabled: !!project });
  const iq = useQuery({ queryKey: ["invitations", pid], queryFn: () => api<{ items: Inv[] }>(`/projects/${pid}/invitations`), enabled: !!project });
  const [links, setLinks] = useState<Record<number, string>>({});
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [busy, setBusy] = useState(false);
  const [inviting, setInviting] = useState(false);
  const [editing, setEditing] = useState<Member | null>(null);
  const [picking, setPicking] = useState(false);
  const [delivering, setDelivering] = useState(false);
  const [temp, setTemp] = useState<{ who: string; pwd: string } | null>(null);
  const [timeout, setTimeoutVal] = useState("");
  const [timeoutErr, setTimeoutErr] = useState("");
  const [justStatus, setJustStatus] = useState(false);

  if ((projErr as ApiError | null)?.status === 403) return <Navigate to="/forbidden" replace />;
  const admin = !!me?.isCompanyAdmin;
  const isOwner = !!project?.roles.includes("owner");
  const ownerOnly = isOwner && !project?.roles.some((r) => r === "pm" || r === "admin");
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["members", pid] });
    qc.invalidateQueries({ queryKey: ["invitations", pid] });
    qc.invalidateQueries({ queryKey: ["project", pid] });
  };
  async function runConfirm() {
    if (!confirm) return;
    setBusy(true);
    try {
      await confirm.run();
      setConfirm(null);
    } catch (e) {
      toast((e as ApiError).message || "操作失败");
    } finally {
      setBusy(false);
    }
  }

  const data = mq.data;
  const members = data?.items || [];
  const agent = data?.agent;
  const candidates = members.filter((m) => !m.roles.includes("owner") && m.id !== agent?.id);
  const days = project ? dayjs(project.plannedHandover).diff(dayjs(project.plannedStart), "day") + 1 : 0;

  const askRemove = (m: Member) => setConfirm({
    title: "移除成员", confirmText: "确认移除", danger: true,
    summary: [["成员", `${m.name}（${m.roleLabels.join("、")}）`], ["访问", "下一次请求起无法访问本项目"],
      ["历史记录", "已有的签认、核对、放行、变更、问题和留言保留原署名，内容不变"], ...(m.isAgent ? [["代理人", "其业主代理人身份同时撤销"] as [string, ReactNode]] : [])],
    run: async () => {
      await api(`/projects/${pid}/members/${m.id}`, { method: "DELETE" });
      toast(`已移除 ${m.name}`);
      refresh();
    },
  });
  const askReset = (m: Member) => setConfirm({
    title: "重置密码", confirmText: "确认重置", danger: true,
    summary: [["成员", `${m.name} · ${fmtPhone(m.phone)}`], ["结果", "生成一次性临时密码，原密码立即失效"], ["下次登录", "必须先设置新密码才能进行其他操作"], ["留痕", "重置动作记入操作日志"]],
    run: async () => {
      const r = await api<{ tempPassword: string; userName: string }>(`/admin/users/${m.id}/reset-password`, { method: "POST" });
      setTemp({ who: `${m.name}（${fmtPhone(m.phone)}）的临时密码：`, pwd: r.tempPassword });
    },
  });
  const askRevokeInv = (v: Inv) => setConfirm({
    title: "撤销邀请", confirmText: "确认撤销", danger: true,
    summary: [["手机号", fmtPhone(v.phone)], ["角色", v.roleLabels.join("、")], ["生成时间", t(v.createdAt)], ["撤销后", "该链接立即失效，打开时显示「邀请已失效，请联系邀请人重新发送」"]],
    run: async () => {
      await api(`/projects/${pid}/invitations/${v.id}/revoke`, { method: "POST" });
      toast("邀请已撤销");
      refresh();
    },
  });
  const askRevokeAgent = () => agent && setConfirm({
    title: "撤销业主代理人", confirmText: "确认撤销", danger: true,
    summary: [["代理人", agent.name], ["生效", "从下一次请求起不能放行检查点"], ["已有记录", `已完成的 ${agent.proxyReleases} 次放行保持不变，标注「代理放行」`]],
    run: async () => {
      await api(`/projects/${pid}/agent`, { method: "DELETE" });
      toast("已撤销代理人");
      refresh();
    },
  });
  const askAgent = (m: Member) => setConfirm({
    title: agent ? "确认更换代理人" : "确认指定代理人", confirmText: "确认",
    summary: [["新代理人", m.name], ...(agent ? [["原代理人", `${agent.name} 的放行权限将立即撤销`] as [string, ReactNode]] : []), ["权限", "只能放行检查点，不能签认基线、图纸版本和变更单"]],
    run: async () => {
      await api(`/projects/${pid}/agent`, { body: { userId: m.id } });
      toast(`业主代理人已设为 ${m.name}`);
      refresh();
    },
  });
  const askAdvance = (target: string, actual?: string) => setConfirm({
    title: "推进项目状态", confirmText: "确认推进",
    summary: [["项目", project?.name ?? ""], ["状态", `${project?.status} → ${target}`], ...(actual ? [["实际交房日期", actual] as [string, ReactNode]] : []), ["说明", "推进后不可回退，并记录操作人与时间"]],
    run: async () => {
      await api(`/projects/${pid}/status`, { body: { status: target, actualHandover: actual } });
      setJustStatus(true);
      toast(`项目状态已更新为${target}`);
      refresh();
    },
  });

  async function saveTimeout(e: FormEvent) {
    e.preventDefault();
    const n = Number(timeout);
    if (!/^\d+$/.test(timeout.trim()) || n < 1 || n > 72) {
      setTimeoutErr("请输入 1–72 之间的整数");
      return;
    }
    setTimeoutErr("");
    try {
      await api(`/projects/${pid}/settings`, { method: "PUT", body: { releaseTimeoutHours: n } });
      toast(`放行时限已改为 ${n} 小时`);
      setTimeoutVal("");
      refresh();
    } catch (ex) {
      setTimeoutErr((ex as ApiError).fieldMap?.().releaseTimeoutHours || (ex as ApiError).message);
    }
  }

  const statusSeal = project && (project.status === "已交房" ? <Seal kind="pass" just={justStatus}>已交房</Seal> : project.status === "筹备" ? <Seal kind="pend" just={justStatus}>筹备</Seal> : <span className={`seal plain${justStatus ? " just" : ""}`}>施工中</span>);
  const actions = (
    <>
      <Link className="btn" to={`/p/${pid}/issues`}><Icon name="alert" />登记问题</Link>
      {can("invitation.create") && <button type="button" className="btn primary" onClick={() => setInviting(true)}><Icon name="plus" />生成邀请</button>}
    </>
  );

  return (
    <Shell title="成员与项目" sub={project?.name} actions={project ? actions : undefined}>
      <div className="pg-members">
        {projLoading || mq.isLoading ? (
          <div className="card"><div className="card-bd" style={{ display: "grid", gap: "var(--space-3)" }}>{[40, 100, 85, 70, 90].map((w, i) => <div key={i} className="skeleton" style={{ width: `${w}%` }} />)}</div></div>
        ) : mq.isError || !project ? (
          <StateCard icon="alert" title="成员信息加载失败（网络中断），请重试" action={<button type="button" className="btn" onClick={() => mq.refetch()}>重试</button>} />
        ) : (
          <div className="cols">
            <div className="col">
              <section className="card o1" aria-labelledby="memHd">
                <div className="card-hd"><h2 id="memHd">成员</h2><span className="hint">{members.length} 人</span><span className="spacer" /><span className="hint">角色只在本项目生效</span></div>
                {members.length ? members.map((m) => (
                  <div className="mrow" key={m.id}>
                    <div><div className="nm2">{m.name}</div><RoleTags m={m} /></div>
                    <div><div className="mono">{fmtPhone(m.phone)}</div><div className="m">加入 {m.joinedAt}</div></div>
                    <div className="acts">
                      {can("member.manage") && <>
                        <button type="button" className="btn sm" onClick={() => setEditing(m)}>编辑角色</button>
                        {admin && <button type="button" className="btn sm" onClick={() => askReset(m)}><Icon name="lock" />重置密码</button>}
                        <button type="button" className="btn sm danger" onClick={() => askRemove(m)}>移除</button>
                      </>}
                    </div>
                  </div>
                )) : (
                  <div className="state"><div>还没有成员。生成邀请链接，把业主、项目经理等各方拉进项目。</div></div>
                )}
              </section>
              <section className="card o5" aria-labelledby="invHd">
                <div className="card-hd"><h2 id="invHd">邀请记录</h2><span className="spacer" /><span className="hint">一次性 · 7 天有效</span></div>
                {iq.data?.items.length ? (
                  <div className="scroll-x">
                    <table className="itable">
                      <thead><tr><th>手机号</th><th>角色</th><th>邀请人</th><th>生成时间</th><th>有效期至</th><th>状态</th><th>操作</th></tr></thead>
                      <tbody>
                        {iq.data.items.map((v) => {
                          const [k, label] = INV_SEAL[v.state];
                          return (
                            <tr key={v.id}>
                              <td className="mono">{fmtPhone(v.phone)}</td><td>{v.roleLabels.join("、")}</td><td>{v.createdBy}</td>
                              <td className="mono">{t(v.createdAt)}</td><td className="mono">{t(v.expiresAt)}</td>
                              <td><Seal kind={k}>{label}</Seal></td>
                              <td>{v.canRevoke ? (
                                <div className="row" style={{ flexWrap: "nowrap" }}>
                                  {links[v.id] && <button type="button" className="btn sm" onClick={() => copy(location.origin + links[v.id], "已复制")}><Icon name="copy" />复制</button>}
                                  <button type="button" className="btn sm danger" onClick={() => askRevokeInv(v)}>撤销</button>
                                </div>
                              ) : <span className="hint">—</span>}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : <div className="state">还没有邀请记录</div>}
              </section>
            </div>
            <div className="col">
              <section className="card o2" aria-labelledby="pxHd">
                <div className="card-hd"><h2 id="pxHd">业主代理人</h2><span className="spacer" /><span className="hint">最多 1 名</span></div>
                <div className="card-bd">
                  {agent ? (
                    <div className="proxy"><span className="avatar">{agent.name.slice(0, 1)}</span>
                      <div><div style={{ fontWeight: 600 }}>{agent.name} <span className="tag info">业主代理人</span></div><div className="hint">已代理放行 {agent.proxyReleases} 次</div></div>
                    </div>
                  ) : <div className="hint">未指定代理人。业主不在现场时，可指定一名成员代为放行检查点。</div>}
                  <p className="hint" style={{ marginTop: "var(--space-3)" }}>代理人只能放行检查点，不能签认基线、图纸版本和变更单。</p>
                  {!!data?.agentHistory.length && (
                    <ul className="timeline">{data.agentHistory.map((h, i) => <li key={i}><span className="when">{t(h.at)}</span>{agentLine(h)}</li>)}</ul>
                  )}
                </div>
                {can("agent.assign") && (
                  <div className="card-ft">
                    <button type="button" className="btn" onClick={() => setPicking(true)}>{agent ? "更换代理人" : "指定代理人"}</button>
                    {agent && <button type="button" className="btn danger" onClick={askRevokeAgent}>撤销代理</button>}
                  </div>
                )}
              </section>
              <section className="card o3" aria-labelledby="stHd">
                <div className="card-hd"><h2 id="stHd">项目状态</h2><span className="spacer" />{statusSeal}</div>
                <div className="card-bd">
                  <dl className="kv">
                    <dt>计划工期</dt><dd className="mono">{project.plannedStart} ~ {project.plannedHandover}（{days} 天）</dd>
                    <dt>实际交房</dt><dd className="mono">{project.actualHandover || "—"}</dd>
                  </dl>
                  {!!data?.statusHistory.length && (
                    <ul className="timeline">{data.statusHistory.map((h, i) => <li key={i}><span className="when">{bj(h.at).format("YYYY-MM-DD")}</span>{statusLine(h)}</li>)}</ul>
                  )}
                </div>
                {can("project.status") && project.status !== "已交房" && (
                  <div className="card-ft">
                    {project.status === "筹备"
                      ? <button type="button" className="btn" onClick={() => askAdvance("施工中")}>推进为施工中</button>
                      : <button type="button" className="btn" onClick={() => setDelivering(true)}>推进为已交房</button>}
                  </div>
                )}
              </section>
              <section className="card o4" aria-labelledby="tlHd">
                <div className="card-hd"><h2 id="tlHd">放行时限</h2></div>
                <div className="card-bd">
                  <div className="bigval">{project.releaseTimeoutHours}<small>小时{project.releaseTimeoutHours === 24 ? "（默认）" : ""}</small></div>
                  <p className="hint" style={{ marginTop: "var(--space-2)" }}>检查点进入待放行后超过时限仍未放行，会在业主、业主代理人和项目经理的待办中标为「超时」并置顶。不会自动放行。</p>
                  {can("release_timeout.set") && (
                    <form className="inline-edit" onSubmit={saveTimeout} noValidate>
                      <Field label="修改为（1–72）" error={timeoutErr}>
                        <input className="input" id="tlInput" type="number" min={1} max={72} step={1} inputMode="numeric" placeholder={String(project.releaseTimeoutHours)} value={timeout} onChange={(e) => setTimeoutVal(e.target.value)} />
                      </Field>
                      <button className="btn" type="submit" style={{ marginTop: 22 }}>保存</button>
                    </form>
                  )}
                </div>
              </section>
            </div>
          </div>
        )}
      </div>

      {inviting && project && (
        <InviteDialog pid={pid} ownerOnly={ownerOnly} canAdmin={!ownerOnly} projectName={project.name}
          onClose={() => setInviting(false)}
          onCreated={(v) => { setLinks((x) => ({ ...x, [v.id]: v.link! })); refresh(); }}
          onCopy={(link) => copy(location.origin + link, "已复制")} />
      )}
      {editing && <RolesDialog pid={pid} m={editing} projectName={project?.name ?? ""} onClose={() => setEditing(null)} onDone={() => { toast(`已更新 ${editing.name} 的角色`); setEditing(null); refresh(); }} />}
      {picking && (
        <PickAgent candidates={candidates} onClose={() => setPicking(false)} onNext={(m) => { setPicking(false); askAgent(m); }} />
      )}
      {delivering && (
        <DeliverDialog onClose={() => setDelivering(false)} onNext={(d) => { setDelivering(false); askAdvance("已交房", d); }} />
      )}
      {temp && (
        <Modal title="临时密码已生成" onClose={() => setTemp(null)} footer={<>
          <button type="button" className="btn" onClick={() => setTemp(null)}>关闭</button>
          <button type="button" className="btn primary" onClick={() => copy(temp.pwd, "已复制")}><Icon name="copy" />复制临时密码</button>
        </>}>
          <div className="hint">{temp.who}</div>
          <div className="temp-pwd">{temp.pwd}</div>
          <div className="notice warn"><span>临时密码只显示这一次，关闭后无法再次查看，也不会写入任何日志。请当面或电话告知本人。该成员用临时密码登录后必须先设置新密码。本次重置动作已记入操作日志（不含临时密码）。</span></div>
        </Modal>
      )}
      {confirm && <ConfirmDialog title={confirm.title} summary={confirm.summary} confirmText={confirm.confirmText} danger={confirm.danger} busy={busy} onConfirm={runConfirm} onClose={() => setConfirm(null)} />}
      {copyDialog}
    </Shell>
  );
}

function InviteDialog({ pid, ownerOnly, canAdmin, onClose, onCreated, onCopy }: {
  pid: string; ownerOnly: boolean; canAdmin: boolean; projectName: string; onClose: () => void; onCreated: (v: Inv) => void; onCopy: (link: string) => void;
}) {
  const options: [string, string][] = ownerOnly ? [["owner_member", "业主方成员"]]
    : [...ROLE_OPTIONS.map(([k, v]): [string, string] => [k, k === "owner_member" ? "业主方成员（仅查看，可被指定为代理人）" : v]), ...(canAdmin ? [["admin", "公司管理员"] as [string, string]] : [])];
  const [phone, setPhone] = useState("");
  const [roles, setRoles] = useState<string[]>(ownerOnly ? ["owner_member"] : []);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Inv | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const p = phone.replace(/\s/g, "");
    const er: Record<string, string> = {};
    if (!/^\d{11}$/.test(p)) er.phone = "请输入 11 位手机号";
    if (!roles.length) er.roles = "请至少选择一个角色";
    setErrs(er);
    if (Object.keys(er).length) return;
    setBusy(true);
    try {
      const v = await api<Inv>(`/projects/${pid}/invitations`, { body: { phone: p, roles } });
      setRes(v);
      onCreated(v);
    } catch (ex) {
      const a = ex as ApiError;
      setErrs(a.fields.length ? a.fieldMap() : { roles: a.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="生成邀请链接" onClose={onClose} footer={res ? <>
      <button type="button" className="btn" onClick={onClose}>完成</button>
      <button type="button" className="btn primary" onClick={() => onCopy(res.link!)}><Icon name="copy" />复制链接</button>
    </> : <>
      <button type="button" className="btn" onClick={onClose}>取消</button>
      <button type="submit" form="invForm" className="btn primary" disabled={busy}>{busy ? "生成中…" : "生成链接"}</button>
    </>}>
      {res ? (
        <>
          <div className="notice info"><span>已为 {res.phone} 生成邀请，角色：{res.roleLabels.join("、")}</span></div>
          <div className="linkbox"><span style={{ flex: 1 }}>{location.origin + res.link}</span></div>
          <div className="hint">仅可使用一次，{t(res.expiresAt)} 前有效</div>
        </>
      ) : (
        <form id="invForm" noValidate onSubmit={submit} style={{ display: "grid", gap: "var(--space-3)" }}>
          <Field label="被邀请人手机号" required error={errs.phone}>
            <input className="input" id="iPhone" type="tel" inputMode="numeric" maxLength={13} placeholder="11 位手机号" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </Field>
          <Field label="角色（可多选）" required error={errs.roles}>
            <div className="checks">
              {options.map(([k, label]) => (
                <label key={k}><input type="checkbox" checked={roles.includes(k)} onChange={(e) => setRoles((x) => e.target.checked ? [...x, k] : x.filter((r) => r !== k))} />{label}</label>
              ))}
            </div>
          </Field>
          {ownerOnly && <div className="notice plain"><span>业主只能邀请「业主方成员」（如家人、自聘监理）。业主方成员只能查看本项目，被你指定为业主代理人后才能放行检查点。</span></div>}
          <div className="hint">链接仅可使用一次，7 天内有效。被邀请人需用该手机号设置密码后加入。</div>
        </form>
      )}
    </Modal>
  );
}

function RolesDialog({ pid, m, projectName, onClose, onDone }: { pid: string; m: Member; projectName: string; onClose: () => void; onDone: () => void }) {
  const [roles, setRoles] = useState<string[]>(m.roles.filter((r) => r !== "owner_agent"));
  const [err, setErr] = useState("");
  async function save() {
    if (!roles.length) {
      setErr("请至少保留一个角色；如需移出项目请使用「移除」");
      return;
    }
    try {
      await api(`/projects/${pid}/members/${m.id}/roles`, { method: "PUT", body: { roles } });
      onDone();
    } catch (ex) {
      setErr((ex as ApiError).message);
    }
  }
  return (
    <Modal title={`编辑角色 · ${m.name}`} onClose={onClose} footer={<>
      <button type="button" className="btn" onClick={onClose}>取消</button>
      <button type="button" className="btn primary" onClick={save}>保存</button>
    </>}>
      <Field label="角色（可多选）" error={err}>
        <div className="checks">
          {ROLE_OPTIONS.map(([k, label]) => (
            <label key={k}><input type="checkbox" checked={roles.includes(k)} onChange={(e) => setRoles((x) => e.target.checked ? [...x, k] : x.filter((r) => r !== k))} />{label}</label>
          ))}
        </div>
      </Field>
      <div className="hint">角色只在「{projectName}」内生效，在其他项目中不获得这些权限。</div>
    </Modal>
  );
}

function PickAgent({ candidates, onClose, onNext }: { candidates: Member[]; onClose: () => void; onNext: (m: Member) => void }) {
  const [sel, setSel] = useState(candidates[0]?.id ?? 0);
  const m = candidates.find((x) => x.id === sel);
  return (
    <Modal title="指定业主代理人" onClose={onClose} footer={<>
      <button type="button" className="btn" onClick={onClose}>取消</button>
      <button type="button" className="btn primary" disabled={!m} onClick={() => m && onNext(m)}>下一步</button>
    </>}>
      {candidates.length ? (
        <Field label="选择已加入本项目的成员" required>
          <select className="select" id="pxSel" value={sel} onChange={(e) => setSel(Number(e.target.value))}>
            {candidates.map((c) => <option key={c.id} value={c.id}>{c.name}（{c.roleLabels.join("、")}）</option>)}
          </select>
        </Field>
      ) : <div className="notice warn"><span>没有可指定的成员。请先邀请代理人加入项目。</span></div>}
      <div className="notice plain"><span>代理人只能放行检查点，不能签认基线、图纸版本和变更单。每个项目最多一名代理人。</span></div>
    </Modal>
  );
}

function DeliverDialog({ onClose, onNext }: { onClose: () => void; onNext: (d: string) => void }) {
  const [d, setD] = useState("");
  const [err, setErr] = useState("");
  return (
    <Modal title="推进为「已交房」" onClose={onClose} footer={<>
      <button type="button" className="btn" onClick={onClose}>取消</button>
      <button type="button" className="btn primary" onClick={() => (d ? onNext(d) : setErr("请填写实际交房日期"))}>下一步</button>
    </>}>
      <Field label="实际交房日期" required error={err}>
        <input className="input" id="dvDate" type="date" value={d} onChange={(e) => setD(e.target.value)} />
      </Field>
      <div className="hint">实际交房日期用于判断问题是否在「交房后」发现。状态推进后不可回退。</div>
    </Modal>
  );
}

