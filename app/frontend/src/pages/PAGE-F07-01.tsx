// PAGE-F07-01 · 变更单列表（REQ-F07-01、AC-F07-02、AC-F07-08、AC-F07-09）：状态筛选、搜索、发起入口
import { useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Shell } from "../layout/Shell";
import { useProject } from "../session";
import { Icon, Loading, Seal } from "../ui";
import "../styles/pages/PAGE-F07-01.css";

export type CoBrief = {
  id: number; code: string; title: string; reasonCategory: string; content: string; status: string; isLate: boolean;
  needsNewDrawing: boolean | null; priceDelta: number | null; scheduleDeltaDays: number | null; costBearer: string;
  workItemCount: number; createdBy: { id: number; name: string } | null; createdAt: string; roundNo: number;
};
type ListResp = { items: CoBrief[]; total: number; page: number; pageSize: number };

const FILTERS: [string, string][] = [["all", "全部"], ["待预算定价", "待预算定价"], ["待业主签认", "待签认"], ["已生效", "已生效"], ["已驳回", "已驳回"], ["late", "后补变更"]];
const SEAL: Record<string, "pass" | "stop" | "pend"> = { 草稿: "pend", 待预算定价: "pend", 待业主签认: "pend", 已生效: "pass", 已驳回: "stop" };
const fee = (v: number | null) => (v === null ? "待预算定价" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toLocaleString("zh-CN"));
const days = (v: number | null) => (v === null ? "—" : v > 0 ? `+${v}` : v < 0 ? `−${Math.abs(v)}` : "0");
const amtCls = (v: number | null) => (v === null ? "muted" : v > 0 ? "amt-plus" : v < 0 ? "amt-minus" : "");

function Flags({ c }: { c: CoBrief }) {
  if (!c.isLate && !c.needsNewDrawing && c.status !== "已驳回" && c.status !== "草稿") return null;
  return (
    <div className="flags">
      {c.isLate && <span className="tag warn">后补变更</span>}
      {c.needsNewDrawing && <span className="tag brand">需新版图纸</span>}
      {c.status === "已驳回" && <span className="tag bad">待项目经理修改后重新提交</span>}
      {c.status === "草稿" && <span className="tag">草稿，待项目经理补齐后提交</span>}
    </div>
  );
}

