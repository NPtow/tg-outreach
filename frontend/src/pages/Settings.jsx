import { useEffect, useState } from "react";
import { api } from "../api";

function Section({ title, children }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
      <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-4">{title}</h3>
      <div className="space-y-4">{children}</div>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <div>
      <label className="text-sm font-medium text-zinc-300 block mb-1">{label}</label>
      {hint && <p className="text-xs text-zinc-500 mb-1.5">{hint}</p>}
      {children}
    </div>
  );
}

const inputCls = "w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500 transition-colors";

const PROVIDERS = [
  { value: "openai",      label: "OpenAI (GPT)" },
  { value: "openrouter",  label: "OpenRouter (350+ моделей)" },
  { value: "anthropic",   label: "Anthropic (Claude)" },
  { value: "ollama",      label: "Ollama (локальная)" },
  { value: "lmstudio",    label: "LM Studio (локальная)" },
];

const OPENAI_MODELS = [
  { value: "gpt-4o-mini",  label: "gpt-4o-mini — быстрая и дешёвая" },
  { value: "gpt-4o",       label: "gpt-4o — умнее" },
  { value: "gpt-4-turbo",  label: "gpt-4-turbo" },
  { value: "o1-mini",      label: "o1-mini" },
];

const ANTHROPIC_MODELS = [
  { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5 — быстрая" },
  { value: "claude-sonnet-4-6",         label: "Claude Sonnet 4.6 — баланс" },
  { value: "claude-opus-4-6",           label: "Claude Opus 4.6 — мощная" },
];

export default function Settings() {
  const [form, setForm] = useState({
    provider: "openai",
    openai_key: "",
    anthropic_key: "",
    base_url: "",
    model: "gpt-4o-mini",
    system_prompt: "Ты вежливый менеджер по продажам. Отвечай кратко и по делу.",
    auto_reply_enabled: true,
    context_messages: 10,
  });
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  useEffect(() => { api.getSettings().then(setForm).finally(() => setLoading(false)); }, []);

  const handleSave = async () => {
    await api.saveSettings(form);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const isLocal = form.provider === "ollama" || form.provider === "lmstudio";
  const defaultBaseUrl = form.provider === "ollama" ? "http://localhost:11434/v1" : "http://localhost:1234/v1";

  if (loading) return <div className="p-8 text-zinc-500 text-sm">Загрузка...</div>;

  return (
    <div className="p-8 max-w-2xl space-y-4">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-zinc-100">Settings</h1>
        <p className="text-sm text-zinc-500 mt-0.5">Настройки AI-провайдера и авто-ответов</p>
      </div>

      <Section title="AI Провайдер">
        <Field label="Провайдер">
          <select className={inputCls} value={form.provider} onChange={e => set("provider", e.target.value)}>
            {PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </Field>

        {/* OpenAI */}
        {form.provider === "openai" && (
          <>
            <Field label="OpenAI API Key" hint="Получи на platform.openai.com">
              <input type="password" className={inputCls} placeholder="sk-..." value={form.openai_key}
                onChange={e => set("openai_key", e.target.value)} />
            </Field>
            <Field label="Модель">
              <select className={inputCls} value={form.model} onChange={e => set("model", e.target.value)}>
                {OPENAI_MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </Field>
          </>
        )}

        {/* OpenRouter */}
        {form.provider === "openrouter" && (
          <>
            <Field label="OpenRouter API Key" hint="Получи на openrouter.ai → Keys">
              <input type="password" className={inputCls} placeholder="sk-or-v1-..." value={form.openai_key}
                onChange={e => set("openai_key", e.target.value)} />
            </Field>
            <Field label="Модель" hint="Формат: provider/model-name, например meta-llama/llama-3.3-70b-instruct:free">
              <input className={inputCls} placeholder="meta-llama/llama-3.3-70b-instruct:free" value={form.model}
                onChange={e => set("model", e.target.value)} />
            </Field>
            <div className="bg-zinc-800/50 border border-zinc-700/50 rounded-lg px-4 py-3">
              <p className="text-xs text-zinc-400">Бесплатные модели: <span className="text-zinc-200">meta-llama/llama-3.3-70b-instruct:free</span>, <span className="text-zinc-200">mistralai/mistral-7b-instruct:free</span>, <span className="text-zinc-200">google/gemma-3-27b-it:free</span></p>
            </div>
          </>
        )}

        {/* Anthropic */}
        {form.provider === "anthropic" && (
          <>
            <Field label="Anthropic API Key" hint="Получи на console.anthropic.com">
              <input type="password" className={inputCls} placeholder="sk-ant-..." value={form.anthropic_key}
                onChange={e => set("anthropic_key", e.target.value)} />
            </Field>
            <Field label="Модель">
              <select className={inputCls} value={form.model} onChange={e => set("model", e.target.value)}>
                {ANTHROPIC_MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </Field>
          </>
        )}

        {/* Ollama / LM Studio */}
        {isLocal && (
          <>
            <Field label="Base URL" hint={`По умолчанию: ${defaultBaseUrl}`}>
              <input className={inputCls} placeholder={defaultBaseUrl} value={form.base_url}
                onChange={e => set("base_url", e.target.value)} />
            </Field>
            <Field label="Модель" hint={form.provider === "ollama" ? "Например: llama3, mistral, gemma2" : "Название модели из LM Studio"}>
              <input className={inputCls} placeholder={form.provider === "ollama" ? "llama3" : "local-model"} value={form.model}
                onChange={e => set("model", e.target.value)} />
            </Field>
            <div className="bg-zinc-800/50 border border-zinc-700/50 rounded-lg px-4 py-3">
              <p className="text-xs text-zinc-400">
                {form.provider === "ollama"
                  ? "Убедись что Ollama запущена: ollama serve"
                  : "Убедись что LM Studio запущена с включённым Local Server"}
              </p>
            </div>
          </>
        )}
      </Section>

      <Section title="Промпт">
        <Field label="System Prompt" hint="Инструкция для AI — кто он и как отвечает">
          <textarea rows={6} className={`${inputCls} font-mono text-xs leading-relaxed resize-y`}
            value={form.system_prompt} onChange={e => set("system_prompt", e.target.value)} />
        </Field>
        <Field label={`Сообщений в контексте: ${form.context_messages}`}
          hint="Сколько последних сообщений передавать AI для контекста">
          <div className="flex items-center gap-3">
            <input type="range" min={3} max={30} value={form.context_messages}
              onChange={e => set("context_messages", Number(e.target.value))}
              className="flex-1 accent-blue-500" />
            <span className="text-sm font-mono text-zinc-300 w-6 text-right">{form.context_messages}</span>
          </div>
        </Field>
      </Section>

      <Section title="Авто-ответы">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-zinc-300">Глобальный авто-ответ</p>
            <p className="text-xs text-zinc-500 mt-0.5">AI отвечает на все входящие сообщения</p>
          </div>
          <div className={`relative w-11 h-6 rounded-full cursor-pointer transition-colors ${form.auto_reply_enabled ? "bg-blue-600" : "bg-zinc-700"}`}
            onClick={() => set("auto_reply_enabled", !form.auto_reply_enabled)}>
            <div className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-all ${form.auto_reply_enabled ? "left-5" : "left-0.5"}`} />
          </div>
        </div>
      </Section>

      <div className="flex items-center gap-3 pt-2">
        <button onClick={handleSave} className="btn-primary px-6">
          {saved ? "Сохранено ✓" : "Сохранить"}
        </button>
        {saved && <span className="text-xs text-emerald-400">Изменения применены</span>}
      </div>
    </div>
  );
}
