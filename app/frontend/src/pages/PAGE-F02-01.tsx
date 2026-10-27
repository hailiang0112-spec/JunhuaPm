// PAGE-F02-01 · 登录页（REQ-F02-02：手机号密码登录、连续输错 5 次锁定 15 分钟，登录后进入我的待办）
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api, ApiError, sessionHint } from "../api";
import { useSession, type Me } from "../session";
import { Icon } from "../ui";
import "../styles/auth.css";

const fmt = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

export default function Login() {
  const nav = useNavigate();
  const { setMe } = useSession();
  const [phone, setPhone] = useState("");
  const [pwd, setPwd] = useState("");
  const [err, setErr] = useState("");
  const [lockLeft, setLockLeft] = useState(0);
  const [busy, setBusy] = useState(false);
  const [sp] = useSearchParams();
  const expired = sp.get("expired") === "1";

  useEffect(() => {
    if (lockLeft <= 0) return;
    const t = setInterval(() => setLockLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [lockLeft > 0]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr("");
    if (!phone.trim() || !pwd) {
      setErr("请输入手机号和密码");
      return;
    }
    setBusy(true);
    try {
      const me = await api<Me>("/auth/login", { body: { phone: phone.replace(/\s/g, ""), password: pwd } });
      setMe(me);
      sessionHint.set();
      nav(me.mustChangePassword ? "/me" : "/", { replace: true });
    } catch (ex) {
      const e2 = ex as ApiError;
      if (e2.code === "ACCOUNT_LOCKED") setLockLeft(Number(e2.details.remainingSeconds) || 900);
      else setErr(e2.message || "网络异常，请检查网络后重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <section className="auth-card" aria-labelledby="loginTitle">
        <div className="auth-brand"><span className="logo">君</span><div>君华装修项目管理平台<small>图纸与现场一致 · 证据可追溯</small></div></div>
        <h1 id="loginTitle">登录</h1>
        <p className="lead">使用受邀开通的手机号和密码登录</p>
        {lockLeft > 0 && (
          <div className="notice bad" role="alert" style={{ marginBottom: "var(--space-4)" }}>
            <Icon name="lock" />
            <div>该账号已锁定：15 分钟内连续 5 次密码错误。<br />请在 <b className="mono">{fmt(lockLeft)}</b> 后重试。</div>
          </div>
        )}
        {expired && !err && lockLeft <= 0 && <div className="notice warn" role="status" style={{ marginBottom: "var(--space-4)" }}><Icon name="alert" /><span>登录已过期，请重新登录。</span></div>}
        {err && <div className="notice bad" role="alert" style={{ marginBottom: "var(--space-4)" }}><Icon name="alert" /><span>{err}</span></div>}
        <form className="form" onSubmit={submit} noValidate style={{ display: "grid", gap: "var(--space-4)" }}>
          <div className="field">
            <label htmlFor="phone">手机号</label>
            <input className="input" id="phone" type="tel" inputMode="numeric" maxLength={13} autoComplete="username" placeholder="请输入手机号" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="pwd">密码</label>
            <input className="input" id="pwd" type="password" autoComplete="current-password" placeholder="请输入密码" value={pwd} onChange={(e) => setPwd(e.target.value)} />
          </div>
          <button className="btn primary block" type="submit" disabled={busy || lockLeft > 0}>{lockLeft > 0 ? `已锁定 ${fmt(lockLeft)}` : busy ? "登录中…" : "登录"}</button>
        </form>
        <p className="hint" style={{ marginTop: "var(--space-4)", display: "flex", gap: "var(--space-2)", alignItems: "center" }}><Icon name="user" />忘记密码请联系公司管理员重置</p>
      </section>
      <p className="auth-foot">仅限受邀成员使用。没有账号请向项目经理或公司管理员索取邀请链接。</p>
    </div>
  );
}
