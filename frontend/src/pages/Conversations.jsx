import { useEffect, useState } from "react";
import { api } from "../api";
import ChatView from "../components/ChatView";
import { EmptyState, PageHeader, Surface } from "../components/workspace";
import { useWsEvent } from "../ws";

const STATUS = {
  active: { cls: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/20", label: "Active" },
  paused: { cls: "bg-amber-500/15 text-amber-300 ring-amber-500/20", label: "Paused" },
  done: { cls: "bg-zinc-700/50 text-zinc-300 ring-zinc-600/20", label: "Done" },
};

function Avatar({ name }) {
  const initials = name ? name.split(" ").map((word) => word[0]).join("").slice(0, 2).toUpperCase() : "?";
  const colors = ["bg-sky-600", "bg-violet-600", "bg-pink-600", "bg-emerald-600", "bg-amber-600", "bg-cyan-600"];
  const color = colors[name?.charCodeAt(0) % colors.length] || "bg-zinc-600";
  return (
    <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl ${color} text-xs font-semibold text-white shadow-[0_12px_30px_rgba(0,0,0,0.28)]`}>
      {initials}
    </div>
  );
}

function fmtDate(value) {
  if (!value) return "";
  const date = new Date(value);
  const diffHours = (Date.now() - date) / 3600000;
  if (diffHours < 24) return date.toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" });
  return date.toLocaleDateString("ru", { day: "2-digit", month: "short" });
}

function inputCls() {
  return "w-full rounded-2xl border border-white/10 bg-white/[0.04] px-3.5 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 outline-none transition focus:border-sky-400/40 focus:bg-white/[0.05]";
}

export default function Conversations() {
  const [conversations, setConversations] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [filters, setFilters] = useState({
    account_id: "",
    status: "",
    search: "",
    campaign_id: "",
    unread_only: false,
    is_hot: false,
  });

  const load = () =>
    api.getConversations({
      account_id: filters.account_id || undefined,
      status: filters.status || undefined,
      search: filters.search || undefined,
      campaign_id: filters.campaign_id || undefined,
      unread_only: filters.unread_only || undefined,
      is_hot: filters.is_hot || undefined,
    }).then(setConversations);

  useEffect(() => {
    api.getAccounts().then(setAccounts);
    api.getCampaigns().then(setCampaigns);
  }, []);

  useEffect(() => {
    load();
  }, [filters]);

  useWsEvent((event) => {
    if (event.event === "new_message" || event.event === "hot_lead") load();
  });

  const setFilter = (key, value) => setFilters((prev) => ({ ...prev, [key]: value }));
  const selectedConversation = conversations.find((item) => item.id === selectedId) || null;
  const totalUnread = conversations.reduce((sum, item) => sum + (item.unread_count || 0), 0);
  const hotCount = conversations.filter((item) => item.is_hot).length;
  const activeFilterCount = ["account_id", "status", "campaign_id"].filter((key) => filters[key]).length +
    (filters.unread_only ? 1 : 0) +
    (filters.is_hot ? 1 : 0) +
    (filters.search ? 1 : 0);

  const handleSelect = async (id) => {
    setSelectedId((current) => (current === id ? null : id));
    const conversation = conversations.find((item) => item.id === id);
    if (conversation?.unread_count > 0) {
      await api.markRead(id);
      setConversations((prev) => prev.map((item) => (item.id === id ? { ...item, unread_count: 0 } : item)));
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Conversation Ops"
        title="Inbox"
        description="Окно операторов для входящих ответов, hot leads и ручной работы по активным диалогам."
        stats={[
          { label: "Visible threads", value: conversations.length, tone: "neutral", caption: activeFilterCount ? `${activeFilterCount} active filters` : "All conversations" },
          { label: "Unread", value: totalUnread, tone: totalUnread ? "blue" : "neutral", caption: totalUnread ? "Need attention" : "Inbox is clear" },
          { label: "Hot leads", value: hotCount, tone: hotCount ? "amber" : "neutral", caption: hotCount ? "Prioritize follow-up" : "No hot threads" },
        ]}
      />

      <div className="grid gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
        <Surface className="overflow-hidden">
          <div className="border-b border-white/8 px-5 py-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-white">Thread queue</h2>
                <p className="mt-1 text-sm text-zinc-400">Scan new replies, filter by account or campaign, and jump into the hottest conversations fast.</p>
              </div>
              {totalUnread ? (
                <div className="rounded-full border border-sky-400/20 bg-sky-400/10 px-3 py-1 text-xs font-semibold text-sky-200">
                  {totalUnread} unread
                </div>
              ) : null}
            </div>

            <div className="mt-5 space-y-3">
              <div className="relative">
                <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500">⌕</span>
                <input
                  className={`${inputCls()} pl-10`}
                  placeholder="Поиск по имени, username или последнему сообщению"
                  value={filters.search}
                  onChange={(event) => setFilter("search", event.target.value)}
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <select className={inputCls()} value={filters.account_id} onChange={(event) => setFilter("account_id", event.target.value)}>
                  <option value="">Все аккаунты</option>
                  {accounts.map((account) => (
                    <option key={account.id} value={account.id}>{account.name}</option>
                  ))}
                </select>
                <select className={inputCls()} value={filters.campaign_id} onChange={(event) => setFilter("campaign_id", event.target.value)}>
                  <option value="">Все кампании</option>
                  {campaigns.map((campaign) => (
                    <option key={campaign.id} value={campaign.id}>{campaign.name}</option>
                  ))}
                </select>
                <select className={inputCls()} value={filters.status} onChange={(event) => setFilter("status", event.target.value)}>
                  <option value="">Все статусы</option>
                  <option value="active">Active</option>
                  <option value="paused">Paused</option>
                  <option value="done">Done</option>
                </select>
                <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-xs font-medium text-zinc-400">
                  <label className="flex items-center gap-2">
                    <input type="checkbox" className="accent-sky-500" checked={filters.unread_only} onChange={(event) => setFilter("unread_only", event.target.checked)} />
                    Unread only
                  </label>
                  <div className="h-4 w-px bg-white/8" />
                  <label className="flex items-center gap-2">
                    <input type="checkbox" className="accent-amber-500" checked={filters.is_hot} onChange={(event) => setFilter("is_hot", event.target.checked)} />
                    Hot only
                  </label>
                </div>
              </div>
            </div>
          </div>

          <div className="border-b border-white/8 px-5 py-3 text-xs uppercase tracking-[0.22em] text-zinc-500">
            {conversations.length} threads
          </div>

          <div className="max-h-[70vh] overflow-y-auto">
            {conversations.length === 0 ? (
              <EmptyState
                compact
                icon="💬"
                title="Inbox is quiet"
                description="Новые диалоги появятся здесь после запуска кампаний или когда кто-то ответит на уже активный outreach."
                className="m-5"
              />
            ) : (
              <div className="divide-y divide-white/6">
                {conversations.map((conversation) => {
                  const name = [conversation.tg_first_name, conversation.tg_last_name].filter(Boolean).join(" ")
                    || (conversation.tg_username ? `@${conversation.tg_username}` : conversation.tg_user_id);
                  const selected = conversation.id === selectedId;
                  const status = STATUS[conversation.status] || STATUS.active;
                  return (
                    <button
                      key={conversation.id}
                      onClick={() => handleSelect(conversation.id)}
                      className={`flex w-full items-start gap-3 px-4 py-4 text-left transition ${
                        selected
                          ? "bg-sky-400/[0.08]"
                          : "hover:bg-white/[0.03]"
                      }`}
                    >
                      <div className="relative">
                        <Avatar name={name} />
                        {conversation.is_hot ? <span className="absolute -right-1 -top-1 text-[11px]">🔥</span> : null}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className={`truncate text-sm font-semibold ${conversation.unread_count ? "text-white" : "text-zinc-200"}`}>{name}</span>
                              {conversation.source_campaign_name ? (
                                <span className="max-w-[110px] truncate rounded-full border border-sky-400/15 bg-sky-400/10 px-2 py-0.5 text-[10px] font-medium text-sky-200">
                                  {conversation.source_campaign_name}
                                </span>
                              ) : null}
                            </div>
                            <p className={`mt-1 truncate text-xs ${conversation.unread_count ? "text-zinc-300" : "text-zinc-500"}`}>
                              {conversation.last_message || "—"}
                            </p>
                          </div>
                          <div className="shrink-0 text-right">
                            <div className="text-[11px] text-zinc-500">{fmtDate(conversation.last_message_at)}</div>
                            {conversation.unread_count ? (
                              <div className="mt-2 inline-flex min-w-5 items-center justify-center rounded-full bg-sky-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                                {conversation.unread_count > 9 ? "9+" : conversation.unread_count}
                              </div>
                            ) : null}
                          </div>
                        </div>
                        <div className="mt-3 flex items-center justify-between gap-3">
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 ${status.cls}`}>
                            {status.label}
                          </span>
                          {conversation.tg_username ? <span className="truncate text-[11px] text-zinc-500">@{conversation.tg_username}</span> : null}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </Surface>

        <Surface className="min-h-[70vh] overflow-hidden">
          {selectedConversation ? (
            <ChatView convId={selectedConversation.id} onClose={() => setSelectedId(null)} onStatusChange={load} />
          ) : (
            <EmptyState
              icon="✉️"
              title="Open a conversation"
              description="Выберите тред слева, чтобы прочитать историю, сменить статус и написать вручную, если нужен human handoff."
              compact
              className="m-5 min-h-[calc(70vh-2.5rem)]"
            />
          )}
        </Surface>
      </div>
    </div>
  );
}
