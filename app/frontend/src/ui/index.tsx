// 共用界面组件：图标、印章、对话框（含二次确认摘要）、提示条、状态页、分页、字段。
import { cloneElement, createContext, isValidElement, useCallback, useContext, useEffect, useId, useState, type ReactElement, type ReactNode } from "react";
import { ApiError } from "../api";

const PATHS: Record<string, string> = {
  todo: "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2",
  overview: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  layers: "M12 3 2 8l10 5 10-5-10-5ZM2 16l10 5 10-5",
  map: "M3 5l6-2 6 2 6-2v16l-6 2-6-2-6 2V5ZM9 3v16M15 5v16",
  stamp: "M9 3h6l-1 7h-4L9 3ZM5 14h14v4H5zM4 21h16",
  pin: "M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21ZM12 7a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z",
  doc: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6ZM14 3v6h6M9 15h6M9 11h3",
  alert: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 7v6M12 16.5v.5",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  chat: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z",
  money: "M3 6h18v12H3zM12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z",
  users: "M9 4.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7ZM2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a5 5 0 0 1 3.5 6",
  home: "M3 21h18M5 21V8l7-5 7 5v13M9 21v-6h6v6",
  download: "M12 3v12m0 0-4-4m4 4 4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2",
  shield: "M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3ZM9 12l2 2 4-4",
  briefcase: "M3 7h18v13H3zM8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2",
  grid: "M3 3h18v18H3zM3 9h18M9 21V9",
  book: "M4 4h6a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H4V4ZM20 4h-6a3 3 0 0 0-3 3v13a2 2 0 0 1 2-2h7V4Z",
  user: "M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM4 21a8 8 0 0 1 16 0",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  chevron: "m6 9 6 6 6-6",
  right: "m9 6 6 6-6 6",
  close: "M6 6l12 12M18 6 6 18",
  plus: "M12 5v14M5 12h14",
  camera: "M3 8h4l2-3h6l2 3h4v11H3zM12 10a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z",
  copy: "M8 8h12v12H8zM4 16V4h12",
  check: "m5 12 5 5 9-10",
  back: "M15 18 9 12l6-6",
  upload: "M12 21V9m0 0-4 4m4-4 4 4M4 7V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2",
  lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
  logout: "M15 4h4v16h-4M10 17l5-5-5-5M15 12H3",
};

export function Icon({ name, className = "icon" }: { name: keyof typeof PATHS | string; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <path d={PATHS[name] || PATHS.list} />
    </svg>
  );
}

/** 设计签名：印章式状态标签（DESIGN.md）。pass 绿 / stop 红 / pend 橙 / proxy 蓝。 */
export function Seal({ kind, children, just }: { kind: "pass" | "stop" | "pend" | "proxy"; children: ReactNode; just?: boolean }) {
  return <span className={`seal ${kind}${just ? " just" : ""}`}>{children}</span>;
}

export function Modal({ title, onClose, children, footer, wide }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="mask show" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined} style={wide ? { width: "min(820px,100%)" } : undefined}>
        <div className="dlg-hd">
          <h2>{title}</h2>
          <span className="spacer" />
          <button type="button" className="icon-btn ghost" aria-label="关闭" onClick={onClose}>
            <Icon name="close" />
          </button>
        </div>
        <div className="dlg-bd">{children}</div>
        {footer && <div className="dlg-ft">{footer}</div>}
      </div>
    </div>
  );
}

/** 不可撤回操作的二次确认：展示将提交的内容摘要（蓝图 §5）。 */
export function ConfirmDialog({ title, summary, warn, confirmText = "确认提交", cancelText = "取消", danger, busy, onConfirm, onClose, children }: {
  title: string; summary: [string, ReactNode][]; warn?: ReactNode; confirmText?: string; cancelText?: string; danger?: boolean; busy?: boolean;
  onConfirm: () => void; onClose: () => void; children?: ReactNode;
}) {
  return (
    <Modal title={title} onClose={onClose} footer={<>
      <button type="button" className="btn" onClick={onClose}>{cancelText}</button>
      <button type="button" className={`btn ${danger ? "danger" : "primary"}`} disabled={busy} onClick={onConfirm}>{busy ? "提交中…" : confirmText}</button>
    </>}>
      <dl className="confirm-summary">
        {summary.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {children}
      {warn && <div className="cf-warn"><Icon name="alert" />{warn}</div>}
    </Modal>
  );
}

type ToastFn = (msg: string) => void;
const ToastCtx = createContext<ToastFn>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; msg: string }[]>([]);
  const push = useCallback((msg: string) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, msg }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 3200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className="toast">{t.msg}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div className="card"><div className="card-bd" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton" style={{ margin: "10px 0", width: `${90 - i * 12}%` }} />)}
    </div></div>
  );
}

export function Empty({ text, action }: { text: string; action?: ReactNode }) {
  return <div className="state"><div className="ic"><Icon name="list" /></div><div>{text}</div>{action && <div style={{ marginTop: 12 }}>{action}</div>}</div>;
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error as ApiError;
  if (e?.status === 403) return <div className="state"><div className="ic"><Icon name="lock" /></div><div>{e.message || "无权访问"}</div></div>;
  return (
    <div className="state"><div className="ic"><Icon name="alert" /></div><div>{e?.message || "加载失败"}</div>
      {retry && <button type="button" className="btn sm" style={{ marginTop: 12 }} onClick={retry}>重试</button>}</div>
  );
}

export function Pager({ page, total, pageSize, onChange }: { page: number; total: number; pageSize: number; onChange: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="pager row" style={{ justifyContent: "flex-end", padding: "8px 16px", fontSize: "var(--text-sm)", color: "var(--muted)" }}>
      <span>共 {total} 条 · 第 {page}/{pages} 页</span>
      <button type="button" className="btn sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>上一页</button>
      <button type="button" className="btn sm" disabled={page >= pages} onClick={() => onChange(page + 1)}>下一页</button>
    </div>
  );
}

export function Field({ label, required, error, children, full }: { label: string; required?: boolean; error?: string; children: ReactNode; full?: boolean }) {
  // 标签与输入框关联：单个子元素没有 id 时自动补一个
  const autoId = useId();
  const el = isValidElement(children) ? (children as ReactElement<{ id?: string }>) : null;
  const id = el ? el.props.id || autoId : undefined;
  return (
    <div className={`field${error ? " invalid" : ""}${full ? " full" : ""}`}>
      <label htmlFor={id}>{label}{required && <span className="req"> *</span>}</label>
      {el && !el.props.id ? cloneElement(el, { id }) : children}
      {error && <span className="err">{error}</span>}
    </div>
  );
}

/** 一键复制微信消息（AC-F16-03）。 */
export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

export function useApiError() {
  const toast = useToast();
  return (e: unknown) => toast((e as ApiError)?.message || "操作失败");
}

export const money = (v: number | string | null | undefined) => (v === null || v === undefined || v === "" ? "—" : `${Number(v).toLocaleString("zh-CN")} 元`);
