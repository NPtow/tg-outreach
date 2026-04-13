import { useEffect, useState } from "react";
import { api } from "../api";
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

function CreateModal({ accounts, prompts, onClose, onCreated }) {
  const [form, setForm] = useState({
    name: "", account_id: "",
    delay_min: 30, delay_max: 90, daily_limit: 20,
    send_hour_from: 9, send_hour_to: 21,
    prompt_template_id: "",
    stop_on_reply: true,
    stop_keywords: "",
    hot_keywords: "",
    max_messages: "",
  });
  const [messagesText, setMessagesText] = useState("");
  const [targetsText, setTargetsText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const inputCls = "w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500 transition-colors";

  const handleSubmit = async () => {
    const messages = messagesText.split("---").map(m => m.trim()).filter(Boolean);
    const targets = targetsText.split("\n").map(t => t.trim()).filter(Boolean);
    if (!form.name || !form.account_id) { setError("Заполни название и аккаунт"); return; }
    if (!messages.length) { setError("Добавь хотя бы одно сообщение"); return; }
    if (!targets.length) { setError("Добавь хотя бы один контакт"); return; }
    setLoading(true); setError("");
    try {
      await api.createCampaign({
        ...form,
        account_id: Number(form.account_id),
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
      <div className="space-y-4">
        <div>
          <label className="text-xs font-medium text-zinc-400 block mb-1.5">Название</label>
          <input className={inputCls} placeholder="Outreach #1" value={form.name} onChange={e => setForm({...form, name: e.target.value})} />
        </div>
        <div>
          <label className="text-xs font-medium text-zinc-400 block mb-1.5">Аккаунт для отправки</label>
          <select className={inputCls} value={form.account_id} onChange={e => setForm({...form, account_id: e.target.value})}>
            <option value="">— выбери аккаунт —</option>
            {accounts.filter(a => a.is_active).map(a => (
              <option key={a.id} value={a.id}>{a.name} ({a.phone})</option>
            ))}
          </select>
          {accounts.filter(a => a.is_active).length === 0 && (
            <p className="text-xs text-amber-400 mt-1">Нет активных аккаунтов</p>
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
          {prompts.length === 0 && (
            <p className="text-[11px] text-zinc-600 mt-1">Создай промпты в разделе Prompts чтобы назначать их</p>
          )}
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
          <label className="text-xs font-medium text-zinc-400 block mb-1.5">
            Контакты <span className="text-zinc-600 font-normal">— username[,имя[,компания[,роль[,заметка]]]]</span>
          </label>
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
          <label className="text-xs font-medium text-zinc-400 block mb-1.5">
            Окно отправки <span className="text-zinc-600 font-normal">— по Москве (UTC+3)</span>
          </label>
          <div className="grid grid-cols-2 gap-3">
            {[{ k: "send_hour_from", label: "С (час)" }, { k: "send_hour_to", label: "До (час)" }].map(({ k, label }) => (
              <div key={k}>
                <label className="text-xs text-zinc-500 block mb-1">{label}</label>
                <input type="number" min={0} max={23} className={inputCls} value={form[k]}
                  onChange={e => setForm({...form, [k]: Number(e.target.value)})} />
              </div>
            ))}
          </div>
          <p className="text-[11px] text-zinc-600 mt-1">Отправка с {form.send_hour_from}:00 до {form.send_hour_to}:00 MSK</p>
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

      {error && <p className="text-red-400 text-xs mt-4 bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>}
      <div className="flex gap-2 mt-5">
        <button onClick={handleSubmit} disabled={loading} className="btn-primary">{loading ? "Создаю..." : "Создать кампанию"}</button>
        <button onClick={onClose} className="btn-ghost">Отмена</button>
      </div>
    </Modal>
  );
}

export default function Campaigns() {
  const [campaigns, setCampaigns] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [prompts, setPrompts] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const load = () => api.getCampaigns().then(setCampaigns);

  useEffect(() => {
    load();
    api.getAccounts().then(setAccounts);
    api.getPrompts().then(setPrompts);
  }, []);
  useWsEvent(msg => { if (msg.event === "campaign_progress") load(); });

  const handleStart = async id => { await api.startCampaign(id).catch(e => alert(e.message)); load(); };
  const handlePause = async id => { await api.pauseCampaign(id); load(); };
  const handleRetry = async id => { await api.retryFailed(id).catch(e => alert(e.message)); load(); };
  const handleDelete = async id => { if (!confirm("Удалить кампанию?")) return; await api.deleteCampaign(id); load(); };

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-zinc-100">Campaigns</h1>
          <p className="text-sm text-zinc-500 mt-0.5">Точечные рассылки с контролем лимитов</p>
        </div>
        <button onClick={() => setShowModal(true)} className="btn-primary">+ New Campaign</button>
      </div>

      {campaigns.length === 0 ? (
        <div className="border border-dashed border-zinc-800 rounded-2xl p-12 text-center">
          <div className="text-4xl mb-3">📢</div>
          <p className="text-zinc-400 text-sm font-medium mb-1">Нет кампаний</p>
          <p className="text-zinc-600 text-xs">Создай первую кампанию для точечной рассылки</p>
        </div>
      ) : (
        <div className="space-y-3">
          {campaigns.map(c => {
            const pct = c.total ? Math.round((c.sent / c.total) * 100) : 0;
            const st = STATUS[c.status] || STATUS.draft;
            const promptName = prompts.find(p => p.id === c.prompt_template_id)?.name;
            return (
              <div key={c.id} className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 hover:border-zinc-700 transition-colors">
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
                        {c.delay_min}–{c.delay_max}с · {c.daily_limit}/день · {c.send_hour_from}:00–{c.send_hour_to}:00 MSK
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
              </div>
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
