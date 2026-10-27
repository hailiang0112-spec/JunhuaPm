// PAGE-F16-01 · 我的待办（首页）：跨工地按角色汇总待办，超时置顶，复制微信消息；右栏我的工地（REQ-F16-01、REQ-F16-02）
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { bj } from "../time";
import { api } from "../api";
import { Shell } from "../layout/Shell";
import { useSession } from "../session";
import { Icon, Seal, useApiError, useToast } from "../ui";
import { StateCard, useCopy } from "../acct";
import "../styles/pages/PAGE-F16-01.css";

type Todo = {
  id: string; kind: string; type: string; seal: "pass" | "stop" | "pend" | "proxy" | "plain"; sealText: string;
  projectId: number; projectName: string; objectId: number; title: string; who: string; due: string; msgDue: string;
  path: string; urgent: boolean; overdueHours: number; bad: boolean; ack: { kind: string; objectId: number } | null;
};
type Site = {
  id: number; name: string; status: string; plannedStart: string; actualHandover: string | null; progress: number;
  currentPhase: { id: number; name: string; colorVar: string } | null; unreleasedCheckpoints: number; roleLabels: string[];
};
type TodoResp = { items: Todo[]; total: number; urgent: number; types: string[]; generatedAt: string; sites: Site[]; isCompanyAdmin: boolean };

const WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

function message(t: Todo) {
  return `【${t.projectName}】${t.type}\n事项：${t.title}\n负责人：${t.who.replace("记录人：", "")}\n${t.msgDue}\n直达链接：${location.origin}${t.path}`;
}

function TodoRow({ t, onCopy, onAck, acking }: { t: Todo; onCopy: () => void; onAck: () => void; acking: boolean }) {
  return (
    <div className="todo">
      <div className="sealcol">{t.seal === "plain" ? <span className="seal plain">{t.sealText}</span> : <Seal kind={t.seal}>{t.sealText}</Seal>}</div>
      <div>
        <div className="p">{t.projectName} · {t.type}</div>
        <div className="t">{t.title}</div>
        <div className="m"><span className="who">{t.who}</span></div>
        <div className={`due${t.bad ? " bad" : ""}`}>{t.due}</div>
      </div>
      <div className="acts">
        {t.ack && <button type="button" className="btn sm" disabled={acking} onClick={onAck}>知道了</button>}
        <Link className="btn sm" to={t.path}>{t.ack ? "查看" : "去处理"}</Link>
        <button type="button" className="btn sm" onClick={onCopy}><Icon name="copy" />复制微信消息</button>
      </div>
    </div>
  );
}

function SiteCard({ s }: { s: Site }) {
  const seal = s.status === "已交房" ? <Seal kind="pass">已交房</Seal> : s.status === "筹备" ? <Seal kind="pend">筹备</Seal> : <span className="seal plain">{s.status}</span>;
  const phase = s.status === "已交房" ? `${s.actualHandover ?? ""} 实际交房` : s.status === "筹备" ? `计划 ${s.plannedStart} 开工` : s.currentPhase?.name ?? "—";
  const pct = Math.round(s.progress);
  return (
    <Link className="card link site" to={`/p/${s.id}`}>
      <div className="hd"><span className="nm2">{s.name}</span>{seal}</div>
      <div className="ph">
        {s.status === "施工中" && s.currentPhase && <i className="phase-dot" style={{ background: `var(${s.currentPhase.colorVar})` }} />}
        {phase}<b>{pct}%</b>
      </div>
      <div className="pbar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${pct}%` }} /></div>
      <div className="stats">
        <span>未放行检查点 <b className={s.unreleasedCheckpoints ? "bad" : undefined}>{s.unreleasedCheckpoints}</b></span>
        <span>我的角色 <b>{s.roleLabels.join(" · ")}</b></span>
      </div>
    </Link>
  );
}

