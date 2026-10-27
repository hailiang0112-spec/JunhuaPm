// PAGE-F02-02 · 邀请落地页（REQ-F02-01：AC-F02-02 新号设置密码 / 已有账号输原密码加入，AC-F02-03 失效邀请）
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { bj } from "../time";
import { api, ApiError } from "../api";
import { useSession, type Me } from "../session";
import { Field, Icon, useToast } from "../ui";
import "../styles/auth.css";
import "../styles/pages/PAGE-F02-02.css";

type Info = {
  projectName: string; inviter: string; inviterRole: string; roles: string[]; roleLabels: string[];
  phoneMasked: string; hasAccount: boolean; accountName: string | null; expiresAt: string;
};

const PW_RULE = /^(?=.*[A-Za-z])(?=.*\d).{8,}$/;

export default function Invite() {
  const { token = "" } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { setMe } = useSession();
  const q = useQuery({ queryKey: ["invitation", token], queryFn: () => api<Info>(`/invitations/${token}`) });
  const [f, setF] = useState({ phone: "", name: "", pwd: "", pwd2: "", old: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [netErr, setNetErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [dead, setDead] = useState(false);
  const info = q.data;
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!info) return;
    const phone = f.phone.replace(/\s/g, "");
    const er: Record<string, string> = {};
    if (!phone) er.phone = "请输入手机号";
    else if (phone.slice(0, 3) !== info.phoneMasked.slice(0, 3) || phone.slice(-4) !== info.phoneMasked.slice(-4)) er.phone = "手机号与邀请不一致，请使用收到邀请的手机号";
    if (info.hasAccount) {
      if (!f.old) er.old = "请输入登录密码";
    } else {
      if (f.name.trim().length < 2 || f.name.trim().length > 20) er.name = "请填写姓名（2–20 字）";
      if (!PW_RULE.test(f.pwd)) er.pwd = "密码至少 8 位，需同时包含字母和数字";
      if (!er.pwd && f.pwd !== f.pwd2) er.pwd2 = "两次输入的密码不一致";
    }
    setErrs(er);
    setNetErr("");
    if (Object.keys(er).length) return;
    setBusy(true);
    try {
      const body = info.hasAccount ? { phone, password: f.old } : { phone, name: f.name.trim(), password: f.pwd };
      const me = await api<Me>(`/invitations/${token}/accept`, { body });
      setMe(me);
      toast(`已加入「${info.projectName}」，角色：${info.roleLabels.join("、")}`);
      nav("/", { replace: true });
    } catch (ex) {
      const a = ex as ApiError;
      if (a.status === 410) setDead(true);
      else if (a.fields?.length) {
        const m = a.fieldMap();
        setErrs({ phone: m.phone, name: m.name, pwd: info.hasAccount ? undefined : m.password, old: info.hasAccount ? m.password : undefined } as Record<string, string>);
      } else setNetErr("网络异常，请重试。已填写的内容已保留。");
    } finally {
      setBusy(false);
    }
  }

  const invalid = dead || (q.error as ApiError | null)?.status === 410 || (q.error as ApiError | null)?.status === 404;
  return (
    <div className="auth pg-invite">
      <section className="auth-card" aria-labelledby="invTitle">
        <div className="auth-brand"><span className="logo">君</span><div>君华装修项目管理平台<small>图纸与现场一致 · 证据可追溯</small></div></div>
        {q.isLoading ? (
          <div aria-busy="true" style={{ display: "grid", gap: "var(--space-3)" }}>
            {[60, 100, 80, 70].map((w, i) => <div key={i} className="skeleton" style={{ width: `${w}%` }} />)}
          </div>
        ) : invalid ? (
          <div className="dead">
            <div className="ic"><Icon name="alert" /></div>
            <h2 id="invTitle">邀请已失效，请联系邀请人重新发送</h2>
            <p className="hint">链接已过期、已被使用或已被撤销，不会创建账号，也不会授予任何角色。</p>
            <p style={{ marginTop: "var(--space-6)" }}><Link to="/login">已有账号？去登录</Link></p>
          </div>
        ) : q.isError || !info ? (
          <div className="dead">
            <div className="ic"><Icon name="alert" /></div>
            <h2 id="invTitle">邀请加载失败（网络中断），请重试</h2>
            <button type="button" className="btn" style={{ marginTop: "var(--space-4)" }} onClick={() => q.refetch()}>重试</button>
          </div>
        ) : (
          <>
            <h1 id="invTitle">你被邀请加入项目</h1>
            <p className="invite-hd"><b>{info.inviter}{info.inviterRole && `（${info.inviterRole}）`}</b>邀请你以<b>{info.roleLabels.join("、")}</b>身份加入</p>
            <dl className="kv">
              <dt>项目</dt><dd>{info.projectName}</dd>
              <dt>邀请人</dt><dd>{info.inviter}{info.inviterRole && ` · ${info.inviterRole}`}</dd>
              <dt>角色</dt><dd>{info.roleLabels.map((r) => <span key={r} className="tag brand" style={{ marginRight: 4 }}>{r}</span>)}</dd>
              <dt>绑定手机号</dt><dd className="mono">{info.phoneMasked}</dd>
              <dt>有效期</dt><dd>{bj(info.expiresAt).format("YYYY-MM-DD HH:mm")} 前有效，仅可使用一次</dd>
            </dl>
            <form className="form" onSubmit={submit} noValidate>
              <Field label="手机号" required error={errs.phone}>
                <input className="input" id="jPhone" type="tel" inputMode="numeric" maxLength={13} placeholder="请输入收到邀请的手机号" autoComplete="username" value={f.phone} onChange={set("phone")} />
              </Field>
              {info.hasAccount ? (
                <>
                  <div className="notice info"><span>该手机号已有账号（{info.accountName}）。输入你的登录密码即可加入本项目，原账号的其他项目不受影响。</span></div>
                  <Field label="登录密码" required error={errs.old}>
                    <input className="input" id="jOld" type="password" autoComplete="current-password" placeholder="请输入现有登录密码" value={f.old} onChange={set("old")} />
                  </Field>
                </>
              ) : (
                <>
                  <Field label="姓名" required error={errs.name}>
                    <input className="input" id="jName" maxLength={20} placeholder="将作为你在签认、核对记录中的署名" value={f.name} onChange={set("name")} />
                  </Field>
                  <Field label="设置密码" required error={errs.pwd}>
                    <input className="input" id="jPwd" type="password" autoComplete="new-password" placeholder="至少 8 位，需同时包含字母和数字" value={f.pwd} onChange={set("pwd")} />
                  </Field>
                  <Field label="确认密码" required error={errs.pwd2}>
                    <input className="input" id="jPwd2" type="password" autoComplete="new-password" placeholder="再输入一次密码" value={f.pwd2} onChange={set("pwd2")} />
                  </Field>
                </>
              )}
              {netErr && <div className="notice bad" role="alert"><span>{netErr}</span></div>}
              <button className="btn primary block" type="submit" disabled={busy}>{busy ? "加入中…" : info.hasAccount ? "确认加入" : "设置密码并加入"}</button>
            </form>
          </>
        )}
      </section>
      <p className="auth-foot">邀请链接仅限本人使用，请勿转发。</p>
    </div>
  );
}
