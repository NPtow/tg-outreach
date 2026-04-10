import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useWsEvent } from "../ws";

function Bubble({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-start" : "justify-end"} mb-3`}>
      <div className={`max-w-[75%] px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed ${
        isUser
          ? "bg-zinc-800 text-zinc-100 rounded-tl-sm"
          : "bg-blue-600 text-white rounded-tr-sm"
      }`}>
        <p className="whitespace-pre-wrap">{msg.text}</p>
        <p className={`text-[10px] mt-1 ${isUser ? "text-zinc-500" : "text-blue-200"}`}>
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

  if (!data) return (
    <div className="flex items-center justify-center h-full text-zinc-500 text-sm">Загрузка...</div>
  );

  const { conversation: conv, messages } = data;
  const name = [conv.tg_first_name, conv.tg_last_name].filter(Boolean).join(" ") || conv.tg_username || conv.tg_user_id;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-zinc-800 bg-zinc-900/50">
        <div>
          <p className="text-sm font-semibold text-zinc-100">{name}</p>
          {conv.tg_username && <p className="text-xs text-zinc-500">@{conv.tg_username}</p>}
        </div>
        <div className="flex items-center gap-1.5">
          {STATUS_BTNS.map(b => (
            <button key={b.key} onClick={() => handleStatus(b.key)}
              className={`text-xs px-2.5 py-1 rounded-lg transition-colors font-medium ${
                conv.status === b.key ? b.active : b.idle
              }`}>
              {b.label}
            </button>
          ))}
          <button onClick={onClose} className="ml-2 w-7 h-7 flex items-center justify-center rounded-lg text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 transition-colors text-lg">
            ×
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {messages.length === 0 && (
          <div className="text-center text-zinc-600 text-sm mt-8">Нет сообщений</div>
        )}
        {messages.map(m => <Bubble key={m.id} msg={m} />)}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3.5 border-t border-zinc-800 bg-zinc-900/30">
        <div className="flex gap-2 items-end">
          <textarea
            rows={1}
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded-xl px-3.5 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-blue-500 transition-colors resize-none"
            placeholder="Написать вручную..."
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
          />
          <button
            onClick={handleSend}
            disabled={sending || !text.trim()}
            className="shrink-0 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white px-4 py-2.5 rounded-xl text-sm font-medium transition-colors"
          >
            ↑
          </button>
        </div>
      </div>
    </div>
  );
}