export default function Todos() {
  const { me } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const onErr = useApiError();
  const { copy, dialog } = useCopy();
  const [filter, setFilter] = useState("全部");
  const q = useQuery({ queryKey: ["todos"], queryFn: () => api<TodoResp>("/todos"), refetchInterval: 60000, refetchOnWindowFocus: true });
  const ack = useMutation({
    mutationFn: (t: Todo) => api("/todos/ack", { body: t.ack }),
    onSuccess: () => {
      toast("已知悉，该知会已从待办移除");
      qc.invalidateQueries({ queryKey: ["todos"] });
      qc.invalidateQueries({ queryKey: ["todo-count"] });
    },
    onError: onErr,
  });

  const data = q.data;
  const items = data?.items ?? [];
  const active = filter === "全部" || data?.types.includes(filter) ? filter : "全部";
  const shown = items.filter((t) => active === "全部" || t.type === active);
  const urgent = shown.filter((t) => t.urgent);
  const groups = useMemo(() => {
    const m = new Map<string, Todo[]>();
    shown.filter((t) => !t.urgent).forEach((t) => m.set(t.type, [...(m.get(t.type) || []), t]));
    return [...m.entries()];
  }, [shown]);

  const now = bj();
  const sub = `${now.format("YYYY-MM-DD")} ${WEEK[now.day()]}` + (data ? ` · 共 ${data.total} 项待办${data.urgent ? `，${data.urgent} 项需立即关注` : ""}` : "");
  const memberOnly = me?.projects.length && me.projects.every((p) => p.roles.every((r) => r === "owner_member" || r === "admin"));
  const emptyTip = me?.isCompanyAdmin && me.projects.every((p) => p.roles.every((r) => r === "admin"))
    ? "公司管理员对项目业务数据只读，不承担签认、核对、放行、定价待办；成员、角色与项目状态在「成员与项目」中管理。"
    : memberOnly
      ? "业主方成员只能查看工地，不承担签认、放行等待办；被业主指定为业主代理人后，待放行检查点会出现在这里。"
      : "新的签认、放行、核对或定价事项出现时会显示在这里。";

  const row = (t: Todo) => <TodoRow key={t.id} t={t} acking={ack.isPending} onAck={() => ack.mutate(t)} onCopy={() => copy(message(t), "已复制")} />;

  return (
    <Shell title="我的待办" sub={sub}>
      <div className="pg-todo">
        {q.isLoading ? (
          <div aria-busy="true">
            {[0, 1].map((k) => (
              <div className="card" key={k}><div className="card-bd" style={{ display: "grid", gap: "var(--space-3)" }}>
                {[40, 100, 85, 70, 90, 60].map((w, i) => <div key={i} className="skeleton" style={{ width: `${w}%` }} />)}
              </div></div>
            ))}
          </div>
        ) : q.isError ? (
          <StateCard icon="alert" title="待办加载失败（网络中断），请重试" text="已显示的内容可能不是最新状态。" action={<button type="button" className="btn" onClick={() => q.refetch()}>重试</button>} />
        ) : (
          <div className="home">
            <section aria-labelledby="todoHd">
              <h2 id="todoHd" className="side-title">待我处理
                <span className="hint updated">更新于 {bj(data!.generatedAt).format("HH:mm")} · 每 60 秒自动刷新</span>
              </h2>
              {items.length > 0 && (
                <div className="filters" role="toolbar" aria-label="按类型筛选">
                  {["全部", ...data!.types].map((t) => (
                    <button key={t} type="button" className={`chip${t === active ? " on" : ""}`} aria-pressed={t === active} onClick={() => setFilter(t)}>
                      {t}{t === "全部" ? ` ${items.length}` : ""}
                    </button>
                  ))}
                </div>
              )}
              {items.length === 0 ? (
                <StateCard icon="check" title="当前没有需要你处理的事项" text={emptyTip} />
              ) : (
                <>
                  {urgent.length > 0 && (
                    <>
                      <div className="grp-title urgent"><Icon name="alert" />需立即关注 <span className="cnt">{urgent.length}</span></div>
                      <div className="card urgent">{urgent.map(row)}</div>
                    </>
                  )}
                  {groups.map(([g, arr]) => (
                    <div key={g}>
                      <div className="grp-title">{g} <span className="cnt">{arr.length}</span></div>
                      <div className="card">{arr.map(row)}</div>
                    </div>
                  ))}
                </>
              )}
            </section>
            <aside aria-labelledby="siteHd">
              <h2 id="siteHd" className="side-title">我的工地 <span className="hint">{data!.isCompanyAdmin ? `公司全部项目 ${data!.sites.length} 个` : `${data!.sites.length} 个`}</span></h2>
              {data!.sites.length ? data!.sites.map((s) => <SiteCard key={s.id} s={s} />) : (
                <StateCard title="你还没有加入任何工地" text="请联系项目经理或公司管理员发送邀请。" />
              )}
            </aside>
          </div>
        )}
      </div>
      {dialog}
    </Shell>
  );
}
