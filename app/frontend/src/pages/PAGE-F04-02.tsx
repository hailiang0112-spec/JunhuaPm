// PAGE-F04-02 · 图纸查看器：缩放、钉点图层、两版并排对比、待重签横幅、版本只读。AC-F04-04、AC-F04-05、AC-F04-08
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Shell } from "../layout/Shell";
import { ErrorState, Icon, Loading, Seal } from "../ui";
import { DrawingStage, fileSize, fmtDate, IC, Svg, type DrawingSet, type Pin, type Version, type VersionBrief } from "./draw-kit";
import "../styles/pages/PAGE-F04-02.css";

type WiDetail = {
  workItem: { id: number; name: string; floorName: string; roomName: string };
  baseline: { status: string; baseDrawingVersion: VersionBrief | null; resign: { newVersion: VersionBrief; oldVersion: VersionBrief | null } | null };
};
type Compare = { left: Version; right: Version; range: string; notes: Version[] };

const STATUS_TEXT: Record<string, string> = { 未核对: "待质检核对", 待放行: "结论一致 · 待业主放行", 不一致: "核对不一致", 已放行: "已放行", 放行后发现不一致: "放行后发现不一致" };

export default function Viewer() {
  const { pid, versionId } = useParams();
  const [sp] = useSearchParams();
  const wid = sp.get("workItem");
  const head = useQuery({ queryKey: ["drawing-version", pid, versionId], queryFn: () => api<Version>(`/projects/${pid}/drawing-versions/${versionId}`) });
  const sets = useQuery({ queryKey: ["drawing-sets", pid], queryFn: () => api<{ items: DrawingSet[] }>(`/projects/${pid}/drawing-sets`) });
  const wi = useQuery({ queryKey: ["wi-detail", pid, wid], queryFn: () => api<WiDetail>(`/projects/${pid}/work-items/${wid}/detail`), enabled: !!wid });
  const set = sets.data?.items.find((s) => s.id === head.data?.setId);
  const versions = set?.versions || [];

  const [sel, setSel] = useState<number>(Number(versionId));
  const [zoom, setZoom] = useState(100);
  const [pins, setPins] = useState(true);
  const [cmp, setCmp] = useState(!!sp.get("compare"));
  const [left, setLeft] = useState<number>(Number(sp.get("compare")) || Number(versionId));
  const [right, setRight] = useState<number>(Number(versionId));
  const [pageNo, setPageNo] = useState(1);
  const [cur, setCur] = useState<Pin | null>(null);
  useEffect(() => { setSel(Number(versionId)); }, [versionId]);
  useEffect(() => { setCur(null); setPageNo(1); }, [sel]);

  const v = useQuery({ queryKey: ["drawing-version", pid, String(sel)], queryFn: () => api<Version>(`/projects/${pid}/drawing-versions/${sel}`) });
  const pinsQ = useQuery({ queryKey: ["drawing-pins", pid, sel], queryFn: () => api<{ items: Pin[] }>(`/projects/${pid}/drawing-versions/${sel}/checkpoints`) });

  if (head.isLoading || sets.isLoading) return <Shell title="图纸查看器"><Loading /></Shell>;
  if (head.error || !head.data) return <Shell title="图纸查看器"><ErrorState error={head.error} retry={() => head.refetch()} /></Shell>;

  const base = wi.data?.baseline.baseDrawingVersion;
  const latestSigned = set?.currentSignedVersion;
  const resign = wi.data?.baseline.status === "待重签" ? wi.data.baseline.resign : null;
  const optLabel = (x: Version) => {
    const tags = [x.status];
    if (base && base.id === x.id && wid) tags.push("本工作项基线引用");
    if (x.isCurrentSigned) tags.push("当前签认版");
    return `V${x.versionNo} · ${tags.join(" · ")}`;
  };
  const enterCompare = () => {
    if (!cmp) {
      setLeft(base && wid ? base.id : sel);
      setRight(versions[0]?.id === (base && wid ? base.id : sel) ? versions[1]?.id ?? sel : versions[0]?.id ?? sel);
    }
    setCmp(!cmp);
  };
  const title = `${head.data.setName}${wi.data?.workItem.floorName && wi.data.workItem.floorName !== "全楼通用" ? ` · ${wi.data.workItem.floorName}` : ""}`;
  const sub = wi.data
    ? `从工作项「${wi.data.workItem.name}」打开 · 基线引用 ${base ? `V${base.versionNo}` : "（未引用）"} · 当前签认版 ${latestSigned ? `V${latestSigned.versionNo}` : "无"}`
    : `当前签认版 ${latestSigned ? `V${latestSigned.versionNo}` : "无"}`;
  const pinList = v.data?.status === "已签认" ? pinsQ.data?.items || [] : [];
  const page = v.data?.pages?.find((p) => p.pageNo === pageNo) || v.data?.pages?.[0];

  return (
    <Shell title={title} sub={sub}
      crumb={<><Link to={`/p/${pid}/drawings`}>图纸</Link><Icon name="right" /><Link to={`/p/${pid}/drawings?volume=${head.data.setId}`}>{head.data.setName}</Link><Icon name="right" /><span>查看器</span></>}>
      <div className="pg-f0402">
        {resign && (
          <div className="banner" role="note"><Icon name="alert" />
            <div><b>图纸已更新，基线待重签。</b>本工作项基线引用 V{resign.oldVersion?.versionNo}；{resign.newVersion.setName} V{resign.newVersion.versionNo} 已于 {fmtDate(resign.newVersion.signedAt)} 签认。重签前现场仍按 V{resign.oldVersion?.versionNo} 施工与核对。</div>
            <Link className="btn sm act" to={`/p/${pid}/work-items/${wid}`}>查看工作项</Link>
          </div>
        )}
        <section className="card" aria-label="查看控制">
          <div className="tools">
            {!cmp && (
              <div className="field"><label htmlFor="ver">版本</label>
                <select className="select" id="ver" value={sel} onChange={(e) => setSel(Number(e.target.value))}>
                  {versions.map((x) => <option key={x.id} value={x.id}>{optLabel(x)}</option>)}
                </select></div>
            )}
            <div className="zoom" role="group" aria-label="缩放">
              <button type="button" className="icon-btn" aria-label="缩小" disabled={zoom <= 50} onClick={() => setZoom((z) => Math.max(50, z - 25))}><Svg d={IC.minus} /></button>
              <span className="pct" aria-live="polite">{zoom}%</span>
              <button type="button" className="icon-btn" aria-label="放大" disabled={zoom >= 300} onClick={() => setZoom((z) => Math.min(300, z + 25))}><Svg d={IC.plus} /></button>
              <button type="button" className="icon-btn" aria-label="适应宽度" onClick={() => setZoom(100)}><Svg d={IC.fit} /></button>
            </div>
            {!cmp && <label className="tgl"><input type="checkbox" checked={pins} onChange={(e) => setPins(e.target.checked)} />检查点钉点</label>}
            <span className="spacer" />
            <button type="button" className="btn" id="cmpBtn" aria-pressed={cmp} disabled={versions.length < 2} onClick={enterCompare}><Svg d={IC.split} />{cmp ? "退出对比" : "两版并排对比"}</button>
          </div>
        </section>

        {!cmp ? (
          <div className="vgrid">
            <section className="card" aria-label="图纸">
              {v.data && <VersionHead v={v.data} />}
              {v.data && (v.data.pages?.length || 0) > 1 && (
                <div className="pages">{v.data.pages!.map((p) => <button key={p.pageNo} type="button" className={`chip${p.pageNo === page?.pageNo ? " on" : ""}`} onClick={() => setPageNo(p.pageNo)}>第 {p.pageNo} 页</button>)}</div>
              )}
              {v.isLoading ? <div className="vwrap"><div className="skeleton" style={{ height: "100%" }} /></div>
                : <DrawingStage page={page} pins={pinList} zoom={zoom} onZoom={setZoom} showPins={pins} current={cur?.id} onPin={setCur} />}
              <div className="legend" aria-label="钉点图例">
                <span><i style={{ background: "var(--muted)" }} />未核对</span><span><i style={{ background: "var(--warn)" }} />待放行</span>
                <span><i style={{ background: "var(--danger)" }} />不一致</span><span><i style={{ background: "var(--success)" }} />已放行</span>
                <span><i style={{ background: "var(--info)" }} />代理放行</span>
              </div>
            </section>
            <aside className="card pinpanel" aria-labelledby="ppH">
              <div className="card-hd"><h2 id="ppH">钉点详情</h2></div>
              <div className="card-bd">
                {v.data?.status !== "已签认" ? <p className="empty">待签认版本不能作为基线或钉点底图，没有检查点钉点。</p>
                  : cur ? <PinInfo pid={pid!} p={cur} />
                    : pinList.length ? <p className="empty">点击图上的钉点查看检查点。本版共 {pinList.length} 个钉点。</p>
                      : <p className="empty">该版本尚无检查点钉点。</p>}
              </div>
            </aside>
          </div>
        ) : (
          <ComparePane pid={pid!} setId={head.data.setId} versions={versions} left={left} right={right} setLeft={setLeft} setRight={setRight} zoom={zoom} setZoom={setZoom} />
        )}
      </div>
    </Shell>
  );
}

