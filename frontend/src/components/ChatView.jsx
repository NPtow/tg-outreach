import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useWsEvent } from "../ws";

function Bubble({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-start" : "justify-end"} mb-3`}>
      <div className={`max-w-[78%] rounded-3xl px-4 py-3 text-sm leading-relaxed shadow-[0_12px_34px_rgba(0,0,0,0.18)] ${
        isUser
          ? "rounded-tl-md border border-white/8 bg-white/[0.05] text-zinc-100"
          : "rounded-tr-md bg-[linear-gradient(135deg,#2563eb,#0ea5e9)] text-white"
      }`}>
        <p className="whitespace-pre-wrap">{msg.text}</p>
        <p className={`mt-1.5 text-[10px] ${isUser ? "text-zinc-500" : "text-sky-100/80"}`}>
          {new Date(msg.created_at).toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" })}
        </p>
      </div>
    </div>
  );
}

const STATUS_BTNS = [
  { key: "active", label: "Active", active: "bg-emerald-600 text-white", idle: "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800" },
  { key: "paused", label: "Pause", active: "bg-amber-600 text-white", idle: "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800" },
  { key: "done",   label: "Done",  active: "bg-zinc-600 text-white",   idle: "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800" },
];

export default function ChatView({ convId, onClose, onStatusChange }) {
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [scheduling, setScheduling] = useState(false);
  const bottomRef = useRef(null);

  const load = () => api.getMessages(convId).then(setData);
  useEffect(() => { load(); }, [convId]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [data?.messages?.length]);
  useWsEvent(e => { if (e.event === "new_message" && e.conversation_id === convId) load(); });

  const handleSend = async () => {
    if (!text.trim()) return;
    setSending(true);
    try { await api.sendMessage(convId, text); setText(""); load(); }
    finally { setSending(false); }
  };

  const handleStatus = async (s) => { await api.updateStatus(convId, s); load(); onStatusChange?.(); };
  const handleScheduleMeeting = async () => {
    setScheduling(true);
    try {
      const result = await api.scheduleMeeting(convId);
      if (result?.reply_text) setText(result.reply_text);
    } finally {
      setScheduling(false);
    }
  };

  if (!data) return (
    <div className="flex items-center justify-center h-full text-zinc-500 text-sm">Загрузка...</div>
  );

  const { conversation: conv, messages } = data;
  const name = [conv.tg_first_name, conv.tg_last_name].filter(Boolean).join(" ") || conv.tg_username || conv.tg_user_id;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/8 bg-white/[0.03] px-5 py-4">
        <div className="min-w-0">
          <p className="truncate text-base font-semibold text-zinc-100">{name}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
            {conv.tg_username ? <span>@{conv.tg_username}</span> : null}
            {conv.source_campaign_name ? (
              <span className="rounded-full border border-sky-400/15 bg-sky-400/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-sky-200">
                {conv.source_campaign_name}
              </span>
            ) : null}
          </div>
        </div>
        <div className="ml-4 flex items-center gap-1.5">
          <button
            onClick={handleScheduleMeeting}
            disabled={scheduling}
            className="rounded-xl border border-sky-400/20 bg-sky-400/10 px-2.5 py-1.5 text-xs font-medium text-sky-200 transition-colors hover:bg-sky-400/15 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {scheduling ? "Booking..." : "Book meeting"}
          </button>
          {STATUS_BTNS.map(b => (
            <button key={b.key} onClick={() => handleStatus(b.key)}
              className={`rounded-xl px-2.5 py-1.5 text-xs font-medium transition-colors ${
                conv.status === b.key ? b.active : b.idle
              }`}>
              {b.label}
            </button>
          ))}
          <button onClick={onClose} className="ml-2 flex h-9 w-9 items-center justify-center rounded-xl text-lg text-zinc-500 transition-colors hover:bg-white/[0.06] hover:text-zinc-200">
            ×
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto bg-[radial-gradient(circle_at_top,rgba(56,189,248,0.08),transparent_30%),linear-gradient(180deg,rgba(12,12,18,0.88),rgba(8,8,12,0.94))] px-5 py-5">
        {messages.length === 0 && (
          <div className="text-center text-zinc-600 text-sm mt-8">Нет сообщений</div>
        )}
        {messages.map(m => <Bubble key={m.id} msg={m} />)}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-white/8 bg-white/[0.03] px-4 py-4">
        <div className="flex gap-2 items-end">
          <textarea
            rows={1}
            className="flex-1 resize-none rounded-2xl border border-white/10 bg-white/[0.05] px-4 py-3 text-sm text-zinc-100 placeholder-zinc-500 outline-none transition focus:border-sky-400/40 focus:bg-white/[0.06]"
            placeholder="Написать вручную..."
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
          />
          <button
            onClick={handleSend}
            disabled={sending || !text.trim()}
            className="shrink-0 rounded-2xl bg-[linear-gradient(135deg,#2563eb,#0ea5e9)] px-4 py-3 text-sm font-medium text-white transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-40"
          >
            ↑
          </button>
        </div>
      </div>
    </div>
  );
}
