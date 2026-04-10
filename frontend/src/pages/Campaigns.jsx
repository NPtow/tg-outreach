import { useEffect, useState } from "react";
import { api } from "../api";
import { useWsEvent } from "../ws";

function CreateModal({ accounts, onClose, onCreated }) {
  const [form, setForm] = useState({
    name: "", account_id: "", delay_min: 30, delay_max: 90, daily_limit: 20,
  });
  const [messagesText, setMessagesText] = useState("");
  const [targetsText, setTargetsText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    const messages = messagesText.split("---").map((m) => m.trim()).filter(Boolean);
    const targets = targetsText.split("\n").map((t) => t.trim()).filter(Boolean);
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
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg p-6 w-full max-w-lg border border-gray-600 max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-bold mb-4">Новая кампания</h2>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-400 block mb-1">Название</label>
            <input className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
              value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Аккаунт для отправки</label>
            <select className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
              value={form.account_id} onChange={(e) => setForm({ ...form, account_id: e.target.value })}>
              <option value="">— выбери —</option>
              {accounts.filter(a => a.is_active).map(a => (
                <option key={a.id} value={a.id}>{a.name} ({a.phone})</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">
              Варианты сообщений <span className="text-gray-500">(разделяй через ---)</span>
            </label>
            <textarea rows={5} className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
              placeholder={"Привет! Хотел бы обсудить...\n---\nДобрый день! Увидел ваш профиль..."}
              value={messagesText} onChange={(e) => setMessagesText(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">
              Контакты <span className="text-gray-500">(username или @username, по одному на строку)</span>
            </label>
            <textarea rows={5} className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
              placeholder={"username1\nusername2\n@username3"}
              value={targetsText} onChange={(e) => setTargetsText(e.target.value)} />
          </div>
          <div className="grid grid-cols-3 gap-2">
            {[
              { k: "delay_min", label: "Задержка мин (сек)" },
              { k: "delay_max", label: "Задержка макс (сек)" },
              { k: "daily_limit", label: "Лимит в день" },
            ].map(({ k, label }) => (
              <div key={k}>
                <label className="text-xs text-gray-400 block mb-1">{label}</label>
                <input type="number" className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
                  value={form[k]} onChange={(e) => setForm({ ...form, [k]: Number(e.target.value) })} />
              </div>
            ))}
          </div>
        </div>
        {error && <p className="text-red-400 text-sm mt-3">{error}</p>}
        <div className="flex gap-3 mt-5">
          <button onClick={handleSubmit} disabled={loading}
            className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-4 py-2 rounded text-sm">
            {loading ? "Создаю..." : "Создать"}
          </button>
          <button onClick={onClose} className="text-gray-400 hover:text-white px-4 py-2 rounded text-sm">Отмена</button>
        </div>
      </div>
    </div>
  );
}

const STATUS_COLORS = {
  draft: "bg-gray-700 text-gray-300",
  running: "bg-green-900 text-green-300",
  paused: "bg-yellow-900 text-yellow-300",
  done: "bg-blue-900 text-blue-300",
};

export default function Campaigns() {
  const [campaigns, setCampaigns] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [showModal, setShowModal] = useState(false);

  const load = () => api.getCampaigns().then(setCampaigns);

  useEffect(() => {
    load();
    api.getAccounts().then(setAccounts);
  }, []);

  useWsEvent((msg) => {
    if (msg.event === "campaign_progress") load();
  });

  const handleStart = async (id) => {
    await api.startCampaign(id).catch((e) => alert(e.message));
    load();
  };
  const handlePause = async (id) => { await api.pauseCampaign(id); load(); };
  const handleDelete = async (id) => {
    if (!confirm("Удалить кампанию?")) return;
    await api.deleteCampaign(id); load();
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Campaigns</h1>
        <button onClick={() => setShowModal(true)}
          className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded text-sm font-medium">
          + New Campaign
        </button>
      </div>

      {campaigns.length === 0 ? (
        <p className="text-gray-500 text-sm">Нет кампаний. Создай первую.</p>
      ) : (
        <div className="space-y-3">
          {campaigns.map((c) => {
            const pct = c.total ? Math.round((c.sent / c.total) * 100) : 0;
            return (
              <div key={c.id} className="bg-gray-800 border border-gray-700 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <span className="font-medium">{c.name}</span>
                    <span className={`ml-3 text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[c.status] || STATUS_COLORS.draft}`}>
                      {c.status}
                    </span>
                  </div>
                  <div className="flex gap-2">
                    {c.status !== "done" && !c.is_running && (
                      <button onClick={() => handleStart(c.id)}
                        className="text-xs bg-green-700 hover:bg-green-600 text-white px-3 py-1 rounded">
                        Запустить
                      </button>
                    )}
                    {c.is_running && (
                      <button onClick={() => handlePause(c.id)}
                        className="text-xs bg-yellow-700 hover:bg-yellow-600 text-white px-3 py-1 rounded">
                        Пауза
                      </button>
                    )}
                    <button onClick={() => handleDelete(c.id)}
                      className="text-xs text-red-400 hover:text-red-300">Удалить</button>
                  </div>
                </div>
                <div className="text-xs text-gray-400 mb-2">
                  {c.sent}/{c.total} отправлено · {c.failed} ошибок · лимит {c.daily_limit}/день · задержка {c.delay_min}-{c.delay_max}с
                </div>
                <div className="w-full bg-gray-700 rounded-full h-1.5">
                  <div className="bg-blue-500 h-1.5 rounded-full transition-all" style={{ width: `${pct}%` }} />
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
