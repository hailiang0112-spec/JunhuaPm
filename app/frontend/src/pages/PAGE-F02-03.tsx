// PAGE-F02-03 · 个人设置（REQ-F02-03 强制改密、REQ-F02-04 校验原密码后修改、退出登录）
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, sessionHint } from "../api";
import { Shell } from "../layout/Shell";
import { useSession, type Me } from "../session";
import { Field, useToast } from "../ui";
import { fmtPhone, StateCard } from "../acct";
import "../styles/pages/PAGE-F02-03.css";

const PW_RULE = /^(?=.*[A-Za-z])(?=.*\d).{8,}$/;
type MeFull = Me & { createdAt: string };

export default function MySettings() {
  const { setMe } = useSession();
  const nav = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["me-full"], queryFn: () => api<MeFull>("/me") });
  const me = q.data;
  const forced = !!me?.mustChangePassword;
  const [f, setF] = useState({ old: "", pwd: "", pwd2: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  // 强制改密：点击导航、底部标签、工地切换器时停留本页（AC-F02-07）
  useEffect(() => {
    if (!forced) return;
    document.body.classList.add("forced");
    const block = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest(".side a, .side button, .tabbar a, .tabbar button, .sitepick")) {
        e.preventDefault();
        e.stopPropagation();
        toast("请先设置新密码");
      }
    };
    document.addEventListener("click", block, true);
    return () => {
      document.body.classList.remove("forced");
      document.removeEventListener("click", block, true);
    };
  }, [forced, toast]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (!forced && !f.old) er.old = "请输入原密码";
    if (!PW_RULE.test(f.pwd)) er.pwd = "密码至少 8 位，需同时包含字母和数字";
    else if (f.pwd !== f.pwd2) er.pwd2 = "两次输入的密码不一致";
    setErrs(er);
    if (Object.keys(er).length) return;
    setBusy(true);
    try {
      const next = await api<MeFull>("/me/password", { body: forced ? { newPassword: f.pwd } : { oldPassword: f.old, newPassword: f.pwd } });
      setMe(next);
      qc.setQueryData(["me-full"], next);
      setF({ old: "", pwd: "", pwd2: "" });
      if (forced) {
        toast("新密码已设置，临时密码已失效");
        nav("/", { replace: true });
      } else toast("密码已修改，其他设备上的登录已失效");
    } catch (ex) {
      const a = ex as ApiError;
      const m = a.fieldMap?.() || {};
      if (m.oldPassword || m.newPassword) setErrs({ old: m.oldPassword, pwd: m.newPassword } as Record<string, string>);
      else toast(a.message || "保存失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    sessionHint.clear();
    setMe(null);
    qc.clear();
    nav("/login", { replace: true });
  }

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  const roleLine = me ? [...new Set(me.projects.flatMap((p) => p.roleLabels))].join("、") || (me.isCompanyAdmin ? "公司管理员" : "") : "";

  return (
    <Shell title="个人设置" sub="账号信息与密码">
      <div className="pg-me">
        {q.isLoading ? (
          <div className="card"><div className="card-bd" style={{ display: "grid", gap: "var(--space-3)" }}>{[40, 100, 85, 70].map((w, i) => <div key={i} className="skeleton" style={{ width: `${w}%` }} />)}</div></div>
        ) : q.isError || !me ? (
          <StateCard icon="alert" title="个人信息加载失败（网络中断），请重试" action={<button type="button" className="btn" onClick={() => q.refetch()}>重试</button>} />
        ) : (
          <>
            {forced && (
              <div className="notice warn force-banner" role="alert"><span><b>你正在使用临时密码登录，请先设置新密码。</b>设置完成前不能进行其他操作。</span></div>
            )}
            <div className="me">
              <section className="card" aria-labelledby="infoHd">
                <div className="card-hd"><h2 id="infoHd">个人信息</h2></div>
                <div className="card-bd">
                  <div className="who"><span className="avatar" aria-hidden="true">{me.name.slice(0, 1)}</span><div><b>{me.name}</b><div className="hint">{roleLine}</div></div></div>
                  <dl className="kv">
                    <dt>手机号</dt><dd className="mono">{fmtPhone(me.phone)}</dd>
                    <dt>账号开通</dt><dd className="mono">{me.createdAt}</dd>
                    <dt>我的项目与角色</dt>
                    <dd>
                      {me.projects.length ? (
                        <ul className="plist">
                          {me.projects.map((p) => (
                            <li key={p.id}>{p.name}{p.roleLabels.map((r) => <span key={r} className="tag brand">{r}</span>)}</li>
                          ))}
                        </ul>
                      ) : <span className="hint">还没有加入任何项目</span>}
                    </dd>
                  </dl>
                </div>
              </section>
              <section className="card" aria-labelledby="pwdHd">
                <div className="card-hd"><h2 id="pwdHd">{forced ? "设置新密码" : "修改密码"}</h2></div>
                <div className="card-bd">
                  <form className="form" onSubmit={submit} noValidate>
                    {!forced && (
                      <Field label="原密码" required error={errs.old}>
                        <input className="input" id="pOld" type="password" autoComplete="current-password" value={f.old} onChange={set("old")} />
                      </Field>
                    )}
                    <Field label="新密码" required error={errs.pwd}>
                      <input className="input" id="pNew" type="password" autoComplete="new-password" placeholder="至少 8 位，需同时包含字母和数字" value={f.pwd} onChange={set("pwd")} />
                    </Field>
                    <Field label="确认新密码" required error={errs.pwd2}>
                      <input className="input" id="pNew2" type="password" autoComplete="new-password" value={f.pwd2} onChange={set("pwd2")} />
                    </Field>
                    <p className="hint">{forced ? "设置后临时密码立即失效。" : "修改后，你在其他设备上的登录会全部失效，当前设备保持登录。"}</p>
                    <button className="btn primary block" type="submit" disabled={busy}>{busy ? "保存中…" : forced ? "设置新密码并继续" : "保存新密码"}</button>
                  </form>
                </div>
              </section>
              <section className="card">
                <div className="card-bd row" style={{ justifyContent: "space-between" }}>
                  <span className="hint">在共用电脑或交接手机后，请主动退出。</span>
                  <button type="button" className="btn" onClick={logout}>退出登录</button>
                </div>
              </section>
            </div>
          </>
        )}
      </div>
    </Shell>
  );
}
