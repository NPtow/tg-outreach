import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Accounts from "./pages/Accounts";
import Campaigns from "./pages/Campaigns";
import Conversations from "./pages/Conversations";
import Prompts from "./pages/Prompts";
import Settings from "./pages/Settings";
import { useWS } from "./ws";

const NAV = [
  { to: "/", label: "Inbox", icon: "💬", end: true },
  { to: "/accounts", label: "Accounts", icon: "👤" },
  { to: "/campaigns", label: "Campaigns", icon: "📢" },
  { to: "/prompts", label: "Prompts", icon: "🧠" },
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
            <Route path="/prompts" element={<Prompts />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
