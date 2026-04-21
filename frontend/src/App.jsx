import { BrowserRouter, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import Accounts from "./pages/Accounts";
import Campaigns from "./pages/Campaigns";
import Contacts from "./pages/Contacts";
import Conversations from "./pages/Conversations";
import Prompts from "./pages/Prompts";
import Settings from "./pages/Settings";
import { useWS, useWsStatus } from "./ws";

const NAV = [
  { to: "/", label: "Inbox", icon: "💬", end: true, eyebrow: "Conversation Ops", blurb: "Monitor live replies, hot leads, and manual interventions." },
  { to: "/accounts", label: "Accounts", icon: "👤", eyebrow: "Runtime", blurb: "Track Telegram account health, sessions, proxies, and campaign readiness." },
  { to: "/campaigns", label: "Campaigns", icon: "📢", eyebrow: "Execution", blurb: "Launch conservative outreach waves with strict pacing and reply stops." },
  { to: "/contacts", label: "Contacts", icon: "👥", eyebrow: "Audience", blurb: "Keep imported prospect batches searchable, editable, and campaign-ready." },
  { to: "/prompts", label: "Prompts", icon: "🧠", eyebrow: "AI Layer", blurb: "Store reusable prompt packs for account- and campaign-level agents." },
  { to: "/settings", label: "Settings", icon: "⚙️", eyebrow: "Control Plane", blurb: "Configure provider credentials, default prompts, and auto-reply behavior." },
];

const WS_STATE = {
  connected: { label: "Live sync online", cls: "border-emerald-400/20 bg-emerald-400/10 text-emerald-200" },
  connecting: { label: "Connecting live sync", cls: "border-sky-400/20 bg-sky-400/10 text-sky-200" },
  reconnecting: { label: "Reconnecting", cls: "border-amber-400/20 bg-amber-400/10 text-amber-200" },
  error: { label: "Live sync interrupted", cls: "border-rose-400/20 bg-rose-400/10 text-rose-200" },
};

function ErrorToast() {
  const [errors, setErrors] = useState([]);

  useEffect(() => {
    const handler = (e) => {
      const id = Date.now();
      const { message, url, status } = e.detail;
      setErrors((prev) => [...prev, { id, message, url, status }]);
      setTimeout(() => setErrors((prev) => prev.filter((x) => x.id !== id)), 10000);
    };
    window.addEventListener("api-error", handler);
    return () => window.removeEventListener("api-error", handler);
  }, []);

  if (errors.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex w-full max-w-sm flex-col gap-2 px-4 sm:px-0">
      {errors.map((err) => (
        <div key={err.id} className="overflow-hidden rounded-2xl border border-rose-400/25 bg-zinc-950/95 shadow-[0_24px_60px_rgba(0,0,0,0.4)] backdrop-blur-xl">
          <div className="flex items-center gap-2 border-b border-rose-400/15 bg-rose-400/10 px-4 py-3">
            <span className="text-xs font-semibold uppercase tracking-[0.18em] text-rose-200">API error {err.status && `· ${err.status}`}</span>
            {err.url ? <span className="ml-auto truncate text-[11px] font-mono text-zinc-500">{err.url}</span> : null}
            <button
              onClick={() => setErrors((prev) => prev.filter((x) => x.id !== err.id))}
              className="ml-1 shrink-0 text-base leading-none text-zinc-500 transition-colors hover:text-zinc-100"
            >
              ×
            </button>
          </div>
          <div className="flex items-start gap-3 px-4 py-3.5">
            <p className="flex-1 break-all text-sm text-zinc-100">{err.message}</p>
            <button
              onClick={() => navigator.clipboard.writeText(err.message)}
              title="Копировать"
              className="shrink-0 rounded-lg border border-white/10 bg-white/4 px-2 py-1 text-[11px] uppercase tracking-[0.16em] text-zinc-300 transition-colors hover:bg-white/8"
            >
              Copy
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function isActivePath(pathname, item) {
  if (item.end) return pathname === item.to;
  return pathname === item.to || pathname.startsWith(`${item.to}/`);
}

function Sidebar({ pathname, onNavigate, mobile }) {
  return (
    <aside className="flex h-full flex-col px-4 py-5">
      <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#3b82f6,#0ea5e9)] text-sm font-semibold text-white shadow-[0_14px_35px_rgba(37,99,235,0.35)]">
              TG
            </div>
            <div>
              <div className="text-base font-semibold tracking-tight text-white">Outreach</div>
              <div className="text-xs uppercase tracking-[0.22em] text-zinc-500">Operator workspace</div>
            </div>
          </div>
          {mobile ? (
            <button
              onClick={onNavigate}
              className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/4 text-zinc-300 lg:hidden"
            >
              ×
            </button>
          ) : null}
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 text-[11px] uppercase tracking-[0.18em] text-zinc-500">
          <div className="rounded-2xl border border-white/8 bg-black/20 px-3 py-2">
            <div>Mode</div>
            <div className="mt-1 text-sm tracking-normal text-zinc-200">Local</div>
          </div>
          <div className="rounded-2xl border border-white/8 bg-black/20 px-3 py-2">
            <div>Scope</div>
            <div className="mt-1 text-sm tracking-normal text-zinc-200">TG ops</div>
          </div>
        </div>
      </div>

      <div className="mt-6 text-[11px] uppercase tracking-[0.22em] text-zinc-600">Workspace</div>
      <nav className="mt-3 space-y-1.5">
        {NAV.map((item) => {
          const active = isActivePath(pathname, item);
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={onNavigate}
              className={`group flex items-center gap-3 rounded-2xl px-3.5 py-3 transition-all ${
                active
                  ? "border border-white/12 bg-white/[0.06] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
                  : "border border-transparent text-zinc-400 hover:border-white/6 hover:bg-white/[0.03] hover:text-zinc-100"
              }`}
            >
              <div className={`flex h-10 w-10 items-center justify-center rounded-2xl text-lg transition-colors ${
                active ? "bg-sky-400/12 text-sky-200" : "bg-white/[0.04] text-zinc-400 group-hover:text-zinc-100"
              }`}>
                {item.icon}
              </div>
              <div className="min-w-0">
                <div className="text-sm font-medium">{item.label}</div>
                <div className="truncate text-xs text-zinc-500">{item.eyebrow}</div>
              </div>
            </NavLink>
          );
        })}
      </nav>

      <div className="mt-auto rounded-[24px] border border-white/10 bg-white/[0.03] px-4 py-4">
        <div className="text-[11px] uppercase tracking-[0.22em] text-zinc-600">Build</div>
        <div className="mt-2 text-sm text-zinc-300">v1.0 local runtime</div>
        <p className="mt-2 text-xs leading-5 text-zinc-500">Built for conservative Telegram outreach with live inbox monitoring, account health, and controlled warm-up.</p>
      </div>
    </aside>
  );
}

function WorkspaceFrame() {
  useWS();
  const pathname = useLocation().pathname;
  const wsStatus = useWsStatus();
  const [mobileOpen, setMobileOpen] = useState(false);
  const current = useMemo(() => NAV.find((item) => isActivePath(pathname, item)) || NAV[0], [pathname]);
  const liveMeta = WS_STATE[wsStatus] || WS_STATE.connecting;

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#07080d] text-zinc-100">
      <div className="pointer-events-none absolute inset-0 opacity-80">
        <div className="absolute -left-24 top-0 h-[420px] w-[420px] rounded-full bg-sky-500/12 blur-[120px]" />
        <div className="absolute right-[-120px] top-[12%] h-[460px] w-[460px] rounded-full bg-fuchsia-500/10 blur-[140px]" />
        <div className="absolute bottom-[-180px] left-[28%] h-[420px] w-[560px] rounded-full bg-cyan-500/8 blur-[140px]" />
      </div>

      <div className="relative flex min-h-screen">
        <div className="hidden w-[300px] shrink-0 border-r border-white/8 bg-black/20 backdrop-blur-xl lg:block">
          <Sidebar pathname={pathname} onNavigate={() => {}} />
        </div>

        {mobileOpen ? (
          <>
            <div className="fixed inset-0 z-40 bg-black/65 backdrop-blur-sm lg:hidden" onClick={() => setMobileOpen(false)} />
            <div className="fixed inset-y-0 left-0 z-50 w-[300px] border-r border-white/8 bg-[#090a11]/95 backdrop-blur-xl lg:hidden">
              <Sidebar pathname={pathname} onNavigate={() => setMobileOpen(false)} mobile />
            </div>
          </>
        ) : null}

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 border-b border-white/8 bg-[#07080d]/85 backdrop-blur-xl">
            <div className="mx-auto flex w-full max-w-[1600px] items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
              <div className="flex min-w-0 items-center gap-3">
                <button
                  onClick={() => setMobileOpen(true)}
                  className="inline-flex h-11 w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04] text-zinc-200 lg:hidden"
                >
                  ☰
                </button>
                <div className="min-w-0">
                  <div className="text-[11px] uppercase tracking-[0.24em] text-zinc-500">{current.eyebrow}</div>
                  <div className="truncate text-lg font-semibold tracking-tight text-white sm:text-xl">{current.label}</div>
                </div>
              </div>

              <div className="hidden items-center gap-2 lg:flex">
                <div className={`rounded-full border px-3 py-1.5 text-xs font-medium ${liveMeta.cls}`}>{liveMeta.label}</div>
                <div className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-300">
                  Safe pacing enabled
                </div>
              </div>
            </div>
          </header>

          <main className="flex-1">
            <div className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6 lg:px-8 lg:py-8">
              <Routes>
                <Route path="/" element={<Conversations />} />
                <Route path="/accounts" element={<Accounts />} />
                <Route path="/campaigns" element={<Campaigns />} />
                <Route path="/contacts" element={<Contacts />} />
                <Route path="/prompts" element={<Prompts />} />
                <Route path="/settings" element={<Settings />} />
              </Routes>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <WorkspaceFrame />
      <ErrorToast />
    </BrowserRouter>
  );
}
