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

function CreateModal({ accounts, onClose, onCreated }) {
  const [form, setForm] = useState({ name: "", account_id: "", delay_min: 30, delay_max: 90, daily_limit: 20 });
  const [messagesText, setMessagesText] = useState("");
  const [targetsText, setTargetsText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const inputCls = "w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500 transition-colors";

  const handleSubmit = async () => {
    const messages = messagesText.split("---").map(m => m.trim()).filter(Boolean);
    const targets = targetsText.split("\n").map(t => t.trim()).filter(Boolean);
    if (!form.name || !form.account_id) { setError("Заполни название и аккаунт"); return; }
    if (!messages.length) { setError("Добавь хотя бы одно сообщение"); return; }
    if (!targets.length) { setError("Добавь хотя бы один контакт"); return; }
    setLoading(true); setError("");
    try {
      await api.createCampaign({ ...form, account_id: Number(form.account_id), messages, targets });
      onCreated();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

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
            <p className="text-xs text-amber-400 mt-1">Нет активных аккаунтов — сначала подключи аккаунт</p>
          )}
        </div>
        <div>
          <label className="text-xs font-medium text-zinc-400 block mb-1.5">
            Варианты сообщений <span className="text-zinc-600 font-normal">— разделяй через ---</span>
          </label>
          <textarea rows={5} className={`${inputCls} resize-y`}
            placeholder={"Привет! Хотел бы обсудить сотрудничество...\n---\nДобрый день! Увидел твой профиль и думаю..."}
            value={messagesText} onChange={e => setMessagesText(e.target.value)} />
          <p className="text-[11px] text-zinc-600 mt-1">
            {messagesText.split("---").filter(m => m.trim()).length} вариант(а) сообщений
          </p>
        </div>
        <div>
          <label className="text-xs font-medium text-zinc-400 block mb-1.5">
            Контакты <span className="text-zinc-600 font-normal">— по одному на строку, без @</span>
          </label>
          <textarea rows={5} className={`${inputCls} resize-y font-mono text-xs`}
            placeholder={"username1\nusername2\nusername3"}
            value={targetsText} onChange={e => setTargetsText(e.target.value)} />
          <p className="text-[11px] text-zinc-600 mt-1">
            {targetsText.split("\n").filter(t => t.trim()).length} контактов
          </p>
        </div>
        <div className="grid grid-cols-3 gap-3 pt-1">
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
  const [showModal, setShowModal] = useState(false);
  const load = () => api.getCampaigns().then(setCampaigns);

  useEffect(() => { load(); api.getAccounts().then(setAccounts); }, []);
  useWsEvent(msg => { if (msg.event === "campaign_progress") load(); });

  const handleStart = async id => { await api.startCampaign(id).catch(e => alert(e.message)); load(); };
  const handlePause = async id => { await api.pauseCampaign(id); load(); };
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
            return (
              <div key={c.id} className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 hover:border-zinc-700 transition-colors">
                <div className="flex items-start justify-between gap-4 mb-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${c.is_running ? "bg-emerald-500 animate-pulse" : "bg-zinc-600"}`} />
                    <div className="min-w-0">
                      <p className="font-medium text-zinc-100 text-sm">{c.name}</p>
                      <p className="text-xs text-zinc-500 mt-0.5">
                        задержка {c.delay_min}–{c.delay_max}с · лимит {c.daily_limit}/день
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
        <CreateModal accounts={accounts} onClose={() => setShowModal(false)}
          onCreated={() => { setShowModal(false); load(); }} />
      )}
    </div>
  );
}