export default function Changes() {
  const { pid } = useParams();
  const nav = useNavigate();
  const { project, can } = useProject(pid);
  const [f, setF] = useState("all");
  const [kw, setKw] = useState("");
  const [page, setPage] = useState(1);
  const params = new URLSearchParams({ page: String(page) });
  if (f === "late") params.set("late", "1");
  else if (f !== "all") params.set("status", f);
  if (kw.trim()) params.set("q", kw.trim());
  const q = useQuery({
    queryKey: ["change-orders", pid, f, kw.trim(), page],
    queryFn: () => api<ListResp>(`/projects/${pid}/change-orders?${params}`),
    placeholderData: keepPreviousData,
  });
  const detail = (c: CoBrief) => `/p/${pid}/changes/${c.id}`;
  const newBtn = can("change.create") && <Link className="btn primary" to={`/p/${pid}/changes/new`}><Icon name="plus" />发起变更单</Link>;
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.pageSize)) : 1;
  const filtered = f !== "all" || !!kw.trim();
  if ((q.error as ApiError | null)?.status === 403) return <Navigate to="/forbidden" replace />;

  return (
    <Shell title="变更单" sub={`${project?.name || ""} · 现场调整先签后做`} actions={newBtn}>
      <div className="pg-f0701">
        <section className="card" aria-labelledby="listTitle">
          <div className="card-hd" style={{ flexWrap: "wrap" }}>
            <h2 id="listTitle">变更单</h2><span className="tag">共 {q.data?.total ?? 0} 张</span>
          </div>
          <div className="card-bd" style={{ paddingBottom: "var(--space-3)" }}>
            <div className="co-filters" role="group" aria-label="按状态筛选">
              {FILTERS.map(([k, label]) => (
                <button key={k} type="button" className={`chip${f === k ? " on" : ""}`} aria-pressed={f === k} onClick={() => { setF(k); setPage(1); }}>{label}</button>
              ))}
              <label className="search">
                <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
                <input className="input" type="search" placeholder="搜索编号或变更内容" aria-label="搜索编号或变更内容" value={kw} onChange={(e) => { setKw(e.target.value); setPage(1); }} />
              </label>
            </div>
          </div>
          {q.isLoading ? <Loading rows={4} /> : q.isError ? (
            <div className="state"><div className="ic"><Icon name="alert" /></div><h3>变更单加载失败（网络中断）</h3><p>已有数据未受影响，请检查网络后重试。</p>
              <button type="button" className="btn" onClick={() => q.refetch()}>重新加载</button></div>
          ) : q.data && q.data.total === 0 && !filtered ? (
            <div className="state"><div className="ic"><Icon name="doc" /></div><h3>还没有变更单</h3><p>现场需要调整时，先发起变更单，业主签认后再施工。</p>{newBtn}</div>
          ) : q.data && q.data.items.length === 0 ? (
            <div className="state"><div className="ic"><Icon name="list" /></div><h3>没有符合条件的变更单</h3><p>换一个状态或清空搜索词再看看。</p></div>
          ) : q.data && (
            <>
              <div className="co-table scroll-x">
                <table>
                  <thead><tr><th style={{ width: 84 }}>编号</th><th>变更内容</th><th>原因类别</th><th className="num">受影响工作项</th><th className="num">费用增减（元）</th><th className="num">工期影响（天）</th><th>承担方</th><th>状态</th><th>发起</th></tr></thead>
                  <tbody>
                    {q.data.items.map((c) => (
                      <tr key={c.id} className="row-link" tabIndex={0} onClick={() => nav(detail(c))} onKeyDown={(e) => e.key === "Enter" && nav(detail(c))}>
                        <td className="mono" style={{ fontSize: "var(--text-sm)" }}>{c.code}</td>
                        <td><div className="co-title">{c.title}</div><Flags c={c} /></td>
                        <td>{c.reasonCategory || "—"}</td>
                        <td className="num">{c.workItemCount}</td>
                        <td className={`num ${amtCls(c.priceDelta)}`}>{fee(c.priceDelta)}</td>
                        <td className="num">{days(c.scheduleDeltaDays)}</td>
                        <td>{c.costBearer || <span className="muted">—</span>}</td>
                        <td><Seal kind={SEAL[c.status] || "pend"}>{c.status}</Seal></td>
                        <td className="co-meta">{c.createdBy?.name}<br />{c.createdAt.slice(0, 10)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="co-cards">
                {q.data.items.map((c) => (
                  <Link key={c.id} className="co-card" to={detail(c)}>
                    <div className="l1">
                      <div><span className="mono">{c.code}</span> · <span className="co-meta">{c.reasonCategory || "草稿"}</span><div className="co-title">{c.title}</div></div>
                      <Seal kind={SEAL[c.status] || "pend"}>{c.status}</Seal>
                    </div>
                    <Flags c={c} />
                    <div className="l3">
                      <span>费用 <b className={`num ${amtCls(c.priceDelta)}`}>{fee(c.priceDelta)}</b>{c.priceDelta === null ? "" : " 元"}</span>
                      <span>工期 <b className="num">{days(c.scheduleDeltaDays)}</b>{c.scheduleDeltaDays === null ? "" : " 天"}</span>
                      <span>承担方 {c.costBearer || "—"}</span>
                      <span className="co-meta">{c.workItemCount} 个工作项 · {c.createdBy?.name} {c.createdAt.slice(0, 10)}</span>
                    </div>
                  </Link>
                ))}
              </div>
              <div className="co-pager">
                <span>第 {page} 页 · 每页 {q.data.pageSize} 条</span>
                <button type="button" className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
                <button type="button" className="btn sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>下一页</button>
              </div>
            </>
          )}
        </section>
      </div>
    </Shell>
  );
}
