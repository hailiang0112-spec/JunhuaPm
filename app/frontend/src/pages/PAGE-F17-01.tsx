// PAGE-F17-01 · 审计与证据包（REQ-F17-01~04、REQ-F14-02：完整性校验、证据包导出、操作日志、计划留档 CSV）
import { useMemo, useState } from "react";
import { useParams } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Card, Shell } from "../layout/Shell";
import { useProject } from "../session";
import { ErrorState, Field, Icon, Pager, Seal, useApiError, useToast } from "../ui";
import "../styles/pages/PAGE-F17-01.css";

type Job = {
  id: number; status: string; error?: string; createdAt: string; finishedAt: string | null;
  result: {
    ok?: boolean; count?: number; tail?: string; checkedAt?: string;
    firstBad?: { code: string; seq: number; at: string; atText: string; recordType: string; recordLabel: string } | null;
    fileName?: string; scopeLabel?: string;
  };
};
type Integrity = { latest: Job | null; ledgerCount: number; tail: string };
type ExportInfo = { options: { phases: { id: number; name: string }[]; floors: { id: number; name: string; rooms: { id: number; name: string }[] }[] }; defaultFrom: string; defaultTo: string };
type Log = { id: number; at: string; actorName: string; actorRole: string; action: string; objectType: string; objectId: string; objectLabel: string; before: unknown; after: unknown };
type Logs = { items: Log[]; total: number; page: number; pageSize: number; facets: { actors: { id: number; name: string }[]; objectTypes: string[] } };
type Summary = { planLogCount: number; csvColumns: string[]; csvFileName: string };

const ZIP = [
  ["记录清单（.xlsx）", "基线、核对、放行、变更单、问题等记录"],
  ["照片原件", "核对与验收照片，不压缩"],
  ["相关图纸版本文件", "范围内工作项引用过的全部版本"],
  ["签认内容快照", "签认当时的完整内容"],
  ["摘要清单", "每条记录的摘要与导出时的链尾摘要"],
];
const hms = (s?: string | null) => (s ? `${s.slice(0, 10)} ${s.slice(11, 19)}` : "");
const hm = (s?: string | null) => (s ? `${s.slice(0, 10)} ${s.slice(11, 16)}` : "");

const KEY_LABELS: Record<string, string> = { status: "状态", name: "名称", folder: "分类", body: "内容", changeOrder: "变更单", source: "来源", title: "标题", ownerName: "责任人", dueOn: "约定完成" };

function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v !== "object") return String(v);
  const entries = Object.entries(v as Record<string, unknown>);
  if (!entries.length) return "—";
  if (entries.length === 1) return show(entries[0][1]);
  return entries.map(([k, x]) => `${KEY_LABELS[k] || k}：${typeof x === "object" && x !== null ? JSON.stringify(x) : x ?? "—"}`).join("；");
}