function VersionHead({ v }: { v: Version }) {
  const signed = v.status === "已签认";
  return (
    <div className="vhd">
      {signed ? <Seal kind="pass">已签认</Seal> : v.status === "已被新版取代" ? <span className="tag">已被新版取代</span> : <Seal kind="pend">待签认</Seal>}
      <span>V{v.versionNo} · {v.file.name}（{fileSize(v.file.size)}）· {signed ? `${v.signedBy} ${fmtDate(v.signedAt)} 签认` : v.status === "已被新版取代" ? "未签认，已被新版取代，不能作为基线或钉点底图" : "待业主签认，不能作为基线或钉点底图"}</span>
      <span className="spacer" />
      <span className="ro"><Svg d={IC.lock} />已发布版本只读，不可删除或替换</span>
    </div>
  );
}

function PinInfo({ pid, p }: { pid: string; p: Pin }) {
  const seal = p.labels.includes("超时") || p.labels.includes("未放行先覆盖") || p.status === "不一致" || p.status === "放行后发现不一致"
    ? <Seal kind="stop">{p.labels.includes("超时") ? "超时" : p.labels.includes("未放行先覆盖") ? "未放行先覆盖" : p.status}</Seal>
    : p.status === "已放行" ? <Seal kind={p.isProxyReleased ? "proxy" : "pass"}>{p.isProxyReleased ? "代理放行" : "已放行"}</Seal>
      : p.status === "待放行" ? <Seal kind="pend">待放行</Seal>
        : p.labels.includes("不得覆盖") ? <Seal kind="stop">不得覆盖</Seal> : <span className="tag">{p.status}</span>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      <div className="row"><span className="mono">{p.code}</span><b>{p.point}</b>{seal}</div>
      <dl className="kv">
        <dt>位置</dt><dd>{p.floorName} · {p.roomName || "本层通用"} · {p.isConcealed ? "隐蔽" : "非隐蔽"}</dd>
        <dt>工作项</dt><dd>{p.workItemName}</dd>
        <dt>情况</dt><dd>{STATUS_TEXT[p.status] || p.status}{p.labels.length ? ` · ${p.labels.join("、")}` : ""}</dd>
      </dl>
      <Link className="btn" to={`/p/${pid}/checkpoints/${p.id}`}>打开检查点</Link>
    </div>
  );
}

