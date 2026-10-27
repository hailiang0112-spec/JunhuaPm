// PAGE-F01-03 · 无权限页（REQ-F01-03、AC-F01-05）：不显示任何项目信息，只提供返回我的待办
import { Link } from "react-router";
import { Icon } from "../ui";
import "../styles/auth.css";
import "../styles/pages/PAGE-F01-03.css";

export default function Forbidden() {
  return (
    <div className="auth deny-wrap">
      <section className="auth-card deny" aria-labelledby="denyTitle">
        <div className="auth-brand"><span className="logo">君</span><div>君华装修项目管理平台<small>图纸与现场一致 · 证据可追溯</small></div></div>
        <div className="deny-ic"><Icon name="lock" /></div>
        <h1 id="denyTitle">无权访问该项目</h1>
        <p>你在该项目中没有任何角色，页面不显示该项目的信息。</p>
        <Link className="btn primary block" to="/">返回我的待办</Link>
      </section>
    </div>
  );
}
