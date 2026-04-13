import { useEffect, useState } from "react";
import { api } from "../api";

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

function PromptForm({ initial, onSave, onClose, saving }) {
  const [form, setForm] = useState(initial || { name: "", description: "", system_prompt: "" });
  const inputCls = "w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500 transition-colors";

  return (
    <div className="space-y-4">
      <div>
        <label className="text-xs font-medium text-zinc-400 block mb-1.5">Название</label>
        <input className={inputCls} placeholder="Холодный outreach" value={form.name}
          onChange={e => setForm({ ...form, name: e.target.value })} />
      </div>
      <div>
        <label className="text-xs font-medium text-zinc-400 block mb-1.5">Описание <span className="text-zinc-600 font-normal">(для себя)</span></label>
        <input className={inputCls} placeholder="Короткий и конкретный тон, давим на боли" value={form.description}
          onChange={e => setForm({ ...form, description: e.target.value })} />
      </div>
      <div>
        <label className="text-xs font-medium text-zinc-400 block mb-1.5">System Prompt</label>
        <textarea rows={8} className={`${inputCls} resize-y font-mono text-xs`}
          placeholder={"Ты менеджер по партнёрствам. Твоя задача — выявить интерес к сотрудничеству.\n\nТон: дружелюбный, профессиональный, краткий.\nНе навязывай, задавай вопросы.\nОтвечай на том же языке что собеседник."}
          value={form.system_prompt}
          onChange={e => setForm({ ...form, system_prompt: e.target.value })} />
        <p className="text-[11px] text-zinc-600 mt-1">{form.system_prompt.length} символов</p>
      </div>
      <div className="flex gap-2 pt-1">
        <button onClick={() => onSave(form)} disabled={saving || !form.name || !form.system_prompt}
          className="btn-primary">{saving ? "Сохраняю..." : "Сохранить"}</button>
        <button onClick={onClose} className="btn-ghost">Отмена</button>
      </div>
    </div>
  );
}

export default function Prompts() {
  const [prompts, setPrompts] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);
  const load = () => api.getPrompts().then(setPrompts);

  useEffect(() => { load(); }, []);

  const handleCreate = async (form) => {
    setSaving(true);
    try { await api.createPrompt(form); setShowCreate(false); load(); }
    finally { setSaving(false); }
  };

  const handleUpdate = async (id, form) => {
    setSaving(true);
    try { await api.updatePrompt(id, form); setEditingId(null); load(); }
    finally { setSaving(false); }
  };

  const handleDelete = async (id) => {
    if (!confirm("Удалить промпт? Кампании/аккаунты перейдут на глобальный.")) return;
    await api.deletePrompt(id);
    load();
  };

  return (
    <div className="p-8 max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-zinc-100">Prompt Library</h1>
          <p className="text-sm text-zinc-500 mt-0.5">Наборы инструкций для GPT-агентов. Назначаются на аккаунт или кампанию.</p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">+ New Prompt</button>
      </div>

      {/* Global prompt note */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-4 flex gap-3 items-start">
        <span className="text-lg shrink-0">🌐</span>
        <div>
          <p className="text-sm font-medium text-zinc-300">Глобальный промпт</p>
          <p className="text-xs text-zinc-500 mt-0.5">Используется если аккаунту/кампании не назначен свой. Настраивается в <span className="text-blue-400">Settings → System Prompt</span>.</p>
        </div>
      </div>

      {prompts.length === 0 ? (
        <div className="border border-dashed border-zinc-800 rounded-2xl p-12 text-center">
          <div className="text-4xl mb-3">🧠</div>
          <p className="text-zinc-400 text-sm font-medium mb-1">Нет промптов</p>
          <p className="text-zinc-600 text-xs">Создай первый промпт и назначь его на кампанию или аккаунт</p>
        </div>
      ) : (
        <div className="space-y-3">
          {prompts.map(p => (
            <div key={p.id} className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 hover:border-zinc-700 transition-colors">
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="min-w-0">
                  <p className="font-medium text-zinc-100 text-sm">{p.name}</p>
                  {p.description && <p className="text-xs text-zinc-500 mt-0.5">{p.description}</p>}
                </div>
                <div className="flex gap-2 shrink-0">
                  <button onClick={() => setEditingId(p.id)} className="text-xs text-zinc-500 hover:text-zinc-200 transition-colors px-2 py-1">Изменить</button>
                  <button onClick={() => handleDelete(p.id)} className="text-xs text-zinc-600 hover:text-red-400 transition-colors px-2 py-1">Удалить</button>
                </div>
              </div>
              <pre className="text-[11px] text-zinc-500 bg-zinc-950 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed max-h-24 overflow-y-auto">
                {p.system_prompt}
              </pre>
            </div>
          ))}
        </div>
      )}

      {showCreate && (
        <Modal title="Новый промпт" onClose={() => setShowCreate(false)}>
          <PromptForm onSave={handleCreate} onClose={() => setShowCreate(false)} saving={saving} />
        </Modal>
      )}
      {editingId && (
        <Modal title="Редактировать промпт" onClose={() => setEditingId(null)}>
          <PromptForm
            initial={prompts.find(p => p.id === editingId)}
            onSave={(form) => handleUpdate(editingId, form)}
            onClose={() => setEditingId(null)}
            saving={saving}
          />
        </Modal>
      )}
    </div>
  );
}