function ComparePane({ pid, setId, versions, left, right, setLeft, setRight, zoom, setZoom }: {
  pid: string; setId: number; versions: Version[]; left: number; right: number; setLeft: (n: number) => void; setRight: (n: number) => void; zoom: number; setZoom: (n: number) => void;
}) {
  const same = left === right;
  const q = useQuery({ queryKey: ["drawing-compare", pid, setId, left, right], queryFn: () => api<Compare>(`/projects/${pid}/drawing-sets/${setId}/compare?from=${left}&to=${right}`), enabled: !same });
  const side = (val: number, set: (n: number) => void, label: string, data?: Version) => (
    <section className="card" aria-label={label}>
      <div className="vhd">
        <select className="select" aria-label={label} style={{ width: "auto" }} value={val} onChange={(e) => set(Number(e.target.value))}>
          {versions.map((x) => <option key={x.id} value={x.id}>V{x.versionNo} · {x.status}</option>)}
        </select>
        {data && <span className="muted">{data.file.name}</span>}
      </div>
      <DrawingStage page={data?.pages?.[0]} zoom={zoom} onZoom={setZoom} showPins={false} />
    </section>
  );
  return (
    <>
      <div className="cmp">
        {side(left, setLeft, "左侧版本", q.data?.left)}
        {side(right, setRight, "右侧版本", q.data?.right)}
      </div>
      <section className="card" aria-labelledby="nH">
        <div className="card-hd"><h2 id="nH">两版之间的改动说明</h2><span className="spacer" /><span className="muted" style={{ fontSize: "var(--text-sm)" }}>{same ? "" : q.data?.range}</span></div>
        <div className="card-bd notes">
          {same ? <p className="muted">请选择两个不同的版本</p> : q.isLoading ? <div className="skeleton" /> : q.error ? <ErrorState error={q.error} /> : q.data?.notes.map((n) => (
            <div key={n.id} className="note">
              <div className="h"><b>V{n.versionNo}</b>{n.status === "已签认" ? <Seal kind="pass">已签认</Seal> : n.status === "已被新版取代" ? <span className="tag">已被新版取代 · 未签认</span> : <Seal kind="pend">待签认</Seal>}</div>
              <p>{n.changeNote || "首版。"}</p>
              <span className="m">{n.createdBy} {fmtDate(n.createdAt)} 发布 · {n.signedBy ? `${n.signedBy} ${fmtDate(n.signedAt)} 签认` : "待业主签认"} · 受影响工作项 {n.affectedCount} 项</span>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
