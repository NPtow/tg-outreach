import { useEffect, useState } from "react";
import { api } from "../api";
import { PageHeader } from "../components/workspace";

function Section({ title, children }) {
  return (
    <div className="rounded-[26px] border border-white/10 bg-white/[0.04] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
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

const inputCls = "w-full rounded-2xl border border-white/10 bg-black/25 px-3.5 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition focus:border-sky-400/40 focus:bg-white/[0.05]";

const PROVIDERS = [
  { value: "openai", label: "OpenAI (GPT)" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "anthropic", label: "Anthropic (Claude)" },
  { value: "ollama", label: "Ollama" },
  { value: "lmstudio", label: "LM Studio" },
];

const OPENAI_MODELS = [
  { value: "gpt-4o-mini", label: "gpt-4o-mini" },
  { value: "gpt-4o", label: "gpt-4o" },
  { value: "gpt-4-turbo", label: "gpt-4-turbo" },
  { value: "o1-mini", label: "o1-mini" },
];

const ANTHROPIC_MODELS = [
  { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
  { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
  { value: "claude-opus-4-6", label: "Claude Opus 4.6" },
];

function SecretField({ label, placeholder, value, onChange, configured, onClear, hint }) {
  return (
    <Field label={label} hint={hint}>
      <div className="space-y-2">
        <input type="password" className={inputCls} placeholder={configured ? "Configured" : placeholder} value={value}
          onChange={onChange} />
        <div className="flex items-center gap-3">
          <span className={`text-xs ${configured ? "text-emerald-400" : "text-zinc-500"}`}>
            {configured ? "Ключ сохранён" : "Ключ не задан"}
          </span>
          {configured && (
            <button type="button" onClick={onClear} className="text-xs text-red-400 hover:text-red-300 transition-colors">
              Очистить
            </button>
          )}
        </div>
      </div>
    </Field>
  );
}

export default function Settings() {
  const [form, setForm] = useState({
    provider: "openai",
    openai_key: "",
    anthropic_key: "",
    openai_key_configured: false,
    anthropic_key_configured: false,
    clear_openai_key: false,
    clear_anthropic_key: false,
    base_url: "",
    model: "gpt-4o-mini",
    system_prompt: "Ты вежливый менеджер по продажам. Отвечай кратко и по делу.",
    auto_reply_enabled: true,
    context_messages: 10,
  });
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    api.getSettings().then((data) => setForm((f) => ({ ...f, ...data }))).finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    await api.saveSettings(form);
    const fresh = await api.getSettings();
    setForm((f) => ({ ...f, ...fresh, openai_key: "", anthropic_key: "", clear_openai_key: false, clear_anthropic_key: false }));
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const isLocal = form.provider === "ollama" || form.provider === "lmstudio";
  const defaultBaseUrl = form.provider === "ollama" ? "http://localhost:11434/v1" : "http://localhost:1234/v1";

  if (loading) return <div className="p-8 text-zinc-500 text-sm">Загрузка...</div>;

  return (
    <div className="max-w-3xl space-y-4">
      <PageHeader
        eyebrow="Control Plane"
        title="Settings"
        description="Настройки AI-провайдера, fallback промпта и глобального auto-reply поведения."
      />

      <Section title="AI Провайдер">
        <Field label="Провайдер">
          <select className={inputCls} value={form.provider} onChange={(e) => set("provider", e.target.value)}>
            {PROVIDERS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </Field>

        {form.provider === "openai" && (
          <>
            <SecretField
              label="OpenAI API Key"
              hint="Ключ не возвращается из backend в браузер"
              placeholder="sk-..."
              value={form.openai_key}
              configured={form.openai_key_configured && !form.clear_openai_key}
              onChange={(e) => setForm((f) => ({ ...f, openai_key: e.target.value, clear_openai_key: false }))}
              onClear={() => setForm((f) => ({ ...f, openai_key: "", clear_openai_key: true, openai_key_configured: false }))}
            />
            <Field label="Модель">
              <select className={inputCls} value={form.model} onChange={(e) => set("model", e.target.value)}>
                {OPENAI_MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </Field>
          </>
        )}

        {form.provider === "openrouter" && (
          <>
            <SecretField
              label="OpenRouter API Key"
              hint="Использует то же защищённое поле, что и OpenAI-compatible ключи"
              placeholder="sk-or-v1-..."
              value={form.openai_key}
              configured={form.openai_key_configured && !form.clear_openai_key}
              onChange={(e) => setForm((f) => ({ ...f, openai_key: e.target.value, clear_openai_key: false }))}
              onClear={() => setForm((f) => ({ ...f, openai_key: "", clear_openai_key: true, openai_key_configured: false }))}
            />
            <Field label="Модель">
              <input className={inputCls} placeholder="meta-llama/llama-3.3-70b-instruct:free" value={form.model}
                onChange={(e) => set("model", e.target.value)} />
            </Field>
          </>
        )}

        {form.provider === "anthropic" && (
          <>
            <SecretField
              label="Anthropic API Key"
              placeholder="sk-ant-..."
              value={form.anthropic_key}
              configured={form.anthropic_key_configured && !form.clear_anthropic_key}
              onChange={(e) => setForm((f) => ({ ...f, anthropic_key: e.target.value, clear_anthropic_key: false }))}
              onClear={() => setForm((f) => ({ ...f, anthropic_key: "", clear_anthropic_key: true, anthropic_key_configured: false }))}
            />
            <Field label="Модель">
              <select className={inputCls} value={form.model} onChange={(e) => set("model", e.target.value)}>
                {ANTHROPIC_MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </Field>
          </>
        )}

        {isLocal && (
          <>
            <Field label="Base URL" hint={`По умолчанию: ${defaultBaseUrl}`}>
              <input className={inputCls} placeholder={defaultBaseUrl} value={form.base_url}
                onChange={(e) => set("base_url", e.target.value)} />
            </Field>
            <Field label="Модель">
              <input className={inputCls} placeholder={form.provider === "ollama" ? "llama3" : "local-model"} value={form.model}
                onChange={(e) => set("model", e.target.value)} />
            </Field>
          </>
        )}
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
