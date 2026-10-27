// PAGE-F10-02 · 楼层 / 房间：KPI、楼层与房间 × 阶段矩阵、房间卡、楼层分布、房间问题、楼层明细、详情抽屉
// REQ-F10-03、AC-F10-09（矩阵下钻）；DEC-313（?floor= / ?room= 自动打开抽屉）
import { useCallback, useEffect, useRef, type KeyboardEvent } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Shell } from "../layout/Shell";
import { useProject } from "../session";
import { ErrorState, Icon, Loading, Seal } from "../ui";
import { CellBar, f1, IssueSeal, Kpi, LevelTag, Matrix, MatrixLegend, type IssueBrief, type MatrixRow, type PhaseBrief, type WorkItem } from "./plan-common";
import "../styles/pages/PAGE-F10-02.css";

type FloorStat = { id: number | "all"; name: string; roomCount: number | null; itemCount: number; doneCount: number; progress: number; weightByPhase: number[]; weightTotal: number; issues: number; closed: number; mid: number; open: number };
type RoomStat = { id: number; floorId: number; floorName: string; name: string; itemCount: number; progress: number; issues: number; closed: number; legacy: number; issueSummary: { code: string; description: string }[] };
type View = { phases: PhaseBrief[]; floors: FloorStat[]; rooms: RoomStat[]; floorMatrix: MatrixRow[]; roomMatrix: MatrixRow[]; workItems: { total: number; done: number; common: number } };
type Detail = {
  kind: "floor" | "room"; title: string; floorId: number | "all"; roomId: number | null;
  stats: { progress: number; itemCount: number; doneCount: number; legacy: number };
  groups: (PhaseBrief & { status: string; items: WorkItem[] })[]; issues: IssueBrief[];
};

function StackBars({ rows, colors, label }: { rows: { name: string; parts: number[]; total: number }[]; colors: string[]; label: string }) {
  const W = 520, L = 80, R = 500, RH = 30, T = 8, H = T + RH * rows.length + 12;
  const max = Math.max(1, ...rows.map((r) => r.total));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
      {rows.map((r, i) => {
        const y = T + i * RH;
        let x = L;
        return (
          <g key={r.name}>
            <text x={L - 8} y={y + 18} textAnchor="end" fontSize="12" style={{ fill: "var(--fg-2)" }}>{r.name}</text>
            {r.parts.map((v, j) => {
              const ww = (R - L - 40) * v / max;
              if (!ww) return null;
              const el = <rect key={j} x={x} y={y + 6} width={ww} height="16" style={{ fill: colors[j] }} />;
              x += ww;
              return el;
            })}
            <text x={x + 6} y={y + 18} fontSize="12" style={{ fill: "var(--fg)" }}>{r.total}</text>
          </g>
        );
      })}
    </svg>
  );
}

