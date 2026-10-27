// 登录态与当前项目上下文：角色、权限点（服务端判定为准，前端只做隐藏，蓝图 §3）。
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type MeProject = { id: number; name: string; status: string; roles: string[]; roleLabels: string[]; permissions: string[] };
export type Me = { id: number; name: string; phone: string; isCompanyAdmin: boolean; mustChangePassword: boolean; projects: MeProject[] };

type Ctx = { me: Me | null; loading: boolean; refresh: () => Promise<void>; setMe: (m: Me | null) => void };
const SessionCtx = createContext<Ctx>({ me: null, loading: true, refresh: async () => {}, setMe: () => {} });

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    try {
      const s = await api<{ authenticated: boolean }>("/auth/csrf");
      setMe(s.authenticated ? await api<Me>("/me") : null);
    } catch {
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);
  return <SessionCtx.Provider value={{ me, loading, refresh, setMe }}>{children}</SessionCtx.Provider>;
}

export const useSession = () => useContext(SessionCtx);

export type Phase = { id: number; code: string; name: string; colorVar: string };
export type ProjectInfo = {
  id: number; name: string; address: string; status: string; plannedStart: string; plannedHandover: string;
  actualHandover: string | null; releaseTimeoutHours: number; roles: string[]; roleLabels: string[]; permissions: string[];
  phases: Phase[]; stats: Record<string, number>;
};

export function useProject(pid: string | number | undefined) {
  const { me } = useSession();
  // 强制改密期间服务端只放行 /me 与改密接口，不请求项目数据
  const q = useQuery({ queryKey: ["project", String(pid)], queryFn: () => api<ProjectInfo>(`/projects/${pid}`), enabled: !!pid && !!me && !me.mustChangePassword });
  const can = (point: string) => !!q.data?.permissions.includes(point);
  const has = (role: string) => !!q.data?.roles.includes(role);
  return { ...q, project: q.data, can, has };
}
