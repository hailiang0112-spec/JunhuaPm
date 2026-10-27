// 图纸 / 基线页面（PAGE-F04-01、F04-02、F05-01、F05-02）共用：类型、格式化、图纸画布（缩放、钉点）。
import { useEffect, useRef, useState, type MouseEvent as RMouseEvent, type ReactNode } from "react";
import type { UploadedFile } from "../api";
import "../styles/pages/drawing.css";

export type VersionBrief = { id: number; setId: number; setName: string; versionNo: number; status: string; isSigned: boolean; signedAt: string | null; isCurrentSigned: boolean };
export type AffectedItem = { id: number; name: string; floorName: string; roomName: string; phaseName: string; baselineStatus: string };
export type Page = { pageNo: number; imageUrl: string; width: number; height: number };
export type Version = {
  id: number; setId: number; setName: string; versionNo: number; status: string; changeNote: string;
  file: UploadedFile; cadFile: UploadedFile | null; createdBy: string; createdAt: string;
  signedBy: string | null; signedAt: string | null; signSha256: string | null; isCurrentSigned: boolean;
  affectedWorkItems: AffectedItem[]; affectedCount: number; affectedSignedCount: number; thumbUrl: string | null;
  pageCount: number; pages?: Page[];
};
export type DrawingSet = { id: number; name: string; currentSignedVersion: Version | null; hasPending: boolean; nextVersionNo: number; versions: Version[] };
export type Pin = {
  id: number; code: string; point: string; isConcealed: boolean; status: string; pageNo: number; x: number; y: number;
  labels: string[]; isProxyReleased?: boolean; workItemId?: number; workItemName?: string; floorName?: string; roomName?: string;
};

export const SIGNED = "已签认";
export const fmtTime = (s?: string | null) => (s ? s.slice(0, 16).replace("T", " ") : "");
export const fmtDate = (s?: string | null) => (s ? s.slice(0, 10) : "");
export const fileSize = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`);
export const shaShort = (s: string) => `${s.slice(0, 4)} ${s.slice(4, 8)} … ${s.slice(-4)}`;
export const ver = (v: { versionNo: number } | null | undefined) => (v ? `V${v.versionNo}` : "");

/** 钉点颜色按检查点状态（DEC-209）：未核对灰、待放行橙、不一致红、已放行绿、代理放行青。 */
export function pinClass(p: Pin) {
  if (p.status === "已放行") return p.isProxyReleased ? "s-proxy" : "s-pass";
  if (p.status === "待放行") return "s-pend";
  if (p.status === "不一致" || p.status === "放行后发现不一致") return "s-stop";
  return "s-none";
}

export function Svg({ d }: { d: string }) {
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><path d={d} /></svg>;
}
export const IC = {
  minus: "M5 12h14", plus: "M12 5v14M5 12h14", fit: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12ZM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z",
  split: "M3 4h18v16H3zM12 4v16", lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
};

/**
 * 图纸画布：服务端渲染好的页面图 + 钉点图层。宽度按缩放百分比；鼠标拖动平移，双指缩放。
 * pick 模式下点击图纸返回归一化坐标（AC-F06-01，与显示分辨率无关）。
 */
export function DrawingStage({ page, pins = [], zoom = 100, onZoom, current, onPin, onPick, picked, className = "vwrap", showPins = true, children }: {
  page: Page | undefined; pins?: Pin[]; zoom?: number; onZoom?: (z: number) => void; current?: number | null;
  onPin?: (p: Pin) => void; onPick?: (x: number, y: number) => void; picked?: { x: number; y: number } | null;
  className?: string; showPins?: boolean; children?: ReactNode;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; l: number; t: number; moved: boolean } | null>(null);
  const pinch = useRef<{ d: number; z: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [page?.imageUrl]);

  const onDown = (e: RMouseEvent) => {
    if (onPick || !wrap.current) return;
    drag.current = { x: e.clientX, y: e.clientY, l: wrap.current.scrollLeft, t: wrap.current.scrollTop, moved: false };
    setDragging(true);
  };
  useEffect(() => {
    const move = (e: MouseEvent) => {
      const g = drag.current;
      if (!g || !wrap.current) return;
      if (Math.abs(e.clientX - g.x) + Math.abs(e.clientY - g.y) > 3) g.moved = true;
      wrap.current.scrollLeft = g.l - (e.clientX - g.x);
      wrap.current.scrollTop = g.t - (e.clientY - g.y);
    };
    const up = () => { drag.current = null; setDragging(false); };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
  }, []);
  useEffect(() => {
    const el = wrap.current;
    if (!el || !onZoom) return;
    const dist = (t: TouchList) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
    const start = (e: TouchEvent) => { if (e.touches.length === 2) pinch.current = { d: dist(e.touches), z: zoom }; };
    const move = (e: TouchEvent) => {
      if (e.touches.length !== 2 || !pinch.current) return;
      e.preventDefault();
      const z = Math.round((pinch.current.z * dist(e.touches)) / pinch.current.d / 5) * 5;
      onZoom(Math.min(300, Math.max(50, z)));
    };
    const end = () => { pinch.current = null; };
    el.addEventListener("touchstart", start, { passive: true });
    el.addEventListener("touchmove", move, { passive: false });
    el.addEventListener("touchend", end);
    return () => { el.removeEventListener("touchstart", start); el.removeEventListener("touchmove", move); el.removeEventListener("touchend", end); };
  }, [onZoom, zoom]);

  const pick = (e: RMouseEvent<HTMLDivElement>) => {
    if (!onPick) return;
    const r = e.currentTarget.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
    onPick(Math.round(x * 1000) / 1000, Math.round(y * 1000) / 1000);
  };

  if (!page) return <div className={className}><div className="state">该版本还没有可显示的页面图。</div></div>;
  return (
    <div ref={wrap} className={`${className}${dragging ? " drag" : ""}${showPins ? "" : " nopins"}`} onMouseDown={onDown}>
      {failed ? (
        <div className="state">图纸加载失败，请重试 <button type="button" className="btn sm" onClick={() => setFailed(false)}>重试</button></div>
      ) : (
        <div className="dstage" style={{ width: `${zoom}%` }} onClick={pick}>
          <img src={page.imageUrl} alt={`图纸第 ${page.pageNo} 页`} width={page.width} height={page.height} draggable={false} onError={() => setFailed(true)} />
          {pins.filter((p) => p.pageNo === page.pageNo).map((p) => (
            <button key={p.id} type="button" className={`dpin ${pinClass(p)}${current === p.id ? " cur" : ""}`} style={{ left: `${p.x * 100}%`, top: `${p.y * 100}%` }}
              aria-label={`${p.code} ${p.point}`} title={`${p.code} ${p.point}`}
              onMouseDown={(e) => e.stopPropagation()} onClick={(e) => { e.stopPropagation(); onPin?.(p); }}>
              {p.code.replace(/^CK-/, "")}
            </button>
          ))}
          {picked && <span className="dpin s-new" style={{ left: `${picked.x * 100}%`, top: `${picked.y * 100}%` }} aria-hidden="true">新</span>}
          {children}
        </div>
      )}
    </div>
  );
}
