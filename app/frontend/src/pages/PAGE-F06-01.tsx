// PAGE-F06-01 · 检查点列表：按状态、工段、楼层筛选；印章标签（DEC-201 单一印章，DEC-202 紧急程度排序）
import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Shell } from "../layout/Shell";
import { useProject } from "../session";
import { ErrorState, Icon, Loading, Seal } from "../ui";
import "../styles/pages/PAGE-F06-01.css";

type SealKind = "pass" | "stop" | "pend" | "proxy";
export type CkRow = {
  id: number; code: string; point: string; isConcealed: boolean; status: string; labels: string[]; seal: string; sealKind: SealKind | null;
  workItemId: number; workItemName: string; phaseName: string; phaseColorVar: string; floorName: string; roomName: string; place: string;
  situation: string; covered: boolean;
};
type ListResp = {
  items: CkRow[]; total: number; page: number; pageSize: number; counts: Record<string, number>; totalAll: number; releaseTimeoutHours: number;
  summary: { noCover: number; pending: number; timeout: number; inconsistent: number; inconsistentAfter: number; released: number; releasedProxy: number };
  phases: { id: number; name: string; colorVar: string }[]; floors: { id: number; name: string }[];
};

const CHIPS = ["全部", "不得覆盖", "待核对", "待放行", "超时", "不一致", "放行后发现不一致", "未放行先覆盖", "已放行"];

function SealCell({ r }: { r: CkRow }) {
  return r.sealKind ? <Seal kind={r.sealKind}>{r.seal}</Seal> : <span className="tag">{r.seal}</span>;
}

export default function Checkpoints() {
  const { pid } = useParams();
  const nav = useNavigate();
  const { project } = useProject(pid);
  const [status, setStatus] = useState("全部");
  const [phase, setPhase] = useState("");
  const [floor, setFloor] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [status, phase, floor]);
  const qs = new URLSearchParams({ status, page: String(page) });
  if (phase) qs.set("phase", phase);
  if (floor) qs.set("floor", floor);
  const q = useQuery({
    queryKey: ["checkpoints", pid, status, phase, floor, page],
    queryFn: () => api<ListResp>(`/projects/${pid}/checkpoints?${qs}`),
    placeholderData: keepPreviousData,
  });
  const data = q.data;
  const sub = data ? `${project?.name || ""} · 共 ${data.totalAll} 个检查点 · 放行时限 ${data.releaseTimeoutHours} 小时` : project?.name;

  if (q.error instanceof ApiError && q.error.status === 403) return <Navigate to="/forbidden" replace />;
  const clear = () => { setStatus("全部"); setPhase(""); setFloor(""); };
  const open = (r: CkRow) => nav(`/p/${pid}/checkpoints/${r.id}`);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1;

  return (
    <Shell title="检查点" sub={sub}>
      <div className="ck-list">
        {q.isPending ? <Loading rows={6} /> : q.error ? <ErrorState error={q.error} retry={() => q.refetch()} /> : data && (
          <>
            <div className="sum" aria-label="检查点概况">
              <div className="kpi"><div className="lb">不得覆盖</div><div className="vl bad num">{data.summary.noCover}</div><div className="target">隐蔽且未放行</div></div>
              <div className="kpi"><div className="lb">待放行</div><div className="vl warn num">{data.summary.pending}</div><div className="target">{data.summary.timeout ? `其中 ${data.summary.timeout} 项已超时` : "暂无超时"}</div></div>
              <div className="kpi"><div className="lb">不一致</div><div className="vl bad num">{data.summary.inconsistent}</div><div className="target">含放行后发现 {data.summary.inconsistentAfter} 项</div></div>
              <div className="kpi"><div className="lb">已放行</div><div className="vl ok num">{data.summary.released}</div><div className="target">含代理放行 {data.summary.releasedProxy} 项</div></div>
            </div>

            <section className="card" aria-label="检查点列表">
              {data.totalAll === 0 ? (
                <div className="state">
                  <div className="ic"><Icon name="pin" /></div>
                  <p>还没有检查点。先在工作项基线里添加检查点。</p>
                  {data.phases[0] && <p style={{ marginTop: "var(--space-3)" }}><Link className="btn" to={`/p/${pid}/phase/${data.phases[0].id}`}>进入工段详情</Link></p>}
                </div>
              ) : (
                <>
                  <div className="filters">
                    <div className="chips" role="group" aria-label="按状态筛选">
                      {CHIPS.map((c) => (
                        <button key={c} type="button" className={`chip${c === status ? " on" : ""}`} aria-pressed={c === status} onClick={() => setStatus(c)}>
                          {c}<span className="n">{data.counts[c] ?? 0}</span>
                        </button>
                      ))}
                    </div>
                    <div className="selrow">
                      <div className="field"><label htmlFor="fPhase">工段</label>
                        <select className="select" id="fPhase" value={phase} onChange={(e) => setPhase(e.target.value)}>
                          <option value="">全部工段</option>
                          {data.phases.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </select></div>
                      <div className="field"><label htmlFor="fFloor">楼层</label>
                        <select className="select" id="fFloor" value={floor} onChange={(e) => setFloor(e.target.value)}>
                          <option value="">全部楼层</option>
                          {data.floors.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                        </select></div>
                    </div>
                  </div>
                  {data.items.length === 0 ? (
                    <div className="state">
                      <div className="ic"><Icon name="pin" /></div>
                      <p>没有符合筛选条件的检查点。</p>
                      <p style={{ marginTop: "var(--space-3)" }}><button type="button" className="btn" onClick={clear}>清除筛选</button></p>
                    </div>
                  ) : (
                    <>
                      <div className="tablewrap scroll-x">
                        <table>
                          <thead><tr><th>状态</th><th>编号</th><th>检查点</th><th>楼层 / 房间</th><th>工段</th><th>隐蔽</th><th>当前情况</th></tr></thead>
                          <tbody>
                            {data.items.map((r) => (
                              <tr key={r.id} className="row-link" tabIndex={0} onClick={() => open(r)}
                                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(r); } }}>
                                <td className="seal-cell"><SealCell r={r} /></td>
                                <td className="idc">{r.code}</td>
                                <td><span className="nm">{r.point}</span></td>
                                <td>{r.place}</td>
                                <td><span className="phase-tag"><span className="phase-dot" style={{ background: `var(${r.phaseColorVar})` }} />{r.phaseName}</span></td>
                                <td className="hid">{r.isConcealed ? "隐蔽" : "—"}</td>
                                <td className="sub">{r.situation}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <div className="cards">
                        {data.items.map((r) => (
                          <Link key={r.id} className="ckcard" to={`/p/${pid}/checkpoints/${r.id}`}>
                            <div className="top"><span className="nm">{[r.floorName, r.roomName].filter(Boolean).join(" ")} · {r.point}</span><SealCell r={r} /></div>
                            <div className="meta">{r.code} · {r.phaseName}{r.isConcealed ? " · 隐蔽" : ""}</div>
                            <div className="info">{r.situation}</div>
                          </Link>
                        ))}
                      </div>
                    </>
                  )}
                  <div className="pager">
                    <span>共 {data.total} 条 · 每页 {data.pageSize} 条</span><span className="spacer" />
                    <button type="button" className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
                    <button type="button" className="btn sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>下一页</button>
                  </div>
                </>
              )}
            </section>
          </>
        )}
      </div>
    </Shell>
  );
}
