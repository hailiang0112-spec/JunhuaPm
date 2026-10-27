// acct 模块页面共用的小工具：复制（带「请手动复制」兜底）、手机号显示、角色清单、无权限卡。
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Icon, Modal, useToast } from "./ui";

/** 复制到剪贴板；浏览器拒绝时弹出文本框让用户长按全选复制（PAGE-F16-01 §7）。 */
export function useCopy() {
  const toast = useToast();
  const [manual, setManual] = useState<string | null>(null);
  async function copy(text: string, okMsg = "已复制") {
    let ok = false;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        ok = true;
      }
    } catch {
      ok = false;
    }
    if (!ok) {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        ok = document.execCommand("copy");
      } catch {
        ok = false;
      }
      ta.remove();
    }
    if (ok) toast(okMsg);
    else setManual(text);
  }
  const dialog = manual === null ? null : (
    <Modal title="请手动复制" onClose={() => setManual(null)} footer={<button type="button" className="btn" onClick={() => setManual(null)}>关闭</button>}>
      <p className="hint">浏览器未允许自动复制，请长按全选后复制。</p>
      <textarea className="textarea copy-fallback" readOnly value={manual} onFocus={(e) => e.currentTarget.select()} aria-label="消息文本" />
    </Modal>
  );
  return { copy, dialog };
}

/** 完整手机号显示为「138 1234 5678」，打码号保持「138****5678」。 */
export const fmtPhone = (p: string) => (/^\d{11}$/.test(p) ? p.replace(/(\d{3})(\d{4})(\d{4})/, "$1 $2 $3") : p);

/** 可直接邀请 / 分配的项目角色（AC-F01-03），顺序与页面原型一致。 */
export const ROLE_OPTIONS: [string, string][] = [
  ["owner", "业主"], ["pm", "项目经理"], ["design_manager", "设计经理"], ["qc", "质检"], ["budget", "预算专员"], ["owner_member", "业主方成员"],
];

/** 公司管理页面的无权限卡（DEC-108）。 */
export function AdminOnly() {
  return (
    <div className="card"><div className="state">
      <div className="ic"><Icon name="lock" /></div>
      <div style={{ color: "var(--fg)", fontWeight: 600, fontSize: "var(--text-lg)" }}>仅公司管理员可访问公司管理页面</div>
      <p style={{ margin: "var(--space-1) 0 var(--space-4)" }}>当前身份没有该页面的权限，页面不显示任何数据。</p>
      <Link className="btn primary" to="/">返回我的待办</Link>
    </div></div>
  );
}

/** 状态卡：标题 + 说明 + 可选操作。 */
export function StateCard({ icon = "list", title, text, action }: { icon?: string; title: string; text?: ReactNode; action?: ReactNode }) {
  return (
    <div className="card"><div className="state">
      <div className="ic"><Icon name={icon} /></div>
      <div style={{ color: "var(--fg)", fontWeight: 600, fontSize: "var(--text-lg)" }}>{title}</div>
      {text && <p style={{ marginTop: "var(--space-1)" }}>{text}</p>}
      {action && <div style={{ marginTop: "var(--space-4)" }}>{action}</div>}
    </div></div>
  );
}