function download(href: string) {
  const a = document.createElement("a");
  a.href = href;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export default function Audit() {
  const { pid } = useParams();
  const { project, can } = useProject(pid);
  const toast = useToast();
  const onErr = useApiError();
  const canCheck = can("integrity.check");
  const canExport = can("evidence.export");
  const canLogs = can("audit.read");

  // 完整性校验
  const integ = useQuery({ queryKey: ["integrity", pid], queryFn: () => api<Integrity>(`/projects/${pid}/integrity-checks`), enabled: !!pid && canCheck });
  const [lastRun, setLastRun] = useState<Job | null>(null);
  const runCheck = useMutation({
    mutationFn: () => api<Job>(`/projects/${pid}/integrity-checks`, { body: {} }),
    onSuccess: (j) => { setLastRun(j); toast("完整性校验已完成"); },
    onError: onErr,
  });
  const ig = lastRun || integ.data?.latest || null;

  // 证据包
  const exp = useQuery({ queryKey: ["evidence-options", pid], queryFn: () => api<ExportInfo>(`/projects/${pid}/evidence-exports`), enabled: !!pid && canExport });
  const [scope, setScope] = useState({ phaseId: "", floorId: "", roomId: "", from: "", to: "" });
  const from = scope.from || exp.data?.defaultFrom || "";
  const to = scope.to || exp.data?.defaultTo || "";
  const [rangeErr, setRangeErr] = useState("");
  const [done, setDone] = useState<Job | null>(null);
  const rooms = exp.data?.options.floors.find((f) => String(f.id) === scope.floorId)?.rooms || [];
  const runExport = useMutation({
    mutationFn: async () => {
      let j = await api<Job>(`/projects/${pid}/evidence-exports`, { body: { phaseId: scope.phaseId || null, floorId: scope.floorId || null, roomId: scope.roomId || null, from, to } });
      // 生产环境由后台 worker 生成，轮询到完成再下载
      while (j.status === "排队" || j.status === "进行中") {
        await new Promise((r) => setTimeout(r, 2000));
        j = await api<Job>(`/projects/${pid}/evidence-exports/${j.id}`);
      }
      if (j.status !== "完成") throw new Error(`证据包生成失败：${j.error || "请稍后重试"}`);
      return j;
    },
    onSuccess: (j) => { setDone(j); toast("证据包已生成"); download(`/api/projects/${pid}/evidence-exports/${j.id}/download`); },
    onError: (e) => { const m = (e as ApiError).fieldMap?.(); if (m?.from) setRangeErr(m.from); else onErr(e); },
  });
  const doExport = () => {
    if (from && to && from > to) { setRangeErr("开始日期不能晚于结束日期"); return; }
    setRangeErr("");
    setDone(null);
    runExport.mutate();
  };

  // 操作日志
  const [f, setF] = useState({ actorId: "", objectType: "", objectId: "", from: "", to: "" });
  const [page, setPage] = useState(1);
  const params = useMemo(() => {
    const p = new URLSearchParams({ page: String(page) });
    Object.entries(f).forEach(([k, v]) => v && p.set(k, v));
    return p.toString();
  }, [f, page]);
  const logs = useQuery({ queryKey: ["audit-logs", pid, params], queryFn: () => api<Logs>(`/projects/${pid}/audit-logs?${params}`), enabled: !!pid && canLogs, placeholderData: (x) => x });
  const setFilter = (k: keyof typeof f) => (e: { target: { value: string } }) => { setPage(1); setF((x) => ({ ...x, [k]: e.target.value })); };

  // 计划留档
  const summary = useQuery({ queryKey: ["audit-summary", pid], queryFn: () => api<Summary>(`/projects/${pid}/audit-summary`), enabled: !!pid });

  return (
    <Shell title="审计与证据包" sub={`${project?.name || ""} · 记录可校验，证据随时可导出`}>
      <div className="notice plain au-note"><Icon name="shield" /><span>签认、核对、放行、变更单状态、图纸版本、问题状态变化和计划留档属于关键记录，只能追加，任何角色（含公司管理员）都不能修改或删除；更正只能追加新记录。每条关键记录都带包含上一条摘要的 SHA-256 串联摘要。</span></div>
      {project && !canExport && !canCheck && (
        <Card><div className="notice warn"><Icon name="lock" /><span>仅业主和公司管理员可导出证据包；完整性校验和操作日志也只对业主和公司管理员开放。你可以在下方导出计划变更留档。</span></div></Card>
      )}

      {(canCheck || canExport) && (
        <div className="top2">
          {canCheck && (
            <section className="card" aria-labelledby="igTitle">
              <div className="card-hd"><h2 id="igTitle">完整性校验</h2><span className="spacer" /><Icon name="shield" /></div>
              <div className="card-bd au-col">
                <p className="muted" style={{ fontSize: "var(--text-sm)" }}>逐条重算本项目全部关键记录的摘要链，确认记录没有被改动。</p>
                <div className="ig-res" aria-live="polite">
                  {runCheck.isPending || integ.isLoading ? (
                    <><div className="skeleton" style={{ width: "50%" }} /><div className="skeleton" /><div className="skeleton" style={{ width: "70%" }} /></>
                  ) : integ.error ? <ErrorState error={integ.error} retry={() => integ.refetch()} /> : !ig ? (
                    <>
                      <div className="hd"><span className="big">尚未执行校验</span></div>
                      <dl><dt>关键记录</dt><dd>{integ.data?.ledgerCount.toLocaleString("zh-CN")} 条</dd><dt>当前链尾摘要</dt><dd className="mono">{integ.data?.tail}</dd></dl>
                    </>
                  ) : ig.result.ok ? (
                    <>
                      <div className="hd"><Seal kind="pass" just={!!lastRun}>完整</Seal><span className="big">摘要链完整</span></div>
                      <dl>
                        <dt>校验时间</dt><dd>{hms(ig.result.checkedAt || ig.finishedAt)}</dd>
                        <dt>已校验</dt><dd>{(ig.result.count || 0).toLocaleString("zh-CN")} 条关键记录，全部一致</dd>
                        <dt>链尾摘要</dt><dd className="mono">{ig.result.tail}</dd>
                      </dl>
                    </>
                  ) : (
                    <>
                      <div className="hd"><Seal kind="stop" just={!!lastRun}>不完整</Seal><span className="big">发现不一致</span></div>
                      <dl>
                        <dt>校验时间</dt><dd>{hms(ig.result.checkedAt || ig.finishedAt)}</dd>
                        <dt>第一条不一致记录</dt><dd><b>{ig.result.firstBad?.code}</b> · {ig.result.firstBad?.atText}</dd>
                        <dt>记录内容</dt><dd>{ig.result.firstBad?.recordLabel}</dd>
                        <dt>说明</dt><dd>该记录重算的摘要与保存的摘要不符，其后的记录无法通过校验。</dd>
                      </dl>
                    </>
                  )}
                </div>
                <button className="btn primary" type="button" disabled={runCheck.isPending} onClick={() => runCheck.mutate()}><Icon name="shield" />{runCheck.isPending ? "校验中…" : "执行完整性校验"}</button>
              </div>
            </section>
          )}
          {canExport && (
            <section className="card" aria-labelledby="exTitle">
              <div className="card-hd"><h2 id="exTitle">导出证据包</h2><span className="spacer" /><Icon name="download" /></div>
              <div className="card-bd au-col">
                {exp.error ? <ErrorState error={exp.error} retry={() => exp.refetch()} /> : (
                  <div className="range">
                    <Field label="工段">
                      <select className="select" value={scope.phaseId} onChange={(e) => setScope({ ...scope, phaseId: e.target.value })}>
                        <option value="">全部工段</option>{exp.data?.options.phases.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    </Field>
                    <Field label="楼层">
                      <select className="select" value={scope.floorId} onChange={(e) => setScope({ ...scope, floorId: e.target.value, roomId: "" })}>
                        <option value="">全部楼层</option>{exp.data?.options.floors.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                      </select>
                    </Field>
                    <Field label="房间">
                      <select className="select" value={scope.roomId} onChange={(e) => setScope({ ...scope, roomId: e.target.value })}>
                        <option value="">全部房间</option>{rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                      </select>
                    </Field>
                    <div className={`field full${rangeErr ? " invalid" : ""}`}>
                      <label htmlFor="xFrom">时间范围</label>
                      <div className="dates">
                        <input className="input" id="xFrom" type="date" value={from} aria-label="开始日期" onChange={(e) => setScope({ ...scope, from: e.target.value })} />
                        <span className="muted">至</span>
                        <input className="input" type="date" value={to} aria-label="结束日期" onChange={(e) => setScope({ ...scope, to: e.target.value })} />
                      </div>
                      {rangeErr && <span className="err">{rangeErr}</span>}
                    </div>
                  </div>
                )}
                <div>
                  <div style={{ fontSize: "var(--text-sm)", color: "var(--fg-2)", marginBottom: "var(--space-2)" }}>ZIP 包含（按所选范围）：</div>
                  <ul className="zip">{ZIP.map(([a, b]) => <li key={a}><Icon name="check" /><span>{a}<span className="muted"> · {b}</span></span></li>)}</ul>
                </div>
                {done && (
                  <div className="notice info"><Icon name="check" /><span>已生成 {done.result.fileName}（范围：{done.result.scopeLabel}），浏览器开始下载。共 {done.result.count} 条记录，链尾摘要 <span className="mono">{done.result.tail?.slice(0, 16)}…</span></span></div>
                )}
                <div className="exp-act"><button className="btn" type="button" disabled={runExport.isPending || !exp.data} onClick={doExport}><Icon name="download" />{runExport.isPending ? "正在生成…" : "导出证据包（ZIP）"}</button></div>
              </div>
            </section>
          )}
        </div>
      )}

      {canLogs && (
        <section className="card" aria-labelledby="lgTitle">
          <div className="card-hd" style={{ flexWrap: "wrap" }}>
            <h2 id="lgTitle">操作日志</h2>{logs.data && <span className="tag">{logs.data.total} 条</span>}
            <span className="spacer" /><span className="muted" style={{ fontSize: "var(--text-xs)" }}>只读，不能修改或删除</span>
          </div>
          <div className="card-bd">
            <div className="log-f">
              <Field label="操作人">
                <select className="select" value={f.actorId} onChange={setFilter("actorId")}>
                  <option value="">全部</option>{logs.data?.facets.actors.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </Field>
              <Field label="对象类型">
                <select className="select" value={f.objectType} onChange={setFilter("objectType")}>
                  <option value="">全部</option>{logs.data?.facets.objectTypes.map((t) => <option key={t}>{t}</option>)}
                </select>
              </Field>
              <Field label="对象编号或名称"><input className="input" type="search" placeholder="如 BG-003" value={f.objectId} onChange={setFilter("objectId")} /></Field>
              <Field label="开始日期"><input className="input" type="date" value={f.from} onChange={setFilter("from")} /></Field>
              <Field label="结束日期"><input className="input" type="date" value={f.to} onChange={setFilter("to")} /></Field>
            </div>
          </div>
          {logs.error ? <ErrorState error={logs.error} retry={() => logs.refetch()} /> : logs.isLoading ? (
            <div className="card-bd" aria-busy="true"><div className="skeleton" /><div className="skeleton" style={{ marginTop: 12, width: "70%" }} /></div>
          ) : !logs.data?.items.length ? (
            <div className="state au-state"><div className="ic"><Icon name="list" /></div><h3>没有符合条件的日志</h3><p>调整操作人、对象或时间范围再看看。</p></div>
          ) : (
            <>
              <div className="scroll-x">
                <table className="log-table">
                  <thead><tr><th>时间</th><th>操作人</th><th>操作</th><th>对象</th><th>变更前</th><th>变更后</th></tr></thead>
                  <tbody>
                    {logs.data.items.map((r) => (
                      <tr key={r.id}>
                        <td className="nowrap">{hm(r.at)}</td>
                        <td className="nowrap">{r.actorName}<div className="muted" style={{ fontSize: "var(--text-xs)" }}>{r.actorRole}</div></td>
                        <td className="op"><span className={`tag${r.action === "作废" || r.action === "删除" ? " bad" : r.action === "状态变更" ? " brand" : ""}`}>{r.action}</span></td>
                        <td>{r.objectType} {r.objectLabel}</td>
                        <td className="before">{show(r.before)}</td>
                        <td>{show(r.after)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager page={logs.data.page} total={logs.data.total} pageSize={logs.data.pageSize} onChange={setPage} />
            </>
          )}
        </section>
      )}

      <section className="card" aria-labelledby="csvTitle">
        <div className="card-hd" style={{ flexWrap: "wrap" }}><h2 id="csvTitle">计划变更留档导出</h2>{summary.data && <span className="tag">共 {summary.data.planLogCount} 条留档</span>}</div>
        <div className="card-bd au-col">
          <div style={{ fontSize: "var(--text-sm)", color: "var(--fg-2)" }}>CSV 列：</div>
          <div className="cols">{(summary.data?.csvColumns || []).map((c) => <span key={c} className="tag">{c}</span>)}</div>
          <div className="csv-act">
            <button className="btn" type="button" disabled={!summary.data} onClick={() => { download(`/api/projects/${pid}/plan-logs/export.csv`); toast(`已生成 ${summary.data!.csvFileName}`); }}>
              <Icon name="download" />导出 CSV
            </button>
          </div>
        </div>
      </section>
    </Shell>
  );
}
