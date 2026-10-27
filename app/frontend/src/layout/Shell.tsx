// 应用外壳（_外壳约定.md）：电脑左侧导航、手机底部 4 标签 + 「更多」、工地切换器、顶栏。
import { useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useProject, useSession } from "../session";
import { Icon } from "../ui";

export function lastProjectId(meProjects: { id: number }[] | undefined) {
  const saved = Number(localStorage.getItem("jh_last_project") || 0);
  if (meProjects?.some((p) => p.id === saved)) return saved;
  return meProjects?.[0]?.id;
}

type NavItem = { to: string; label: string; icon?: string; dot?: string; badge?: number; end?: boolean };

function NavLinks({ groups, onPick, active }: { groups: [string, NavItem[]][]; onPick?: () => void; active?: string }) {
  return (
    <>
      {groups.map(([g, items], gi) => (
        <div key={gi}>
          {g && <div className="navgroup">{g}</div>}
          {items.map((it) => (
            <NavLink key={it.to + it.label} to={it.to} end={it.end ?? true} onClick={onPick} className={({ isActive }) => "navitem" + (isActive || it.to === active ? " on" : "")}>
              {it.dot ? <span className="phase-dot" style={{ background: `var(${it.dot})` }} aria-hidden="true" /> : <Icon name={it.icon || "list"} />}
              <span className="nm">{it.label}</span>
              {!!it.badge && <span className="badge">{it.badge}</span>}
            </NavLink>
          ))}
        </div>
      ))}
    </>
  );
}

