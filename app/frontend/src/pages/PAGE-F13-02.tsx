// PAGE-F13-02 · 公告栏（REQ-F13-02：留言按发布者角色归入业主 / 工地经理 / 设计师板块；回复正序挂在原留言下；只能删自己的留言）
import { useState, type FormEvent } from "react";
import { useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Shell } from "../layout/Shell";
import { useProject } from "../session";
import { ConfirmDialog, ErrorState, Icon, useApiError, useToast } from "../ui";
import "../styles/pages/PAGE-F13-02.css";

type Board = "owner" | "site" | "design";
type Msg = {
  id: number; board: Board; authorName: string; roleLabel: string; createdAt: string; body: string; deleted: boolean;
  deletedAt: string | null; deletedBy: string | null; canDelete: boolean; replies: Msg[];
};
type Data = { boards: Record<Board, Msg[]>; boardNames: Record<Board, string>; me: { name: string; roleLabel: string; board: Board; boardName: string } };
const ORDER: [Board, string, string][] = [["owner", "业主", "home"], ["site", "工地经理", "users"], ["design", "设计师", "map"]];
const hm = (s: string | null) => (s ? `${s.slice(0, 10)} ${s.slice(11, 16)}` : "");
const excerpt = (s: string) => (s.length > 40 ? s.slice(0, 40) + "…" : s);

