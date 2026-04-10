import { useEffect, useState } from "react";
import { api } from "../api";
import ChatView from "../components/ChatView";
import { useWsEvent } from "../ws";

const STATUS_COLORS = {
  active: "bg-green-900 text-green-300",
  paused: "bg-yellow-900 text-yellow-300",
  done: "bg-gray-700 text-gray-400",
};

function fmtDate(dt) {
  if (!dt) return "";
  const d = new Date(dt);
  const now = new Date();
  const diffH = (now - d) / 3600000;
  if (diffH < 24) return d.toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString("ru", { day: "2-digit", month: "2-digit" });
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

  useEffect(() => {
    api.getAccounts().then(setAccounts);
  }, []);

  useEffect(() => { load(); }, [filters]);

  useWsEvent((event) => {
    if (event.event === "new_message") load();
  });

  const setFilter = (key, val) => setFilters((f) => ({ ...f, [key]: val }));

  const selectedConv = convs.find((c) => c.id === selectedId);

  return (
    <div className="flex h-[calc(100vh-53px)]">
      {/* Left: table */}
      <div className={`flex flex-col ${selectedId ? "w-1/2" : "w-full"} overflow-hidden`}>
        {/* Filters */}
        <div className="flex items-center gap-3 px-6 py-3 border-b border-gray-700 bg-gray-900 flex-wrap">
          <input
            className="bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm w-48"
            placeholder="Поиск по имени..."
            value={filters.search}
            onChange={(e) => setFilter("search", e.target.value)}
          />
          <select
            className="bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm"
            value={filters.account_id}
            onChange={(e) => setFilter("account_id", e.target.value)}
          >
            <option value="">Все аккаунты</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
          <select
            className="bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm"
            value={filters.status}
            onChange={(e) => setFilter("status", e.target.value)}
          >
            <option value="">Все статусы</option>
            <option value="active">Active</option>
            <option value="paused">Paused</option>
            <option value="done">Done</option>
          </select>
          <span className="text-xs text-gray-500 ml-auto">{convs.length} conversations</span>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-gray-900 border-b border-gray-700">
              <tr>
                <th className="text-left px-4 py-2 text-gray-400 font-medium">#</th>
                <th className="text-left px-4 py-2 text-gray-400 font-medium">Контакт</th>
                <th className="text-left px-4 py-2 text-gray-400 font-medium">Аккаунт</th>
                <th className="text-left px-4 py-2 text-gray-400 font-medium">Статус</th>
                <th className="text-left px-4 py-2 text-gray-400 font-medium">Последнее</th>
                <th className="text-left px-4 py-2 text-gray-400 font-medium">Дата</th>
              </tr>
            </thead>
            <tbody>
              {convs.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-gray-500">
                    Нет диалогов
                  </td>
                </tr>
              )}
              {convs.map((c) => {
                const name =
                  [c.tg_first_name, c.tg_last_name].filter(Boolean).join(" ") ||
                  (c.tg_username ? "@" + c.tg_username : c.tg_user_id);
                const isSelected = c.id === selectedId;
                return (
                  <tr
                    key={c.id}
                    onClick={() => setSelectedId(isSelected ? null : c.id)}
                    className={`border-b border-gray-800 cursor-pointer transition-colors ${
                      isSelected ? "bg-blue-900/30" : "hover:bg-gray-800"
                    }`}
                  >
                    <td className="px-4 py-3 text-gray-500">{c.id}</td>
                    <td className="px-4 py-3 font-medium">{name}</td>
                    <td className="px-4 py-3 text-gray-400 text-xs">{c.account_name}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[c.status]}`}>
                        {c.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-300 max-w-[200px] truncate">
                      {c.last_message || "—"}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                      {fmtDate(c.last_message_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Right: chat */}
      {selectedId && (
        <div className="w-1/2 flex flex-col">
          <ChatView
            convId={selectedId}
            onClose={() => setSelectedId(null)}
            onStatusChange={load}
          />
        </div>
      )}
    </div>
  );
}