/** activeNav：详情页没有自己的导航项时，指定要高亮的导航路径（如工作项详情高亮所属工段） */
export function Shell({ title, sub, actions, children, crumb, activeNav }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode; children: ReactNode; crumb?: ReactNode; activeNav?: string }) {
  const { pid: routePid } = useParams();
  const { me } = useSession();
  const pid = routePid ? Number(routePid) : lastProjectId(me?.projects);
  if (routePid) localStorage.setItem("jh_last_project", routePid);
  const { project } = useProject(pid);
  const counts = useQuery({ queryKey: ["todo-count"], queryFn: () => api<{ total: number; checkpoints: number }>("/todos/count"), refetchInterval: 60000, enabled: !!me && !me.mustChangePassword });
  const [more, setMore] = useState(false);
  const [pick, setPick] = useState(false);
  const nav = useNavigate();
  const { pathname } = useLocation();
  // 底部标签高亮：前三个标签之外的页面一律高亮「更多」（_外壳约定.md）
  const tab = pathname === "/" ? "todo" : /\/checkpoints(\/|$)/.test(pathname) ? "cp" : /\/drawings(\/|$)/.test(pathname) ? "dw" : "more";
  const p = pid ? `/p/${pid}` : "";
  const groups: [string, NavItem[]][] = [["", [{ to: "/", label: "我的待办", icon: "todo", badge: counts.data?.total }]]];
  if (pid) {
    groups.push(["总览", [{ to: p, label: "项目总览", icon: "overview" }, { to: `${p}/floors`, label: "楼层 / 房间", icon: "layers" }]]);
    groups.push(["施工阶段", (project?.phases || []).map((ph) => ({ to: `${p}/phase/${ph.id}`, label: ph.name, dot: ph.colorVar }))]);
    groups.push(["证据链", [
      { to: `${p}/drawings`, label: "图纸", icon: "map", end: false },
      { to: `${p}/baselines`, label: "基线签认", icon: "stamp" },
      { to: `${p}/checkpoints`, label: "检查点", icon: "pin", badge: counts.data?.checkpoints, end: false },
      { to: `${p}/changes`, label: "变更单", icon: "doc", end: false },
      { to: `${p}/issues`, label: "问题", icon: "alert" },
    ]]);
    groups.push(["房屋档案", [
      { to: `${p}/archive`, label: "档案资料", icon: "folder" },
      { to: `${p}/supplements`, label: "补充事项", icon: "list" },
      { to: `${p}/notices`, label: "公告栏", icon: "chat" },
      { to: `${p}/payments`, label: "付款节点", icon: "money" },
    ]]);
    groups.push(["项目设置", [
      { to: `${p}/members`, label: "成员与项目", icon: "users" },
      { to: `${p}/structure`, label: "项目结构", icon: "home" },
      { to: `${p}/import`, label: "数据导入导出", icon: "download" },
      { to: `${p}/audit`, label: "审计与证据包", icon: "shield" },
    ]]);
  }
  const company: NavItem[] = [];
  if (me?.isCompanyAdmin) company.push({ to: "/company/projects", label: "项目管理", icon: "briefcase" }, { to: "/company/templates", label: "公司模板", icon: "grid" });
  company.push({ to: "/experience", label: "公司经验库", icon: "book" });
  groups.push(["公司", company]);
  groups.push(["", [{ to: "/me", label: "个人设置", icon: "user" }]]);

  return (
    <div className="app">
      <aside className="side">
        <div className="brand"><span className="logo">君</span><span className="nm">君华 · 项目管理</span></div>
        <button type="button" className="sitepick" aria-label={`切换工地，当前${project?.name || "全部工地"}`} onClick={() => setPick(true)}>
          <Icon name="home" /><span className="nm">{routePid ? project?.name || "…" : "全部工地"}</span><span className="spacer" /><Icon name="chevron" />
        </button>
        <nav aria-label="工地导航"><NavLinks groups={groups} active={activeNav} /></nav>
      </aside>
      <main className="main" id="main">
        {crumb && <div className="crumb">{crumb}</div>}
        <header className="topbar">
          <div className="ttl"><h1>{title}</h1>{sub && <div className="sub">{sub}</div>}</div>
          <span className="spacer" />
          {actions}
        </header>
        {children}
      </main>
      <nav className="tabbar" aria-label="手机底部导航">
        <Link className={"tab" + (tab === "todo" ? " on" : "")} to="/"><span className="tab-ic"><Icon name="todo" />{!!counts.data?.total && <span className="tab-badge">{counts.data.total}</span>}</span>待办</Link>
        <Link className={"tab" + (tab === "cp" ? " on" : "")} to={pid ? `${p}/checkpoints` : "/"}><span className="tab-ic"><Icon name="pin" />{!!counts.data?.checkpoints && <span className="tab-badge">{counts.data.checkpoints}</span>}</span>检查点</Link>
        <Link className={"tab" + (tab === "dw" ? " on" : "")} to={pid ? `${p}/drawings` : "/"}><span className="tab-ic"><Icon name="map" /></span>图纸</Link>
        <button type="button" className={"tab" + (tab === "more" ? " on" : "")} aria-haspopup="dialog" onClick={() => setMore(true)}><Icon name="more" />更多</button>
      </nav>
      {more && (
        <div className="sheet-mask" onMouseDown={(e) => e.target === e.currentTarget && setMore(false)}>
          <div className="sheet" role="dialog" aria-label="全部导航"><nav className="sheet-nav"><NavLinks groups={groups} active={activeNav} onPick={() => setMore(false)} /></nav></div>
        </div>
      )}
      {pick && (
        <div className="sheet-mask" onMouseDown={(e) => e.target === e.currentTarget && setPick(false)}>
          <div className="sheet" role="dialog" aria-label="切换工地">
            <div className="navgroup">切换工地</div>
            {(me?.projects || []).map((x) => (
              <button key={x.id} type="button" className="navitem link-btn" style={{ width: "100%" }} onClick={() => { setPick(false); nav(`/p/${x.id}`); }}>
                <Icon name="home" /><span className="nm">{x.name}</span><span className="tag">{x.roleLabels.join("、")}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** 卡片容器 */
export function Card({ title, extra, children, bodyClass = "card-bd" }: { title?: ReactNode; extra?: ReactNode; children: ReactNode; bodyClass?: string }) {
  return (
    <section className="card">
      {title !== undefined && <div className="card-hd"><h2>{title}</h2><span className="spacer" />{extra}</div>}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}
