import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import { useEffect, useState } from "react";
import Accounts from "./pages/Accounts";
import Campaigns from "./pages/Campaigns";
import Contacts from "./pages/Contacts";
import Conversations from "./pages/Conversations";
import Prompts from "./pages/Prompts";
import Settings from "./pages/Settings";
import Warming from "./pages/Warming";
import { useWS } from "./ws";

function ErrorToast() {
  const [errors, setErrors] = useState([]);

  useEffect(() => {
    const handler = (e) => {
      const id = Date.now();
      const { message, url, status } = e.detail;
      setErrors(prev => [...prev, { id, message, url, status }]);
      setTimeout(() => setErrors(prev => prev.filter(x => x.id !== id)), 10000);
    };
    window.addEventListener("api-error", handler);
    return () => window.removeEventListener("api-error", handler);
  }, []);

  if (errors.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm w-full">
      {errors.map(err => (
        <div key={err.id} className="bg-zinc-900 border border-red-500/50 rounded-xl shadow-2xl overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 bg-red-500/10 border-b border-red-500/20">
            <span className="text-red-400 text-xs font-semibold">Ошибка {err.status && `· ${err.status}`}</span>
            {err.url && <span className="text-zinc-600 text-xs font-mono ml-auto truncate">{err.url}</span>}
            <button
              onClick={() => setErrors(prev => prev.filter(x => x.id !== err.id))}
              className="text-zinc-500 hover:text-zinc-200 text-base leading-none shrink-0 ml-1">×</button>
          </div>
          <div className="px-3 py-2.5 flex items-start gap-2">
            <p className="text-sm text-zinc-100 flex-1 break-all select-all">{err.message}</p>
            <button
              onClick={() => navigator.clipboard.writeText(err.message)}
              title="Копировать"
              className="text-zinc-500 hover:text-zinc-200 text-xs shrink-0 px-1.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 transition-colors">
              copy
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

const NAV = [
  { to: "/", label: "Inbox", icon: "💬", end: true },
  { to: "/accounts", label: "Accounts", icon: "👤" },
  { to: "/campaigns", label: "Campaigns", icon: "📢" },
  { to: "/contacts", label: "Contacts", icon: "👥" },
  { to: "/prompts", label: "Prompts", icon: "🧠" },
  { to: "/warming", label: "Warming", icon: "🔥" },
  { to: "/settings", label: "Settings", icon: "⚙️" },
];

function Sidebar() {
  return (
    <aside className="w-56 shrink-0 flex flex-col bg-zinc-900 border-r border-zinc-800 h-screen sticky top-0">
      <div className="px-5 py-5 border-b border-zinc-800">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-blue-500 flex items-center justify-center text-white text-xs font-bold">TG</div>
          <span className="font-semibold text-zinc-100 text-sm">Outreach</span>
        </div>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV.map(({ to, label, icon, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all ${
              isActive
                ? "bg-zinc-800 text-zinc-100 font-medium"
                : "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/50"
            }`
          }>
            <span className="text-base">{icon}</span>
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="px-4 py-4 border-t border-zinc-800">
        <p className="text-[11px] text-zinc-600">v1.0 · Local</p>
      </div>
    </aside>
  );
}

export default function App() {
  useWS();
  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-zinc-950 text-zinc-100">
        <Sidebar />
        <main className="flex-1 min-w-0 overflow-auto">
          <Routes>
            <Route path="/" element={<Conversations />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/campaigns" element={<Campaigns />} />
            <Route path="/contacts" element={<Contacts />} />
            <Route path="/prompts" element={<Prompts />} />
            <Route path="/warming" element={<Warming />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
      <ErrorToast />
    </BrowserRouter>
  );
}
