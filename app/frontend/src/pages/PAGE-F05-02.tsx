// PAGE-F05-02 · 基线签认：按工段 / 楼层分组，展开看完整内容后才能勾选签认，批量签认逐项留痕，退回必填理由。
// AC-F05-03、AC-F05-04、AC-F05-05、AC-F05-09、AC-F01-07、AC-F01-10、AC-F01-12、AC-F01-13
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, idemKey } from "../api";
import { Shell } from "../layout/Shell";
import { useProject, useSession } from "../session";
import { Empty, ErrorState, Field, Icon, Loading, Modal, money, Seal, useToast } from "../ui";
import "../styles/pages/PAGE-F05-02.css";

type Ck = { id: number; code: string; point: string; isConcealed: boolean };
type Item = {
  baselineId: number; revisionId: number; workItemId: number; name: string; phaseName: string; floorName: string; roomName: string;
  plannedFinish: string | null; cost: string | null; drawing: string; description: string; acceptanceCriteria: string;
  qcUserName: string; checkpoints: Ck[]; isResign: boolean; soon: boolean;
};
type Group = { key: string; name: string; items: Item[]; cost: string };
type Pending = { group: string; groups: Group[]; total: number; totalCost: string };

export default function BaselineSign() {
  const { pid } = useParams();
  const [sp, setSp] = useSearchParams();
  const group = sp.get("group") === "floor" ? "floor" : "phase";
  const { project, can, has } = useProject(pid);
  const { me } = useSession();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["baselines-pending", pid, group], queryFn: () => api<Pending>(`/projects/${pid}/baselines/pending?group=${group}`) });
  const owner = can("baseline.sign");
  const [opened, setOpened] = useState<Record<number, boolean>>({});
  const [sel, setSel] = useState<{ group: string; ids: number[] }>({ group: "", ids: [] });
  // 本页内刚签认 / 退回的条目：刷新列表后仍在原位显示印章，直到离开页面
  const [done, setDone] = useState<Record<number, { st: "signed" | "returned"; item: Item; group: string; reason?: string }>>({});
  const [signing, setSigning] = useState<Item[] | null>(null);
  const [returning, setReturning] = useState<Item | null>(null);
  const [just, setJust] = useState<number[]>([]);

  const unit = group === "phase" ? "工段" : "楼层";
  const groups: Group[] = (q.data?.groups || []).map((g) => ({ ...g, items: [...g.items] }));
  Object.values(done).forEach((d) => {
    let g = groups.find((x) => x.key === d.group);
    if (!g) { g = { key: d.group, name: d.item[group === "phase" ? "phaseName" : "floorName"], items: [], cost: "0" }; groups.push(g); }
    if (!g.items.some((i) => i.baselineId === d.item.baselineId)) g.items.push(d.item);
  });
  const groupName = (key: string) => groups.find((g) => g.key === key)?.name || "";

  const pick = (g: Group, it: Item, on: boolean) => {
    if (on && sel.group && sel.group !== g.key && sel.ids.length) {
      toast(`批量签认只能在同一${unit}内勾选，已清空「${groupName(sel.group)}」的选择`);
      setSel({ group: g.key, ids: [it.revisionId] });
      return;
    }
    const ids = on ? [...sel.ids.filter((i) => i !== it.revisionId), it.revisionId] : sel.ids.filter((i) => i !== it.revisionId);
    setSel({ group: g.key, ids });
  };
  const switchGroup = (g: string) => { setSel({ group: "", ids: [] }); setSp({ group: g }, { replace: true }); };

  const sign = useMutation({
    mutationFn: (items: Item[]) => api<{ count: number }>(`/projects/${pid}/baselines/sign`, { body: { revisionIds: items.map((i) => i.revisionId) }, headers: { "Idempotency-Key": idemKey() } }),
    onSuccess: (r, items) => {
      toast(`已签认 ${r.count} 项，生成 ${r.count} 条签认记录`);
      setDone((d) => ({ ...d, ...Object.fromEntries(items.map((i) => [i.baselineId, { st: "signed" as const, item: i, group: groupKeyOf(i) }])) }));
      setJust(items.map((i) => i.baselineId));
      setSel({ group: "", ids: [] });
      setSigning(null);
      qc.invalidateQueries({ queryKey: ["baselines-pending", pid] });
      qc.invalidateQueries({ queryKey: ["todo-count"] });
    },
    onError: (e) => { toast((e as ApiError).message || "提交失败，请重试"); setSigning(null); qc.invalidateQueries({ queryKey: ["baselines-pending", pid] }); },
  });
  const groupKeyOf = (it: Item) => groups.find((g) => g.items.some((i) => i.baselineId === it.baselineId))?.key || "";

  const banner = owner ? "逐项展开看完全部内容后才能签认。可勾选同一工段或同一楼层的多项一起签认，每项都会生成独立的签认记录。本项目任一业主签认即生效，记录署名为你本人，其他业主的同一待办同时消失。"
    : has("owner_agent") ? "业主代理人只能放行检查点，不能签认或退回基线。以下内容仅供查看。"
      : has("owner_member") ? "业主方成员只能查看，不能签认或退回基线。以下内容仅供查看。"
        : "基线由业主签认或退回。待签认期间基线锁定，需业主退回后才能修改；被退回的基线会出现在项目经理的待办中。";

  return (
    <Shell title="基线签认" sub={project && q.data ? `${project.name} · ${q.data.total} 项待签认 · 合计 ${money(q.data.totalCost)}` : undefined}>
      <div className="pg-f0502">
        <div className="banner note"><Icon name="alert" /><div>{banner}</div></div>
        <div className="bar">
          <div className="chips" role="group" aria-label="分组方式">
            <button type="button" className={`chip${group === "phase" ? " on" : ""}`} aria-pressed={group === "phase"} onClick={() => switchGroup("phase")}>按工段</button>
            <button type="button" className={`chip${group === "floor" ? " on" : ""}`} aria-pressed={group === "floor"} onClick={() => switchGroup("floor")}>按楼层</button>
          </div>
          <span className="spacer" />
          {owner && <span className="muted" style={{ fontSize: "var(--text-sm)" }}>{sel.ids.length ? `已选 ${sel.ids.length} 项 · ${groupName(sel.group)}` : "未选择"}</span>}
        </div>
        {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} retry={() => q.refetch()} /> : !groups.length ? (
          <div className="card"><Empty text="没有待签认的基线。" /></div>
        ) : groups.map((g) => {
          const pend = g.items.filter((i) => !done[i.baselineId]);
          const n = sel.group === g.key ? sel.ids.length : 0;
          return (
            <section key={g.key} className="card grp" aria-label={g.name}>
              <div className="card-hd">
                <h2>{group === "phase" ? `${g.name} 工段` : g.name}</h2><span className="cnt">{pend.length} 项待签认</span><span className="spacer" />
                {owner && pend.length > 0 && <button type="button" className="btn primary" disabled={!n} onClick={() => setSigning(pend.filter((i) => sel.ids.includes(i.revisionId)))}><Icon name="stamp" />签认本组所选（{n}）</button>}
              </div>
              <div className="items">
                {g.items.map((it) => {
                  const d = done[it.baselineId];
                  const canAct = owner && !d;
                  const open = !!opened[it.baselineId];
                  return (
                    <div key={it.baselineId} className={`it${open ? " open" : ""}`}>
                      <div className="row">
                        {canAct && <input type="checkbox" className="ck" aria-label={`选择 ${it.name}`} disabled={!open} title={open ? undefined : "请先展开查看完整内容"}
                          checked={sel.ids.includes(it.revisionId)} onChange={(e) => pick(g, it, e.target.checked)} />}
                        <div className="im">
                          <span className="nm">{it.name}</span>
                          <span className="meta">{group === "phase" ? `${it.floorName}${it.roomName ? ` ${it.roomName}` : ""}` : it.phaseName} · 计划完成 {it.plannedFinish} · {it.drawing}
                            {it.isResign && <span className="tag brand">重签</span>}
                            {it.soon && !d && <span className="tag bad">即将施工，基线未签认</span>}</span>
                        </div>
                        <div className="tail">
                          <span className="cost">{money(it.cost)}</span>
                          {d?.st === "signed" ? <Seal kind="pass" just={just.includes(it.baselineId)}>已签认</Seal> : d?.st === "returned" ? <span className="tag bad">已退回</span> : <Seal kind="pend">待签认</Seal>}
                          <button type="button" className="exp" aria-expanded={open} onClick={() => setOpened((o) => ({ ...o, [it.baselineId]: !open }))}>{open ? "收起" : "展开查看"}<Icon name="chevron" /></button>
                        </div>
                      </div>
                      <div className="detail">
                        <dl className="kv">
                          <dt>图纸分册与版本</dt><dd>{it.drawing}（已签认）</dd>
                          <dt>工作说明</dt><dd>{it.description}</dd>
                          <dt>验收标准</dt><dd>{it.acceptanceCriteria}</dd>
                          <dt>费用</dt><dd className="num">{money(it.cost)}</dd>
                          <dt>计划完成日期</dt><dd>{it.plannedFinish}</dd>
                          <dt>质检人</dt><dd>{it.qcUserName}</dd>
                          <dt>检查点</dt><dd><ul className="cks">{it.checkpoints.map((c) => <li key={c.id}><span className="idc">{c.code}</span><span>{c.point}{c.isConcealed ? "（隐蔽）" : ""}</span></li>)}</ul></dd>
                        </dl>
                        {d?.st === "returned" && <p className="ret">已退回：{d.reason}</p>}
                        {canAct && open && (
                          <div className="acts">
                            <button type="button" className="btn" onClick={() => setSigning([it])}><Icon name="stamp" />签认此项</button>
                            <button type="button" className="btn danger" onClick={() => setReturning(it)}><Icon name="back" />退回</button>
                          </div>
                        )}
                        <div className="acts"><Link className="btn sm" to={`/p/${pid}/work-items/${it.workItemId}`}>打开工作项</Link></div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}
        {signing && signing.length > 0 && (
          <Modal title={`签认 ${signing.length} 项基线`} onClose={() => setSigning(null)} footer={<>
            <button type="button" className="btn" onClick={() => setSigning(null)}>返回修改</button>
            <button type="button" className="btn primary" disabled={sign.isPending} onClick={() => sign.mutate(signing)}>{sign.isPending ? "提交中…" : "确认签认"}</button>
          </>}>
            <dl className="confirm-summary">
              {signing.map((i) => (
                <div key={i.baselineId} style={{ display: "contents" }}>
                  <dt>{i.name}</dt><dd>{i.drawing} · {money(i.cost)} · 计划完成 {i.plannedFinish} · 检查点 {i.checkpoints.length} 个</dd>
                </div>
              ))}
              <dt>合计</dt><dd className="num">{money(signing.reduce((s, i) => s + Number(i.cost || 0), 0))}</dd>
              <dt>签认人</dt><dd>{me?.name}（业主）</dd>
            </dl>
            <p className="hint">将生成 {signing.length} 条独立签认记录，每条包含签认人、时间和该项基线的完整内容快照。签认后不可撤回。</p>
          </Modal>
        )}
        {returning && <ReturnDialog pid={pid!} it={returning} me={me?.name || ""} onClose={() => setReturning(null)}
          onDone={(reason) => { setDone((d) => ({ ...d, [returning.baselineId]: { st: "returned", item: returning, group: groupKeyOf(returning), reason } })); setSel((s) => ({ ...s, ids: s.ids.filter((x) => x !== returning.revisionId) })); setReturning(null); }} />}
      </div>
    </Shell>
  );
}

function ReturnDialog({ pid, it, me, onClose, onDone }: { pid: string; it: Item; me: string; onClose: () => void; onDone: (reason: string) => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");
  const [step, setStep] = useState<1 | 2>(1);
  const m = useMutation({
    mutationFn: () => api(`/projects/${pid}/baselines/${it.baselineId}/return`, { body: { reason: reason.trim() }, headers: { "Idempotency-Key": idemKey() } }),
    onSuccess: () => { toast("已退回，项目经理将收到待办"); qc.invalidateQueries({ queryKey: ["baselines-pending", pid] }); qc.invalidateQueries({ queryKey: ["todo-count"] }); onDone(reason.trim()); },
    onError: (e) => { toast((e as ApiError).message || "提交失败，请重试"); setStep(1); },
  });
  if (step === 2) {
    return (
      <Modal title="确认退回基线" onClose={onClose} footer={<>
        <button type="button" className="btn" onClick={() => setStep(1)}>返回修改</button>
        <button type="button" className="btn danger" disabled={m.isPending} onClick={() => m.mutate()}>{m.isPending ? "提交中…" : "确认退回"}</button>
      </>}>
        <dl className="confirm-summary">
          <dt>基线</dt><dd>{it.name} · {it.drawing} · {money(it.cost)}</dd>
          <dt>退回理由</dt><dd>{reason.trim()}</dd>
          <dt>操作人</dt><dd>{me}（业主）</dd>
        </dl>
        <p className="hint">退回后基线状态为「已退回」，理由随基线保存，项目经理修改后可重新提交。</p>
      </Modal>
    );
  }
  return (
    <Modal title="退回基线" onClose={onClose} footer={<>
      <button type="button" className="btn" onClick={onClose}>取消</button>
      <button type="button" className="btn danger" onClick={() => (reason.trim() ? setStep(2) : setErr("请填写退回理由"))}>下一步</button>
    </>}>
      <p style={{ fontWeight: 600 }}>{it.name} · {it.drawing} · {money(it.cost)}</p>
      <Field label="退回理由" required error={err}>
        <textarea className="textarea" rows={3} maxLength={200} value={reason} placeholder="例如：费用含 2 道拉结筋，但验收标准写的是每 500mm 一道，请核对后重新提交" onChange={(e) => { setReason(e.target.value); setErr(""); }} />
      </Field>
    </Modal>
  );
}
