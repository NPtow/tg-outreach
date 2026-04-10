import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useWsEvent } from "../ws";

const STATUS_COLORS = {
  active: "bg-green-900 text-green-300",
  paused: "bg-yellow-900 text-yellow-300",
  done: "bg-gray-700 text-gray-400",
};

function Message({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-start" : "justify-end"} mb-2`}>
      <div
        className={`max-w-[70%] px-3 py-2 rounded-lg text-sm ${
          isUser ? "bg-gray-700 text-gray-100" : "bg-blue-600 text-white"
        }`}
      >
        <p>{msg.text}</p>
        <p className={`text-xs mt-1 ${isUser ? "text-gray-400" : "text-blue-200"}`}>
          {new Date(msg.created_at).toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" })}
        </p>
      </div>
    </div>
  );
}

export default function ChatView({ convId, onClose, onStatusChange }) {
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef(null);

  const load = () => api.getMessages(convId).then(setData);

  useEffect(() => { load(); }, [convId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [data?.messages?.length]);

  useWsEvent((event) => {
    if (event.event === "new_message" && event.conversation_id === convId) {
      load();
    }
  });

  const handleSend = async () => {
    if (!text.trim()) return;
    setSending(true);
    try {
      await api.sendMessage(convId, text);
      setText("");
      load();
    } finally {
      setSending(false);
    }
  };

  const handleStatus = async (status) => {
    await api.updateStatus(convId, status);
    load();
    onStatusChange?.();
  };

  if (!data) return <div className="p-4 text-gray-400 text-sm">Загрузка...</div>;

  const { conversation: conv, messages } = data;
  const name = [conv.tg_first_name, conv.tg_last_name].filter(Boolean).join(" ") || conv.tg_username || conv.tg_user_id;

  return (
    <div className="flex flex-col h-full border-l border-gray-700">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 bg-gray-800">
        <div>
          <div className="font-medium text-sm">{name}</div>
          {conv.tg_username && <div className="text-xs text-gray-400">@{conv.tg_username}</div>}
        </div>
        <div className="flex items-center gap-2">
          {["active", "paused", "done"].map((s) => (
            <button
              key={s}
              onClick={() => handleStatus(s)}
              className={`text-xs px-2 py-1 rounded-full ${
                conv.status === s ? STATUS_COLORS[s] : "bg-gray-700 text-gray-400 hover:bg-gray-600"
              }`}
            >
              {s}
            </button>
          ))}
          <button onClick={onClose} className="ml-2 text-gray-400 hover:text-white text-lg leading-none">×</button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4">
        {messages.map((m) => <Message key={m.id} msg={m} />)}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex gap-2 p-3 border-t border-gray-700 bg-gray-800">
        <input
          className="flex-1 bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
          placeholder="Написать вручную..."
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
        />
        <button
          onClick={handleSend}
          disabled={sending || !text.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-4 py-2 rounded text-sm"
        >
          Send
        </button>
      </div>
    </div>
  );
}
