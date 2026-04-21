import { useEffect, useState } from "react";
import { api } from "../api";
import { EmptyState, PageHeader, Surface } from "../components/workspace";
import { useWsEvent } from "../ws";

const STATUS = {
  draft:   { cls: "bg-zinc-800 text-zinc-400",          label: "Draft" },
  running: { cls: "bg-emerald-500/15 text-emerald-400", label: "Running" },
  paused:  { cls: "bg-amber-500/15 text-amber-400",     label: "Paused" },
  done:    { cls: "bg-blue-500/15 text-blue-400",       label: "Done" },
};

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 rounded-2xl w-full max-w-lg border border-zinc-700/50 shadow-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
          <h2 className="text-base font-semibold text-zinc-100">{title}</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200 text-xl w-7 h-7 flex items-center justify-center rounded-lg hover:bg-zinc-800 transition-colors">×</button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

// ── Contact picker modal (two-level: batches → contacts) ────────────────────
function ContactPicker({ onClose, onSelect }) {
  const [batches, setBatches] = useState([]);
  const [activeBatch, setActiveBatch] = useState(null); // null = batch list
  const [contacts, setContacts] = useState([]);
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState(new Set()); // contact ids

  useEffect(() => { api.getContactBatches().then(setBatches); }, []);

  const loadContacts = (batchId) => {
    api.getContacts("", batchId).then(setContacts);
  };

  const drillIn = (batch) => {
    setActiveBatch(batch);
    setSearch("");
    loadContacts(batch.id);
  };

  const selectAllBatch = (batch) => {
    api.getContacts("", batch.id).then(cs => {
      setPicked(prev => {
        const n = new Set(prev);
        cs.forEach(c => n.add(c.id));
        return n;
      });
      // Also ensure we have these contacts cached for handleAdd
      setContacts(prev => {
        const existing = new Map(prev.map(c => [c.id, c]));
        cs.forEach(c => existing.set(c.id, c));
        return [...existing.values()];
      });
    });
  };

  const filtered = activeBatch
    ? contacts.filter(c => {
        if (!search) return true;
        const s = search.toLowerCase();
        return (c.username + (c.display_name || "") + (c.company || "") + (c.role || "")).toLowerCase().includes(s);
      })
    : [];

  const togglePick = (c) => {
    setPicked(prev => {
      const n = new Set(prev);
      if (n.has(c.id)) n.delete(c.id); else n.add(c.id);
      return n;
    });
    setContacts(prev => {
      const existing = new Map(prev.map(x => [x.id, x]));
      existing.set(c.id, c);
      return [...existing.values()];
    });
  };

  const handleAdd = () => {
    const chosen = contacts.filter(c => picked.has(c.id));
    onSelect(chosen);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-[60] p-4">
      <div className="bg-zinc-900 rounded-2xl w-full max-w-xl border border-zinc-700/50 shadow-2xl max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            {activeBatch && (
              <button onClick={() => { setActiveBatch(null); setSearch(""); }} className="text-zinc-500 hover:text-zinc-200 text-sm mr-1">← </button>
            )}
            <h2 className="text-base font-semibold text-zinc-100 truncate">
              {activeBatch ? activeBatch.name : "Выбрать контакты из базы"}
            </h2>
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200 text-xl w-7 h-7 flex items-center justify-center rounded-lg hover:bg-zinc-800 transition-colors shrink-0">×</button>
        </div>

        {activeBatch && (
          <div className="px-4 py-3 border-b border-zinc-800 shrink-0">
            <input
              className="w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500"
              placeholder="Поиск..."
              value={search} onChange={e => setSearch(e.target.value)}
            />
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          {!activeBatch ? (
            /* Batch list */
            batches.length === 0 ? (
              <div className="p-8 text-center text-zinc-500 text-sm">База контактов пуста — сначала импортируй CSV в разделе Contacts</div>
            ) : (
              <div className="divide-y divide-zinc-800/50">
                {batches.map(b => (
                  <div key={b.id} className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/30 transition-colors">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-zinc-200 font-medium">{b.name}</p>
                      <p className="text-xs text-zinc-500">{b.count} контактов</p>
                    </div>
                    <button
                      onClick={() => selectAllBatch(b)}
                      className="text-xs bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 px-2.5 py-1.5 rounded-lg transition-colors shrink-0">
                      Выбрать все
                    </button>
                    <button
                      onClick={() => drillIn(b)}
                      className="text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-2.5 py-1.5 rounded-lg transition-colors shrink-0">
                      Открыть →
                    </button>
                  </div>
                ))}
              </div>
            )
          ) : (
            /* Contact list inside a batch */
            <div className="divide-y divide-zinc-800/50">
              <div className="flex items-center gap-3 px-4 py-2 bg-zinc-800/30">
                <button
                  onClick={() => {
                    const allIds = filtered.map(c => c.id);
                    const allSelected = allIds.every(id => picked.has(id));
                    setPicked(prev => {
                      const n = new Set(prev);
                      if (allSelected) allIds.forEach(id => n.delete(id));
                      else allIds.forEach(id => n.add(id));
                      return n;
                    });
                    setContacts(prev => {
                      const existing = new Map(prev.map(c => [c.id, c]));
                      filtered.forEach(c => existing.set(c.id, c));
                      return [...existing.values()];
                    });
                  }}
                  className="text-xs text-zinc-400 hover:text-zinc-200 transition-colors">
                  Выбрать всё в батче
                </button>
              </div>
              {filtered.length === 0 ? (
                <div className="p-8 text-center text-zinc-500 text-sm">Ничего не найдено</div>
              ) : filtered.map(c => (
                <div key={c.id}
                  className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-zinc-800/40 transition-colors ${picked.has(c.id) ? "bg-zinc-800/30" : ""}`}
                  onClick={() => togglePick(c)}>
                  <input type="checkbox" className="accent-blue-500 shrink-0" checked={picked.has(c.id)} readOnly />
                  <div className="min-w-0">
                    <span className="text-sm text-blue-400 font-mono">@{c.username}</span>
                    {c.display_name && <span className="text-xs text-zinc-300 ml-2">{c.display_name}</span>}
                    {(c.company || c.role) && (
                      <span className="text-xs text-zinc-600 ml-2">{[c.company, c.role].filter(Boolean).join(" · ")}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="px-4 py-3 border-t border-zinc-800 flex items-center justify-between shrink-0">
          <span className="text-xs text-zinc-500">{picked.size} выбрано</span>
          <div className="flex gap-2">
            <button onClick={onClose} className="btn-ghost text-sm">Отмена</button>
            <button onClick={handleAdd} disabled={picked.size === 0} className="btn-primary text-sm">
              Добавить {picked.size > 0 ? `(${picked.size})` : ""}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Create Campaign modal ────────────────────────────────────────
function CreateModal({ accounts, prompts, onClose, onCreated }) {
  const [form, setForm] = useState({
    name: "",
    account_ids: [],
    delay_min: 30, delay_max: 90, daily_limit: 20,
    send_window_enabled: false,
    send_hour_from: 9, send_hour_to: 21,
    prompt_template_id: "",
    stop_on_reply: false,
    stop_keywords: "",
    hot_keywords: "",
    max_messages: "",
  });
  const [messagesText, setMessagesText] = useState("");
  const [targetsText, setTargetsText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showPicker, setShowPicker] = useState(false);

  const inputCls = "w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500 transition-colors";
  const activeAccounts = accounts.filter(a => a.can_receive);

  const toggleAccount = (id) => {
    setForm(f => {
      const ids = f.account_ids.includes(id)
        ? f.account_ids.filter(x => x !== id)
        : [...f.account_ids, id];
      return { ...f, account_ids: ids };
    });
  };

  const handlePickerSelect = (chosen) => {
    const lines = chosen.map(c => {
      const parts = [c.username];
      if (c.display_name) parts.push(c.display_name);
      else if (c.company || c.role || c.custom_note) parts.push("");
      if (c.company) parts.push(c.company);
      else if (c.role || c.custom_note) parts.push("");
      if (c.role) parts.push(c.role);
      else if (c.custom_note) parts.push("");
      if (c.custom_note) parts.push(c.custom_note);
      // Trim trailing empty
      while (parts.length > 1 && parts[parts.length - 1] === "") parts.pop();
      return parts.join(",");
    });
    const existing = targetsText.trim();
    setTargetsText(existing ? existing + "\n" + lines.join("\n") : lines.join("\n"));
  };

  const handleSubmit = async () => {
    const messages = messagesText.split("---").map(m => m.trim()).filter(Boolean);
    const targets = targetsText.split("\n").map(t => t.trim()).filter(Boolean);
    if (!form.name) { setError("Заполни название"); return; }
    if (form.account_ids.length === 0) { setError("Выбери хотя бы один аккаунт"); return; }
    if (!messages.length) { setError("Добавь хотя бы одно сообщение"); return; }
    if (!targets.length) { setError("Добавь хотя бы один контакт"); return; }
    setLoading(true); setError("");
    try {
      await api.createCampaign({
        ...form,
        prompt_template_id: form.prompt_template_id ? Number(form.prompt_template_id) : null,
        max_messages: form.max_messages ? Number(form.max_messages) : null,
        messages,
        targets,
      });
      onCreated();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const targetCount = targetsText.split("\n").filter(t => t.trim()).length;
  const csvCount = targetsText.split("\n").filter(t => t.includes(",") && t.trim()).length;
  const usedVars = ["first_name","company","role","note"].filter(v => messagesText.includes(`{${v}}`));

  return (
    <Modal title="Новая кампания" onClose={onClose}>
      {error && <p className="text-red-400 text-xs mb-4 bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>}
      <div className="space-y-4">
        {/* Name */}
        <div>
          <label className="text-xs font-medium text-zinc-400 block mb-1.5">Название</label>
          <input className={inputCls} placeholder="Outreach #1" value={form.name} onChange={e => setForm({...form, name: e.target.value})} />
        </div>

        {/* Accounts — multi-select checkboxes */}
        <div>
          <label className="text-xs font-medium text-zinc-400 block mb-1.5">
            Аккаунты для отправки
            {form.account_ids.length > 0 && (
              <span className="ml-1.5 text-blue-400 font-normal">{form.account_ids.length} выбрано</span>
            )}
          </label>
          {activeAccounts.length === 0 ? (
            <p className="text-xs text-amber-400">Нет активных аккаунтов</p>
          ) : (
            <div className="space-y-1.5">
              {activeAccounts.map(a => (
                <label key={a.id} className={`flex items-center gap-2.5 px-3 py-2 rounded-lg cursor-pointer border transition-colors ${form.account_ids.includes(a.id) ? "bg-blue-600/10 border-blue-500/30 text-zinc-100" : "border-zinc-800 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"}`}
                  onClick={() => toggleAccount(a.id)}>
                  <div className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors ${form.account_ids.includes(a.id) ? "bg-blue-600 border-blue-600" : "border-zinc-600"}`}>
                    {form.account_ids.includes(a.id) && <span className="text-white text-[10px] font-bold">✓</span>}
                  </div>
                  <span className="text-sm">{a.name}</span>
                  <span className="text-xs text-zinc-600 ml-auto">{a.phone}</span>
                </label>
              ))}
            </div>
          )}
          {form.account_ids.length > 1 && (
            <p className="text-[11px] text-zinc-600 mt-1.5">Контакты распределятся между аккаунтами автоматически</p>
          )}
        </div>

        {/* Prompt selector */}
        <div>
          <label className="text-xs font-medium text-zinc-400 block mb-1.5">
            Промпт агента <span className="text-zinc-600 font-normal">— для авто-ответов на входящие</span>
          </label>
          <select className={inputCls} value={form.prompt_template_id} onChange={e => setForm({...form, prompt_template_id: e.target.value})}>
            <option value="">— глобальный (из Settings) —</option>
            {prompts.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        {/* Messages */}
        <div>
          <label className="text-xs font-medium text-zinc-400 block mb-1.5">
            Варианты первого сообщения <span className="text-zinc-600 font-normal">— разделяй через ---</span>
          </label>
          <textarea rows={5} className={`${inputCls} resize-y`}
            placeholder={"Привет, {first_name}! Ты из {company}? Хочу обсудить...\n---\nДобрый день! Вижу что ты {role}, интересно..."}
            value={messagesText} onChange={e => setMessagesText(e.target.value)} />
          <div className="flex items-center gap-3 mt-1">
            <p className="text-[11px] text-zinc-600">{messagesText.split("---").filter(m => m.trim()).length} вариант(а)</p>
            {usedVars.length > 0 && (
              <p className="text-[11px] text-blue-400">использует: {usedVars.map(v => `{${v}}`).join(", ")}</p>
            )}
          </div>
        </div>

        {/* Targets */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs font-medium text-zinc-400">
              Контакты <span className="text-zinc-600 font-normal">— username[,имя[,компания[,роль[,заметка]]]]</span>
            </label>
            <button type="button" onClick={() => setShowPicker(true)}
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1 shrink-0">
              👥 Из базы контактов
            </button>
          </div>
          <textarea rows={5} className={`${inputCls} resize-y font-mono text-xs`}
            placeholder={"john_doe\njane_smith,Джейн\nbob_cto,Боб,OpenAI,CTO,познакомились на ProductConf"}
            value={targetsText} onChange={e => setTargetsText(e.target.value)} />
          <p className="text-[11px] text-zinc-600 mt-1">
            {targetCount} контактов
            {csvCount > 0 && <span className="text-blue-400 ml-2">· {csvCount} с доп.данными</span>}
          </p>
        </div>

        {/* Timing */}
        <div className="grid grid-cols-3 gap-3">
          {[
            { k: "delay_min", label: "Задержка мин", suffix: "с" },
            { k: "delay_max", label: "Задержка макс", suffix: "с" },
            { k: "daily_limit", label: "Лимит в день", suffix: "msg" },
          ].map(({ k, label, suffix }) => (
            <div key={k}>
              <label className="text-xs font-medium text-zinc-400 block mb-1.5">{label}</label>
              <div className="relative">
                <input type="number" className={`${inputCls} pr-7`} value={form[k]}
                  onChange={e => setForm({...form, [k]: Number(e.target.value)})} />
                <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-zinc-600">{suffix}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Time window */}
        <div>
          <label className="flex items-center gap-2.5 cursor-pointer mb-2"
            onClick={() => setForm(f => ({ ...f, send_window_enabled: !f.send_window_enabled }))}>
            <div className={`relative w-8 h-4 rounded-full transition-colors shrink-0 ${form.send_window_enabled ? "bg-blue-600" : "bg-zinc-700"}`}>
              <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${form.send_window_enabled ? "left-[18px]" : "left-0.5"}`} />
            </div>
            <span className="text-xs font-medium text-zinc-400">
              Ограничить время отправки <span className="text-zinc-600 font-normal">— по Москве (UTC+3)</span>
            </span>
          </label>
          {form.send_window_enabled && (
            <div>
              <div className="grid grid-cols-2 gap-3">
                {[{ k: "send_hour_from", label: "С (час 0–23)" }, { k: "send_hour_to", label: "До (час 0–23)" }].map(({ k, label }) => (
                  <div key={k}>
                    <label className="text-xs text-zinc-500 block mb-1">{label}</label>
                    <input type="number" min={0} max={23} className={inputCls} value={form[k]}
                      onChange={e => setForm({...form, [k]: Number(e.target.value)})} />
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-zinc-600 mt-1">
                {form.send_hour_from < form.send_hour_to
                  ? `Отправка с ${form.send_hour_from}:00 до ${form.send_hour_to}:00 MSK`
                  : `Ночная отправка: с ${form.send_hour_from}:00 до ${form.send_hour_to}:00 MSK (+1 день)`}
              </p>
            </div>
          )}
        </div>

        {/* Advanced / stop conditions */}
        <div className="border-t border-zinc-800 pt-3">
          <button type="button" onClick={() => setShowAdvanced(!showAdvanced)}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors flex items-center gap-1">
            <span className={`transition-transform ${showAdvanced ? "rotate-90" : ""}`}>▶</span>
            Условия остановки
          </button>
          {showAdvanced && (
            <div className="space-y-3 mt-3">
              <label className="flex items-center gap-2.5 text-sm text-zinc-300 cursor-pointer">
                <div className={`relative w-8 h-4 rounded-full transition-colors shrink-0 ${form.stop_on_reply ? "bg-blue-600" : "bg-zinc-700"}`}
                  onClick={() => setForm({...form, stop_on_reply: !form.stop_on_reply})}>
                  <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${form.stop_on_reply ? "left-[18px]" : "left-0.5"}`} />
                </div>
                <span className="text-xs text-zinc-300">Остановить авто-ответ когда человек написал</span>
              </label>
              <div>
                <label className="text-xs font-medium text-zinc-400 block mb-1.5">
                  Стоп-слова <span className="text-zinc-600 font-normal">— через запятую → добавить в чёрный список</span>
                </label>
                <input className={inputCls} placeholder="нет,отписка,стоп,не интересно"
                  value={form.stop_keywords} onChange={e => setForm({...form, stop_keywords: e.target.value})} />
              </div>
              <div>
                <label className="text-xs font-medium text-zinc-400 block mb-1.5">
                  Горячие слова <span className="text-zinc-600 font-normal">— через запятую → пометить 🔥</span>
                </label>
                <input className={inputCls} placeholder="интересно,расскажи,позвони,да"
                  value={form.hot_keywords} onChange={e => setForm({...form, hot_keywords: e.target.value})} />
              </div>
              <div>
                <label className="text-xs font-medium text-zinc-400 block mb-1.5">
                  Макс. ответов GPT <span className="text-zinc-600 font-normal">— затем пауза (пусто = без лимита)</span>
                </label>
                <input type="number" className={inputCls} placeholder="5"
                  value={form.max_messages} onChange={e => setForm({...form, max_messages: e.target.value})} />
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="flex gap-2 mt-5">
        <button onClick={handleSubmit} disabled={loading} className="btn-primary">{loading ? "Создаю..." : "Создать кампанию"}</button>
        <button onClick={onClose} className="btn-ghost">Отмена</button>
      </div>

      {showPicker && (
        <ContactPicker onClose={() => setShowPicker(false)} onSelect={handlePickerSelect} />
      )}
    </Modal>
  );
}

export default function Campaigns() {
  const [campaigns, setCampaigns] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [prompts, setPrompts] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [startErrors, setStartErrors] = useState({});
  const load = () => api.getCampaigns().then(setCampaigns);

  useEffect(() => {
    load();
    api.getAccounts().then(setAccounts);
    api.getPrompts().then(setPrompts);
  }, []);
  useWsEvent(msg => { if (msg.event === "campaign_progress") load(); });

  const handleStart = async id => {
    try {
      const result = await api.startCampaign(id);
      setStartErrors((prev) => ({ ...prev, [id]: null }));
      if (result?.blocked_accounts?.length) {
        setStartErrors((prev) => ({
          ...prev,
          [id]: `Часть аккаунтов исключена: ${result.blocked_accounts.map((a) => `${a.name || "#" + a.account_id} → ${a.reason}`).join(", ")}`,
        }));
      }
    } catch (e) {
      const payload = e.payload;
      if (payload?.blocked_accounts?.length) {
        setStartErrors((prev) => ({
          ...prev,
          [id]: payload.blocked_accounts.map((a) => `${a.name || "#" + a.account_id} → ${a.reason}${a.error ? ` (${a.error})` : ""}`).join("; "),
        }));
      } else {
        setStartErrors((prev) => ({ ...prev, [id]: e.message }));
      }
    }
    load();
  };
  const handlePause = async id => { await api.pauseCampaign(id); load(); };
  const handleRetry = async id => { await api.retryFailed(id).catch(e => alert(e.message)); load(); };
  const handleDelete = async id => { if (!confirm("Удалить кампанию?")) return; await api.deleteCampaign(id); load(); };

  const accountName = (ids) => {
    if (!ids || ids.length === 0) return "—";
    const names = ids.map(id => accounts.find(a => a.id === id)?.name || `#${id}`);
    if (names.length === 1) return names[0];
    return `${names[0]} +${names.length - 1}`;
  };

  const runningCount = campaigns.filter((campaign) => campaign.is_running).length;
  const totalSent = campaigns.reduce((sum, campaign) => sum + (campaign.sent || 0), 0);
  const totalFailed = campaigns.reduce((sum, campaign) => sum + (campaign.failed || 0), 0);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Execution"
        title="Campaigns"
        description="Точечные outreach-волны с контролем задержек, лимитов, окна отправки и стоп-правил по ответам."
        actions={<button onClick={() => setShowModal(true)} className="btn-primary">+ New Campaign</button>}
        stats={[
          { label: "Campaigns", value: campaigns.length, tone: "neutral", caption: "Configured waves" },
          { label: "Running", value: runningCount, tone: runningCount ? "emerald" : "neutral", caption: "Currently in motion" },
          { label: "Sent", value: totalSent, tone: totalSent ? "blue" : "neutral", caption: "Delivered messages" },
          { label: "Failed", value: totalFailed, tone: totalFailed ? "rose" : "neutral", caption: totalFailed ? "Needs retry or review" : "No failures logged" },
        ]}
      />

      {campaigns.length === 0 ? (
        <EmptyState icon="📢" title="No campaigns yet" description="Создайте первую кампанию, чтобы запустить контролируемую рассылку по импортированным контактам." />
      ) : (
        <div className="space-y-3">
          {campaigns.map(c => {
            const pct = c.total ? Math.round((c.sent / c.total) * 100) : 0;
            const st = STATUS[c.status] || STATUS.draft;
            const promptName = prompts.find(p => p.id === c.prompt_template_id)?.name;
            return (
              <Surface key={c.id} className="p-5 transition-colors hover:border-white/16">
                <div className="flex items-start justify-between gap-4 mb-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${c.is_running ? "bg-emerald-500 animate-pulse" : "bg-zinc-600"}`} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="font-medium text-zinc-100 text-sm">{c.name}</p>
                        {promptName && (
                          <span className="text-[10px] bg-violet-500/15 text-violet-400 px-1.5 py-0.5 rounded-full shrink-0">{promptName}</span>
                        )}
                        {c.stop_on_reply && (
                          <span className="text-[10px] bg-zinc-800 text-zinc-500 px-1.5 py-0.5 rounded-full shrink-0">⏸ reply</span>
                        )}
                      </div>
                      <p className="text-xs text-zinc-500 mt-0.5">
                        {accountName(c.account_ids)} · {c.delay_min}–{c.delay_max}с · {c.daily_limit}/день
                        {c.send_window_enabled && ` · ${c.send_hour_from}:00–${c.send_hour_to}:00 MSK`}
                      </p>
                    </div>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${st.cls}`}>{st.label}</span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {c.status !== "done" && !c.is_running && (
                      <button onClick={() => handleStart(c.id)}
                        className="text-xs bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
                        ▶ Запустить
                      </button>
                    )}
                    {c.is_running && (
                      <button onClick={() => handlePause(c.id)}
                        className="text-xs bg-amber-600 hover:bg-amber-500 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
                        ⏸ Пауза
                      </button>
                    )}
                    {c.failed > 0 && !c.is_running && (
                      <button onClick={() => handleRetry(c.id)}
                        className="text-xs bg-zinc-700 hover:bg-zinc-600 text-zinc-300 px-3 py-1.5 rounded-lg font-medium transition-colors">
                        ↺ Retry ({c.failed})
                      </button>
                    )}
                    <button onClick={() => handleDelete(c.id)} className="text-xs text-zinc-600 hover:text-red-400 transition-colors px-2 py-1.5">
                      Удалить
                    </button>
                  </div>
                </div>
                <div className="flex items-center gap-4 mb-2">
                  <span className="text-xs text-zinc-400">
                    <span className="text-zinc-100 font-medium">{c.sent}</span>/{c.total} отправлено
                  </span>
                  {c.failed > 0 && <span className="text-xs text-red-400">{c.failed} ошибок</span>}
                  {c.skipped > 0 && <span className="text-xs text-zinc-600">{c.skipped} пропущено</span>}
                  <span className="text-xs text-zinc-600 ml-auto">{pct}%</span>
                </div>
                <div className="w-full bg-zinc-800 rounded-full h-1">
                  <div className={`h-1 rounded-full transition-all duration-500 ${c.status === "done" ? "bg-blue-500" : "bg-emerald-500"}`}
                    style={{ width: `${pct}%` }} />
                </div>
                {startErrors[c.id] && (
                  <p className="text-xs text-red-300 bg-red-500/10 px-3 py-2 rounded-lg mt-3">
                    {startErrors[c.id]}
                  </p>
                )}
              </Surface>
            );
          })}
        </div>
      )}

      {showModal && (
        <CreateModal accounts={accounts} prompts={prompts} onClose={() => setShowModal(false)}
          onCreated={() => { setShowModal(false); load(); }} />
      )}
    </div>
  );
}