function Drawer({ pid, sel, onClose, canIssue }: { pid: string; sel: { kind: "floor" | "room"; id: string }; onClose: () => void; canIssue: boolean }) {
  const q = useQuery({ queryKey: ["scope-detail", pid, sel.kind, sel.id], queryFn: () => api<Detail>(`/projects/${pid}/scope-detail?${sel.kind}=${sel.id}`) });
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    btn.current?.focus();
    const onKey = (e: globalThis.KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const d = q.data;
  const first = d?.groups.find((g) => g.status === "进行中") || d?.groups[0];
  const param = sel.kind === "room" ? `room=${sel.id}` : `floor=${sel.id}`;
  const issueNew = d ? `/p/${pid}/issues?new=1${d.floorId !== "all" ? `&floor=${d.floorId}` : ""}${d.roomId ? `&room=${d.roomId}` : ""}` : "";
  return (
    <>
      <div className="drawer-mask f1002" onClick={onClose} />
      <aside className="drawer f1002" role="dialog" aria-modal="true" aria-labelledby="dr-t">
        <div className="dh">
          <div style={{ flex: 1, minWidth: 0 }}><h3 id="dr-t">{d?.title || "…"}</h3><div className="sub">{sel.kind === "room" ? "房间详情 · 跨工段事项与问题" : sel.id === "all" ? "跨楼层通项 · 材料进场、系统调试、隐蔽验收、竣工验收" : "楼层详情 · 跨工段事项与问题"}</div></div>
          <button ref={btn} type="button" className="icon-btn ghost" aria-label="关闭" onClick={onClose}><Icon name="close" /></button>
        </div>
        <div className="db">
          {q.isLoading && <Loading rows={4} />}
          {q.error && <ErrorState error={q.error} retry={() => q.refetch()} />}
          {d && <>
            <div className="dstats">
              <div><b>{f1(d.stats.progress)}%</b><span>加权完成度</span></div><div><b>{d.stats.itemCount}</b><span>工作项</span></div>
              <div><b>{d.stats.doneCount}</b><span>已完成</span></div><div><b className={d.stats.legacy ? "down" : ""}>{d.stats.legacy}</b><span>遗留问题</span></div>
            </div>
            <div className="dsec">跨工段工作项</div>
            {!d.groups.length && <div className="state" style={{ padding: "var(--space-6)" }}>该范围暂无工作项，可在项目结构中新增并指定楼层与房间。</div>}
            {d.groups.map((g) => (
              <div key={g.id}>
                <div className="dsec" style={{ marginTop: "var(--space-3)" }}>
                  <span className="phase-dot" style={{ background: `var(${g.colorVar})` }} />{g.name}<span className="tag">{g.items.length} 项</span>
                  <Link className="btn sm" style={{ marginLeft: "auto" }} to={`/p/${pid}/phase/${g.id}?${param}`}>在工段中查看</Link>
                </div>
                {g.items.map((t) => (
                  <div key={t.id} className="titem">
                    <Link to={`/p/${pid}/work-items/${t.id}`}>{t.name}</Link>
                    <span>{t.checkpointSeal && <Link to={`/p/${pid}/checkpoints/${t.checkpointSeal.checkpointId}`} style={{ textDecoration: "none" }}><Seal kind={t.checkpointSeal.kind}>{t.checkpointSeal.text}</Seal></Link>}</span>
                    <div className="meta">
                      <span>{d.kind === "floor" ? `${t.roomName} · ` : ""}负责人 {t.ownerName}</span><span>计划 {t.plannedFinish || "—"}</span>
                      <span className={`tag ${t.status === "已完成" ? "ok" : t.status === "进行中" ? "brand" : ""}`}>{t.status} {t.progress}%</span>
                    </div>
                  </div>
                ))}
              </div>
            ))}
            <div className="dsec">问题 <span className="tag">{d.issues.length} 项</span></div>
            {!d.issues.length && <p className="muted" style={{ fontSize: "var(--text-sm)" }}>该范围暂无问题记录。</p>}
            {d.issues.map((i) => (
              <div key={i.id} className="issue">
                <div className="h"><span className="muted">{i.code}</span><b style={{ flex: 1, minWidth: 180 }}>{i.description}</b><LevelTag level={i.level} /><IssueSeal status={i.status} /></div>
                <div className="meta">{i.phaseName} · 负责人 {i.ownerName} · 要求闭环 {i.dueDate || "—"}{i.overdueDays > 0 && <> · <b className="down">超期 {i.overdueDays} 天</b></>} · <Link to={`/p/${pid}/issues?id=${i.id}`}>查看问题</Link></div>
              </div>
            ))}
          </>}
        </div>
        {d && <div className="df">
          {canIssue && <Link className="btn" to={issueNew}><Icon name="plus" />在此登记问题</Link>}
          {first && <Link className="btn" to={`/p/${pid}/phase/${first.id}?${param}`}>在{first.name}（{first.status}）中查看</Link>}
        </div>}
      </aside>
    </>
  );
}

export default function Floors() {
  const { pid = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const { project, can } = useProject(pid);
  const q = useQuery({ queryKey: ["floor-view", pid], queryFn: () => api<View>(`/projects/${pid}/floor-view`) });
  const close = useCallback(() => setSp({}, { replace: true }), [setSp]);
  if ((q.error as ApiError | null)?.status === 403) return <Navigate to="/forbidden" replace />;
  const v = q.data;
  const roomSel = sp.get("room"), floorSel = sp.get("floor");
  const validRoom = roomSel && v?.rooms.some((r) => String(r.id) === roomSel);
  const validFloor = floorSel && v?.floors.some((f) => String(f.id) === floorSel);
  const sel = validRoom ? { kind: "room" as const, id: roomSel! } : validFloor ? { kind: "floor" as const, id: floorSel! } : null;
  const open = (kind: "floor" | "room", id: number | string) => setSp({ [kind]: String(id) });
  const key = (fn: () => void) => (e: KeyboardEvent) => { if (e.key === "Enter") fn(); };
  const realFloors = v?.floors.filter((f) => f.id !== "all") || [];
  const withItems = v?.rooms.filter((r) => r.itemCount > 0) || [];
  const fast = [...withItems].sort((a, b) => b.progress - a.progress)[0];
  const slow = [...withItems].sort((a, b) => a.progress - b.progress || b.issues - a.issues)[0];
  const hot = [...(v?.rooms || [])].sort((a, b) => b.issues - a.issues)[0];
  const nm = (r: RoomStat) => `${r.floorName} · ${r.name}`;
  const actions = <>
    <button type="button" className="btn" onClick={() => open("floor", "all")}>全楼通用事项</button>
    {can("issue.create") && <Link className="btn primary" to={`/p/${pid}/issues?new=1`}><Icon name="plus" />登记问题</Link>}
  </>;

  return (
    <Shell title="楼层 / 房间" sub={`${project?.name || ""}　｜　${realFloors.length} 个楼层 · ${v?.rooms.length ?? "…"} 个房间，按房间统筹各工段工作项`} actions={actions}>
      <div className="plan-pg pg-f1002">
        {q.isLoading && <Loading rows={6} />}
        {q.error && <div className="card"><ErrorState error={q.error} retry={() => q.refetch()} /></div>}
        {v && !realFloors.length && <div className="card"><div className="state">还没有楼层和房间，项目经理可在项目结构中添加{can("structure.edit") && <div style={{ marginTop: 12 }}><Link className="btn" to={`/p/${pid}/structure`}>去项目结构</Link></div>}</div></div>}
        {v && realFloors.length > 0 && <>
          <section className="grid-kpi mt-4" aria-label="楼层与房间指标">
            <Kpi label="楼层 / 房间" value={`${realFloors.length} / ${v.rooms.length}`}><span className="tag">另设「全楼通用」</span></Kpi>
            <Kpi label="工作项" value={v.workItems.total} unit="项"><span className="tag ok">已完成 {v.workItems.done} 项</span><span className="tag">通用 {v.workItems.common} 项</span></Kpi>
            <Kpi label="房间覆盖" value={`${withItems.length} / ${v.rooms.length}`} unit="室"><span className="tag brand">{v.rooms.filter((r) => r.itemCount && r.progress >= 99.95).length} 室已完工</span></Kpi>
            <Kpi label="进展最快房间" value={fast ? f1(fast.progress) : "—"} unit="%">{fast && <span className="tag ok">{nm(fast)}</span>}</Kpi>
            <Kpi label="短板房间" value={slow ? f1(slow.progress) : "—"} unit="%">{slow && <><span className="tag bad">{nm(slow)}</span><span className="tag">{slow.itemCount} 项</span></>}</Kpi>
            <Kpi label="问题集中房间" value={hot?.issues ?? 0} unit="项">{hot && hot.issues > 0 ? <><span className="tag warn">{nm(hot)}</span><span className="tag">遗留 {hot.legacy} 项</span></> : <span className="tag">暂无问题</span>}</Kpi>
          </section>

          <section className="card" aria-labelledby="fm-t">
            <div className="card-hd"><h2 id="fm-t">楼层 × 阶段 完成度矩阵</h2><span className="desc">点楼层名打开楼层详情 · 点单元格进入该工段并筛选该楼层</span></div>
            <div className="card-bd" style={{ paddingBottom: 0 }}><div className="scroll-x"><div className="chartbox mx" style={{ minWidth: 640 }}>
              <Matrix phases={v.phases} rows={v.floorMatrix} label="楼层与阶段完成度矩阵" labelW={150} rowH={34} onRow={(r) => open("floor", r.id)} cellTo={(r, p) => `/p/${pid}/phase/${p.id}?floor=${r.id}`} />
            </div></div></div>
            <MatrixLegend noneText="该工段无此范围事项" />
          </section>

          <section className="card" aria-labelledby="rm-t">
            <div className="card-hd"><h2 id="rm-t">房间 × 阶段 完成度矩阵</h2><span className="desc">{v.rooms.length} 个房间按楼层分组 · 点房间名打开房间详情 · 点单元格进入该工段并筛选该房间</span></div>
            <div className="card-bd" style={{ paddingBottom: 0 }}><div className="scroll-x"><div className="chartbox mx" style={{ minWidth: 640 }}>
              <Matrix phases={v.phases} rows={v.roomMatrix} label="房间与阶段完成度矩阵" labelW={150} rowH={34} groupBy onRow={(r) => open("room", r.id)} cellTo={(r, p) => `/p/${pid}/phase/${p.id}?room=${r.id}`} />
            </div></div></div>
            <MatrixLegend noneText="该工段无此范围事项" />
          </section>

          <section className="card" aria-labelledby="rc-t">
            <div className="card-hd"><h2 id="rc-t">各房间完成度</h2><span className="desc">按楼层分组 · 百分比为跨工段加权完成度，左侧红线表示有遗留问题</span></div>
            <div className="card-bd">
              {realFloors.map((f) => {
                const rs = v.rooms.filter((r) => r.floorId === f.id);
                return (
                  <div key={f.id} className="flgroup">
                    <div className="gh"><button type="button" onClick={() => open("floor", f.id)}>{f.name}</button><span className="tag">{rs.length} 个房间 · {f1(f.progress)}%</span></div>
                    <div className="rmgrid">
                      {rs.map((r) => (
                        <button key={r.id} type="button" className={`rmcard${r.legacy ? " leg" : ""}`} onClick={() => open("room", r.id)}>
                          <span className="t"><span>{r.name}</span><span>{f1(r.progress)}%</span></span>
                          <div className="pbar"><i style={{ width: `${r.progress}%` }} /></div>
                          <span className="s">{r.itemCount} 项工作 · 问题 {r.issues}{r.legacy ? ` · 遗留 ${r.legacy}` : ""}</span>
                        </button>
                      ))}
                      {!rs.length && <span className="muted" style={{ fontSize: "var(--text-sm)" }}>该楼层还没有房间。</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <div className="grid-2">
            <section className="card" aria-labelledby="fl-t">
              <div className="card-hd"><h2 id="fl-t">各楼层工作量分布</h2><span className="desc">按工作项权重合计，分工段堆叠</span></div>
              <div className="card-bd"><div className="chartbox"><StackBars label="各楼层工作量按工段堆叠" colors={v.phases.map((p) => `var(${p.colorVar})`)} rows={v.floors.map((f) => ({ name: f.name, parts: f.weightByPhase, total: f.weightTotal }))} /></div></div>
              <div className="legend">{v.phases.map((p) => <span key={p.id}><i style={{ background: `var(${p.colorVar})` }} />{p.name}</span>)}</div>
            </section>
            <section className="card" aria-labelledby="fi-t">
              <div className="card-hd"><h2 id="fi-t">各楼层问题分布</h2><span className="desc">已闭环 / 处理中 / 未闭环</span></div>
              <div className="card-bd"><div className="chartbox"><StackBars label="各楼层问题发现、处理中与未闭环" colors={["var(--success)", "var(--warn)", "var(--danger)"]} rows={v.floors.map((f) => ({ name: f.name, parts: [f.closed, f.mid, f.open], total: f.issues }))} /></div></div>
              <div className="legend"><span><i style={{ background: "var(--success)" }} />已闭环</span><span><i style={{ background: "var(--warn)" }} />处理中</span><span><i style={{ background: "var(--danger)" }} />未闭环</span></div>
            </section>
          </div>

          <section className="card" aria-labelledby="ri-t">
            <div className="card-hd"><h2 id="ri-t">房间问题分布</h2><span className="desc">只列有问题记录的房间 · 点行打开房间详情</span></div>
            <div className="card-bd tight"><div className="scroll-x"><table style={{ minWidth: 560 }}>
              <thead><tr><th>楼层 / 房间</th><th className="num">问题</th><th className="num">已闭环</th><th className="num">遗留</th><th>问题摘要</th></tr></thead>
              <tbody>{v.rooms.filter((r) => r.issues).sort((a, b) => b.issues - a.issues).map((r) => {
                const fn = () => open("room", r.id);
                return <tr key={r.id} className="row-link" tabIndex={0} onClick={fn} onKeyDown={key(fn)}><td className="nowrap"><span className="fl-tag">{r.floorName}</span> <b>{r.name}</b></td><td className="num">{r.issues}</td><td className="num">{r.closed}</td><td className={`num${r.legacy ? " down" : ""}`}>{r.legacy}</td><td>{r.issueSummary.map((i) => <div key={i.code}>{i.code} {i.description}</div>)}</td></tr>;
              })}
              {!v.rooms.some((r) => r.issues) && <tr><td colSpan={5} className="muted" style={{ textAlign: "center", padding: "var(--space-6)" }}>各房间暂无问题记录</td></tr>}</tbody>
            </table></div></div>
          </section>

          <section className="card" aria-labelledby="fd-t">
            <div className="card-hd"><h2 id="fd-t">楼层明细</h2><span className="desc">房间数 / 工作项 / 完成度 / 问题闭环</span></div>
            <div className="card-bd tight"><div className="scroll-x"><table style={{ minWidth: 640 }}>
              <thead><tr><th>楼层</th><th className="num">房间</th><th className="num">工作项</th><th className="num">已完成</th><th style={{ width: "30%" }}>加权完成度</th><th className="num">问题</th><th className="num">遗留</th></tr></thead>
              <tbody>{v.floors.map((f) => {
                const fn = () => open("floor", f.id);
                return <tr key={String(f.id)} className="row-link" tabIndex={0} onClick={fn} onKeyDown={key(fn)}><td><b>{f.name}</b></td><td className="num">{f.roomCount ?? "—"}</td><td className="num">{f.itemCount}</td><td className="num">{f.doneCount}</td><td><CellBar v={f.progress} /></td><td className="num">{f.issues}</td><td className={`num${f.mid + f.open ? " down" : ""}`}>{f.mid + f.open}</td></tr>;
              })}</tbody>
            </table></div></div>
          </section>
        </>}
      </div>
      {sel && <Drawer pid={pid} sel={sel} onClose={close} canIssue={can("issue.create")} />}
    </Shell>
  );
}
