// 接口客户端：同域会话 Cookie + CSRF；错误体统一为 {code, message, fields, details}（技术方案 §4.4）。

export type FieldError = { field: string; message: string };
export class ApiError extends Error {
  status: number;
  code: string;
  fields: FieldError[];
  details: Record<string, unknown>;
  constructor(status: number, body: { code?: string; message?: string; fields?: FieldError[]; details?: Record<string, unknown> }) {
    super(body.message || "请求失败");
    this.status = status;
    this.code = body.code || "ERROR";
    this.fields = body.fields || [];
    this.details = body.details || {};
  }
  fieldMap(): Record<string, string> {
    return Object.fromEntries(this.fields.map((f) => [f.field, f.message]));
  }
}

function cookie(name: string) {
  return document.cookie.split("; ").find((c) => c.startsWith(name + "="))?.split("=")[1] || "";
}

let csrfReady: Promise<unknown> | null = null;
function ensureCsrf() {
  if (cookie("csrftoken")) return Promise.resolve();
  if (!csrfReady) csrfReady = fetch("/api/auth/csrf", { credentials: "same-origin" });
  return csrfReady;
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData; headers?: Record<string, string> } = {}): Promise<T> {
  const method = opts.method || (opts.body !== undefined || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = { ...(opts.headers || {}) };
  if (method !== "GET") {
    await ensureCsrf();
    headers["X-CSRFToken"] = decodeURIComponent(cookie("csrftoken"));
  }
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch("/api" + path, { method, headers, body, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, { code: "NETWORK", message: "网络异常，请检查网络后重试。" });
  }
  const text = await res.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return { message: text }; } })() : {};
  if (!res.ok) {
    const err = new ApiError(res.status, data);
    if (res.status === 401 && !location.pathname.startsWith("/login") && !location.pathname.startsWith("/invite")) {
      location.assign("/login?expired=1");
    }
    if (err.code === "PASSWORD_CHANGE_REQUIRED" && location.pathname !== "/me") location.assign("/me");
    throw err;
  }
  return data as T;
}

/** 不可撤回操作的幂等键（服务端行锁 + 唯一约束兜底，重复返回 409）。 */
export function idemKey() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export async function uploadFile(projectId: number | string, file: File): Promise<UploadedFile> {
  const form = new FormData();
  form.append("file", file);
  return api(`/projects/${projectId}/files`, { form });
}

export type UploadedFile = { id: number; name: string; size: number; mime: string; sha256: string; status: string; isImage: boolean; url: string; thumbUrl: string | null; uploadedAt: string | null };

/** 是否曾在本浏览器登录过：用于区分「登录已过期」与首次访问（只存标记，不存任何凭据）。 */
export const sessionHint = {
  set: () => { try { localStorage.setItem("jh_had_session", "1"); } catch { /* 隐私模式下忽略 */ } },
  clear: () => { try { localStorage.removeItem("jh_had_session"); } catch { /* 同上 */ } },
  has: () => { try { return localStorage.getItem("jh_had_session") === "1"; } catch { return false; } },
};
