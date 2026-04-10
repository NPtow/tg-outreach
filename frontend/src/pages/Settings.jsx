import { useEffect, useState } from "react";
import { api } from "../api";

export default function Settings() {
  const [form, setForm] = useState({
    openai_key: "",
    model: "gpt-4o-mini",
    system_prompt: "Ты вежливый менеджер по продажам. Отвечай кратко и по делу.",
    auto_reply_enabled: true,
    context_messages: 10,
  });
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getSettings().then(setForm).finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    await api.saveSettings(form);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  if (loading) return <div className="p-8 text-gray-400">Loading...</div>;

  return (
    <div className="p-8 max-w-2xl">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      <div className="space-y-5">
        <div>
          <label className="block text-sm text-gray-400 mb-1">OpenAI API Key</label>
          <input
            type="password"
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm"
            placeholder="sk-..."
            value={form.openai_key}
            onChange={(e) => setForm({ ...form, openai_key: e.target.value })}
          />
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-1">Model</label>
          <select
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm"
            value={form.model}
            onChange={(e) => setForm({ ...form, model: e.target.value })}
          >
            <option value="gpt-4o-mini">gpt-4o-mini (дешевле)</option>
            <option value="gpt-4o">gpt-4o</option>
            <option value="gpt-4-turbo">gpt-4-turbo</option>
          </select>
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-1">System Prompt</label>
          <textarea
            rows={6}
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm font-mono"
            value={form.system_prompt}
            onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
          />
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-1">
            Сообщений в контексте: {form.context_messages}
          </label>
          <input
            type="range"
            min={3}
            max={30}
            value={form.context_messages}
            onChange={(e) => setForm({ ...form, context_messages: Number(e.target.value) })}
            className="w-full"
          />
        </div>

        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={form.auto_reply_enabled}
            onChange={(e) => setForm({ ...form, auto_reply_enabled: e.target.checked })}
            className="w-4 h-4"
          />
          <span className="text-sm">Auto-reply включён глобально</span>
        </label>

        <button
          onClick={handleSave}
          className="bg-blue-600 hover:bg-blue-500 text-white px-6 py-2 rounded text-sm font-medium"
        >
          {saved ? "Сохранено ✓" : "Сохранить"}
        </button>
      </div>
    </div>
  );
}
