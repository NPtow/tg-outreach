import { useEffect, useState } from "react";
import { api } from "../api";
import ChatView from "../components/ChatView";
import { useWsEvent } from "../ws";

const STATUS = {
  active:  { cls: "bg-emerald-500/15 text-emerald-400 ring-emerald-500/20", label: "Active" },
  paused:  { cls: "bg-amber-500/15 text-amber-400 ring-amber-500/20",       label: "Paused" },
  done:    { cls: "bg-zinc-700/50 text-zinc-400 ring-zinc-600/20",           label: "Done" },
};

function Avatar({ name }) {
  const initials = name ? name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase() : "?";
  const colors = ["bg-blue-600","bg-violet-600","bg-pink-600","bg-emerald-600","bg-amber-600","bg-cyan-600"];
  const color = colors[name?.charCodeAt(0) % colors.length] || "bg-zinc-600";
  return (
    <div className={`w-8 h-8 rounded-full ${color} flex items-center justify-center text-xs font-semibold text-white shrink-0`}>
      {initials}
    </div>
  );
}

function fmtDate(dt) {
  if (!dt) return "";
  const d = new Date(dt);
  const diffH = (Date.now() - d) / 3600000;
  if (diffH < 24) return d.toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString("ru", { day: "2-digit", month: "short" });
}

export default function Conversations() {
  const [convs, setConvs] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [filters, setFilters] = useState({ account_id: "", status: "", search: "" });

  const load = () =>
    api.getConversations({
      account_id: filters.account_id || undefined,
      status: filters.status || undefined,
      search: filters.search || undefined,
    }).then(setConvs);

  useEffect(() => { api.getAccounts().then(setAccounts); }, []);
  useEffect(() => { load(); }, [filters]);
  useWsEvent((e) => { if (e.event === "new_message") load(); });

  const setFilter = (k, v) => setFilters(f => ({ ...f, [k]: v }));
  const selectedConv = convs.find(c => c.id === selectedId);

  return (
    <div className="flex h-screen">
      {/* List panel */}
      <div className={`flex flex-col ${selectedId ? "w-[420px] shrink-0" : "flex-1"} border-r border-zinc-800`}>
        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-800">
          <h1 className="text-base font-semibold text-zinc-100 mb-3">Inbox</h1>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-500 text-sm">🔍</span>
              <input
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg pl-8 pr-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-blue-500 transition-colors"
                placeholder="Поиск..."
                value={filters.search}
                onChange={e => setFilter("search", e.target.value)}
              />
            </div>
            <select
              className="bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-sm text-zinc-300 focus:outline-none focus:border-blue-500"
              value={filters.status}
              onChange={e => setFilter("status", e.target.value)}
            >
              <option value="">Все</option>
              <option value="active">Active</option>
              <option value="paused">Paused</option>
              <option value="done">Done</option>
            </select>
          </div>
        </div>

        {/* Count */}
        <div className="px-5 py-2 border-b border-zinc-800/50">
          <span className="text-xs text-zinc-500">{convs.length} диалогов</span>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto divide-y divide-zinc-800/50">
          {convs.length === 0 && (
            <div className="flex flex-col items-center justify-center h-48 text-zinc-500">
              <span className="text-3xl mb-2">💬</span>
              <p className="text-sm">Нет диалогов</p>
            </div>
          )}
          {convs.map(c => {
            const name = [c.tg_first_name, c.tg_last_name].filter(Boolean).join(" ")
              || (c.tg_username ? "@" + c.tg_username : c.tg_user_id);
            const isSelected = c.id === selectedId;
            const st = STATUS[c.status] || STATUS.active;
            return (
              <div
                key={c.id}
                onClick={() => setSelectedId(isSelected ? null : c.id)}
                className={`flex items-start gap-3 px-4 py-3.5 cursor-pointer transition-colors ${
                  isSelected ? "bg-blue-600/10 border-l-2 border-blue-500" : "hover:bg-zinc-800/40 border-l-2 border-transparent"
                }`}
              >
                <Avatar name={name} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2 mb-0.5">
                    <span className="text-sm font-medium text-zinc-100 truncate">{name}</span>
                    <span className="text-[11px] text-zinc-500 shrink-0">{fmtDate(c.last_message_at)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <p className="text-xs text-zinc-400 truncate flex-1">{c.last_message || "—"}</p>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ring-1 shrink-0 ${st.cls}`}>
                      {st.label}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Chat panel */}
      {selectedId ? (
        <div className="flex-1 flex flex-col min-w-0">
          <ChatView convId={selectedId} onClose={() => setSelectedId(null)} onStatusChange={load} />
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-zinc-600">
          <div className="text-center">
            <div className="text-5xl mb-3">💬</div>
            <p className="text-sm">Выбери диалог</p>
          </div>
        </div>
      )}
    </div>
  );
}