export default function Notices() {
  const { pid } = useParams();
  const { project, can } = useProject(pid);
  const toast = useToast();
  const onErr = useApiError();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["notices", pid], queryFn: () => api<Data>(`/projects/${pid}/notices`), enabled: !!pid });
  const [cur, setCur] = useState<Board>("owner");
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  const [replyTo, setReplyTo] = useState<number | null>(null);
  const [reply, setReply] = useState("");
  const [del, setDel] = useState<Msg | null>(null);
  const canPost = can("notice.post");
  const reload = () => qc.invalidateQueries({ queryKey: ["notices", pid] });

  const post = useMutation({
    mutationFn: (body: string) => api<Msg>(`/projects/${pid}/notices`, { body: { body } }),
    onSuccess: (m) => { setText(""); setCur(m.board); toast(`已发布到「${q.data?.boardNames[m.board]}」板块`); reload(); },
    onError: onErr,
  });
  const sendReply = useMutation({
    mutationFn: ({ id, body }: { id: number; body: string }) => api<Msg>(`/projects/${pid}/notices/${id}/replies`, { body: { body } }),
    onSuccess: () => { setReply(""); setReplyTo(null); toast("已回复"); reload(); },
    onError: onErr,
  });
  const remove = useMutation({
    mutationFn: (m: Msg) => api(`/projects/${pid}/notices/${m.id}`, { method: "DELETE" }),
    onSuccess: () => { setDel(null); toast("留言已删除"); reload(); },
    onError: (e) => { setDel(null); onErr(e); },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = text.trim();
    if (!v) { setErr("请填写留言内容"); return; }
    setErr("");
    post.mutate(v);
  };

  const msg = (m: Msg, isReply: boolean) => (
    <>
      <div className="who"><span className="av" aria-hidden="true">{m.authorName.slice(0, 1)}</span><b>{m.authorName}</b><span className="r">{m.roleLabel}</span><span className="t">{hm(m.createdAt)}</span></div>
      {m.deleted ? (
        <><p className="msg del">该留言已删除</p><div className="del-meta">删除记录：{m.deletedBy} · {hm(m.deletedAt)}</div></>
      ) : <p className="msg">{m.body}</p>}
      <div className="ops">
        {!isReply && !m.deleted && canPost && (
          <button className="op-btn" type="button" onClick={() => { setReplyTo(replyTo === m.id ? null : m.id); setReply(""); }}><Icon name="chat" />回复</button>
        )}
        {m.canDelete && <button className="op-btn danger" type="button" onClick={() => setDel(m)}><Icon name="close" />删除</button>}
      </div>
    </>
  );

  const data = q.data;
  return (
    <Shell title="公告栏" sub={`${project?.name || ""} · 各方留言沟通，全程留痕`}>
      {canPost && (
        <section className="card" aria-labelledby="cpTitle">
          <div className="card-hd"><h2 id="cpTitle">发布留言</h2></div>
          <form className="card-bd composer" onSubmit={submit} noValidate>
            <div className={`field${err ? " invalid" : ""}`}>
              <label htmlFor="cpText" className="sr">留言内容</label>
              <textarea className="textarea" id="cpText" rows={3} maxLength={500} value={text} onChange={(e) => setText(e.target.value)}
                placeholder="写下要告知各方的事，例如：明天下午 3 点到现场放行一楼厨房检查点" />
              {err && <span className="err">{err}</span>}
            </div>
            <div className="row">
              <span className="to"><Icon name="user" />将以 <b>{data ? `${data.me.name}（${data.me.roleLabel}）` : "…"}</b> 的身份发布到「<b>{data?.me.boardName || "…"}</b>」板块（按角色自动归入）</span>
              <button className="btn primary" type="submit" disabled={post.isPending}><Icon name="chat" />发布</button>
            </div>
          </form>
        </section>
      )}
      {q.isLoading ? (
        <section className="card"><div className="card-bd" aria-busy="true"><div className="skeleton" style={{ width: "45%", marginBottom: 12 }} /><div className="skeleton" style={{ marginBottom: 12 }} /><div className="skeleton" style={{ width: "70%" }} /></div></section>
      ) : q.error || !data ? (
        <section className="card"><ErrorState error={q.error} retry={() => q.refetch()} /></section>
      ) : (
        <>
          <div className="bd-tabs" role="tablist" aria-label="板块">
            {ORDER.map(([b, name]) => <button key={b} role="tab" aria-selected={cur === b} className={`chip${cur === b ? " on" : ""}`} type="button" onClick={() => setCur(b)}>{name}</button>)}
          </div>
          <div className="boards">
            {ORDER.map(([b, name, icon]) => {
              const list = data.boards[b] || [];
              return (
                <section key={b} className={`card board${cur === b ? " cur" : ""}`} aria-labelledby={`bd-${b}`}>
                  <div className="card-hd"><Icon name={icon} /><h2 id={`bd-${b}`}>{name}</h2><span className="tag">{list.length} 条</span></div>
                  <div className="card-bd">
                    {!list.length ? (
                      <div className="state nt-state"><div className="ic"><Icon name="chat" /></div><h3>还没有留言</h3><p>{name}板块的留言会显示在这里。</p></div>
                    ) : list.map((p) => (
                      <article key={p.id} className="post">
                        {msg(p, false)}
                        {p.replies.length > 0 && <div className="replies">{p.replies.map((r) => <div key={r.id}>{msg(r, true)}</div>)}</div>}
                        {replyTo === p.id && (
                          <form className="reply-box" onSubmit={(e) => { e.preventDefault(); if (reply.trim()) sendReply.mutate({ id: p.id, body: reply.trim() }); }}>
                            <input className="input" autoFocus maxLength={500} value={reply} onChange={(e) => setReply(e.target.value)} placeholder={`回复 ${p.authorName}`} aria-label="回复内容" />
                            <button className="btn sm" type="submit" disabled={sendReply.isPending || !reply.trim()}>回复</button>
                          </form>
                        )}
                      </article>
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        </>
      )}
      {del && (
        <ConfirmDialog title="删除留言" danger confirmText="确认删除" busy={remove.isPending} onClose={() => setDel(null)} onConfirm={() => remove.mutate(del)}
          summary={[["留言", excerpt(del.body)], ["发布时间", hm(del.createdAt)], ["删除后", "显示为「该留言已删除」，删除记录保留"]]} />
      )}
    </Shell>
  );
}
