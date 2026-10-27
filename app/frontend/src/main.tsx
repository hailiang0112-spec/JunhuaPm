import { StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider, useLocation } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/shell.css";
import { SessionProvider, useSession } from "./session";
import { Loading, ToastProvider } from "./ui";
import { ROUTES } from "./routes";
import { sessionHint } from "./api";

const PUBLIC = ["/login", "/invite/"];

function Guard({ children }: { children: React.ReactNode }) {
  const { me, loading } = useSession();
  const loc = useLocation();
  if (PUBLIC.some((p) => loc.pathname.startsWith(p))) return <>{children}</>;
  if (loading) return <Loading />;
  if (!me) return <Navigate to={sessionHint.has() ? "/login?expired=1" : "/login"} replace />;
  if (me.mustChangePassword && loc.pathname !== "/me") return <Navigate to="/me" replace />;
  return <>{children}</>;
}

const router = createBrowserRouter(
  ROUTES.map(({ path, Component }) => ({
    path,
    element: (
      <Guard>
        <Suspense fallback={<Loading />}><Component /></Suspense>
      </Guard>
    ),
  })).concat([{ path: "*", element: <Navigate to="/" replace /> }]),
);

const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <SessionProvider>
          <RouterProvider router={router} />
        </SessionProvider>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
