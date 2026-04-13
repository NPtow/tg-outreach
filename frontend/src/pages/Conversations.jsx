import { useEffect, useRef, useState } from "react";
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
  const [campaigns, setCampaigns] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [filters, setFilters] = useState({
    account_id: "", status: "", search: "",
    campaign_id: "", unread_only: false, is_hot: false,
  });
  const prevUnread = useRef(0);

  const load = () =>
    api.getConversations({
      account_id: filters.account_id || undefined,
      status: filters.status || undefined,
      search: filters.search || undefined,
      campaign_id: filters.campaign_id || undefined,
      unread_only: filters.unread_only || undefined,
      is_hot: filters.is_hot || undefined,
    }).then(setConvs);

  useEffect(() => { api.getAccounts().then(setAccounts); api.getCampaigns().then(setCampaigns); }, []);
  useEffect(() => { load(); }, [filters]);
  useWsEvent((e) => { if (e.event === "new_message" || e.event === "hot_lead") load(); });

  const setFilter = (k, v) => setFilters(f => ({ ...f, [k]: v }));
  const selectedConv = convs.find(c => c.id === selectedId);

  const totalUnread = convs.reduce((s, c) => s + (c.unread_count || 0), 0);
  const hotCount = convs.filter(c => c.is_hot).length;

  const handleSelect = async (id) => {
    setSelectedId(prev => prev === id ? null : id);
    const conv = convs.find(c => c.id === id);
    if (conv?.unread_count > 0) {
      await api.markRead(id);
      setConvs(prev => prev.map(c => c.id === id ? { ...c, unread_count: 0 } : c));
    }
  };

  return (
    <div className="flex h-screen">
      {/* List panel */}
      <div className={`flex flex-col ${selectedId ? "w-[420px] shrink-0" : "flex-1"} border-r border-zinc-800`}>
        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-800">
          <div className="flex items-center justify-between mb-3">
            <h1 className="text-base font-semibold text-zinc-100">Inbox</h1>
            <div className="flex items-center gap-2">
              {hotCount > 0 && (
                <button
                  onClick={() => setFilter("is_hot", !filters.is_hot)}
                  className={`text-xs px-2 py-1 rounded-full font-medium transition-colors ${filters.is_hot ? "bg-orange-500 text-white" : "bg-orange-500/15 text-orange-400 hover:bg-orange-500/25"}`}
                >
                  🔥 {hotCount}
                </button>
              )}
              {totalUnread > 0 && (
                <span className="text-xs bg-blue-600 text-white px-2 py-0.5 rounded-full font-medium">
                  {totalUnread}
                </span>
              )}
            </div>
          </div>
          {/* Search */}
          <div className="relative mb-2">
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-500 text-sm">🔍</span>
            <input
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg pl-8 pr-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-blue-500 transition-colors"
              placeholder="Поиск..."
              value={filters.search}
              onChange={e => setFilter("search", e.target.value)}
            />
          </div>
          {/* Filter row */}
          <div className="flex gap-2">
            <select
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-xs text-zinc-300 focus:outline-none focus:border-blue-500"
              value={filters.status}
              onChange={e => setFilter("status", e.target.value)}
            >
              <option value="">Все статусы</option>
              <option value="active">Active</option>
              <option value="paused">Paused</option>
              <option value="done">Done</option>
            </select>
            <select
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-xs text-zinc-300 focus:outline-none focus:border-blue-500"
              value={filters.campaign_id}
              onChange={e => setFilter("campaign_id", e.target.value)}
            >
              <option value="">Все кампании</option>
              {campaigns.map(c => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          {/* Toggle row */}
          <div className="flex gap-3 mt-2">
            <label className="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer select-none">
              <input type="checkbox" className="accent-blue-500" checked={filters.unread_only}
                onChange={e => setFilter("unread_only", e.target.checked)} />
              Непрочитанные
            </label>
            <label className="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer select-none">
              <input type="checkbox" className="accent-orange-500" checked={filters.is_hot}
                onChange={e => setFilter("is_hot", e.target.checked)} />
              🔥 Горячие
            </label>
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
                onClick={() => handleSelect(c.id)}
                className={`flex items-start gap-3 px-4 py-3.5 cursor-pointer transition-colors ${
                  isSelected ? "bg-blue-600/10 border-l-2 border-blue-500" : "hover:bg-zinc-800/40 border-l-2 border-transparent"
                }`}
              >
                <div className="relative">
                  <Avatar name={name} />
                  {c.is_hot && (
                    <span className="absolute -top-1 -right-1 text-[10px]">🔥</span>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2 mb-0.5">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className={`text-sm font-medium truncate ${c.unread_count > 0 ? "text-white" : "text-zinc-100"}`}>
                        {name}
                      </span>
                      {c.source_campaign_name && (
                        <span className="text-[10px] bg-blue-500/15 text-blue-400 px-1.5 py-0.5 rounded-full shrink-0 truncate max-w-[80px]">
                          {c.source_campaign_name}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {c.unread_count > 0 && (
                        <span className="w-4 h-4 bg-blue-500 rounded-full flex items-center justify-center text-[10px] text-white font-bold">
                          {c.unread_count > 9 ? "9+" : c.unread_count}
                        </span>
                      )}
                      <span className="text-[11px] text-zinc-500">{fmtDate(c.last_message_at)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <p className={`text-xs truncate flex-1 ${c.unread_count > 0 ? "text-zinc-300" : "text-zinc-400"}`}>
                      {c.last_message || "—"}
                    </p>
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
