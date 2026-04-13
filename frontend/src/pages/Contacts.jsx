import { useEffect, useState, useRef } from "react";
import { api } from "../api";

const CSV_FORMAT = `Формат CSV-файла (одна строка = один контакт):

username[,имя[,компания[,роль[,заметка[,теги]]]]]

Примеры:
john_doe
jane_smith,Джейн
bob_cto,Боб,OpenAI,CTO
alice,Алиса,Microsoft,PM,встретились на ProductConf,target`;

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

function AddModal({ onClose, onAdded }) {
  const [form, setForm] = useState({ username: "", display_name: "", company: "", role: "", custom_note: "", tags: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const inp = "w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500 transition-colors";

  const handleSubmit = async () => {
    if (!form.username.trim()) { setError("Username обязателен"); return; }
    setLoading(true); setError("");
    try {
      await api.createContact(form);
      onAdded();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <Modal title="Добавить контакт" onClose={onClose}>
      <div className="space-y-3">
        {[
          { k: "username", label: "Username *", ph: "john_doe" },
          { k: "display_name", label: "Имя", ph: "Иван" },
          { k: "company", label: "Компания", ph: "OpenAI" },
          { k: "role", label: "Роль", ph: "CTO" },
          { k: "custom_note", label: "Заметка", ph: "Встретились на ProductConf" },
          { k: "tags", label: "Теги", ph: "target,warm" },
        ].map(({ k, label, ph }) => (
          <div key={k}>
            <label className="text-xs font-medium text-zinc-400 block mb-1">{label}</label>
            <input className={inp} placeholder={ph} value={form[k]} onChange={e => setForm({ ...form, [k]: e.target.value })} />
          </div>
        ))}
      </div>
      {error && <p className="text-red-400 text-xs mt-3 bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>}
      <div className="flex gap-2 mt-4">
        <button onClick={handleSubmit} disabled={loading} className="btn-primary">{loading ? "Добавляю..." : "Добавить"}</button>
        <button onClick={onClose} className="btn-ghost">Отмена</button>
      </div>
    </Modal>
  );
}

function ImportModal({ onClose, onImported }) {
  const [csvText, setCsvText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const fileRef = useRef();

  const handleFile = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => setCsvText(ev.target.result);
    reader.readAsText(file, "UTF-8");
  };

  const handleImport = async () => {
    if (!csvText.trim()) { setError("Вставь CSV или загрузи файл"); return; }
    setLoading(true); setError(""); setResult(null);
    try {
      const r = await api.importContacts(csvText);
      setResult(r);
      onImported();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <Modal title="Импорт контактов" onClose={onClose}>
      <div className="space-y-4">
        <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-700/50">
          <p className="text-[11px] text-zinc-400 font-mono whitespace-pre-line leading-relaxed">{CSV_FORMAT}</p>
        </div>

        <div>
          <label className="text-xs font-medium text-zinc-400 block mb-1.5">Загрузить файл (.csv или .txt)</label>
          <input ref={fileRef} type="file" accept=".csv,.txt" onChange={handleFile} className="hidden" />
          <button onClick={() => fileRef.current.click()}
            className="w-full border border-dashed border-zinc-700 hover:border-zinc-500 rounded-lg py-3 text-sm text-zinc-400 hover:text-zinc-200 transition-colors">
            Выбрать файл
          </button>
          {csvText && (
            <p className="text-[11px] text-emerald-400 mt-1">{csvText.split("\n").filter(l => l.trim()).length} строк загружено</p>
          )}
        </div>

        <div>
          <label className="text-xs font-medium text-zinc-400 block mb-1.5">или вставить CSV текст</label>
          <textarea rows={6}
            className="w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 text-xs text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500 font-mono resize-y"
            placeholder={"john_doe\njane_smith,Джейн\nbob_cto,Боб,OpenAI,CTO"}
            value={csvText} onChange={e => setCsvText(e.target.value)} />
        </div>

        {result && (
          <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-4 py-3">
            <p className="text-sm text-emerald-400 font-medium">Импортировано: {result.added} контактов</p>
          </div>
        )}
      </div>
      {error && <p className="text-red-400 text-xs mt-3 bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>}
      <div className="flex gap-2 mt-4">
        <button onClick={handleImport} disabled={loading} className="btn-primary">{loading ? "Импортирую..." : "Импортировать"}</button>
        <button onClick={onClose} className="btn-ghost">Закрыть</button>
      </div>
    </Modal>
  );
}

export default function Contacts() {
  const [contacts, setContacts] = useState([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(new Set());
  const [showAdd, setShowAdd] = useState(false);
  const [showImport, setShowImport] = useState(false);

  const load = (q = search) => api.getContacts(q).then(setContacts);

  useEffect(() => { load(); }, []);

  const handleSearch = (v) => {
    setSearch(v);
    load(v);
  };

  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === contacts.length) setSelected(new Set());
    else setSelected(new Set(contacts.map(c => c.id)));
  };

  const handleBulkDelete = async () => {
    if (!confirm(`Удалить ${selected.size} контактов?`)) return;
    await api.bulkDeleteContacts([...selected]);
    setSelected(new Set());
    load();
  };

  const handleDelete = async (id) => {
    await api.deleteContact(id);
    setSelected(prev => { const n = new Set(prev); n.delete(id); return n; });
    load();
  };

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-zinc-100">Contacts</h1>
          <p className="text-sm text-zinc-500 mt-0.5">База контактов для кампаний</p>
        </div>
        <div className="flex gap-2">
          {selected.size > 0 && (
            <button onClick={handleBulkDelete}
              className="text-sm bg-red-600/20 hover:bg-red-600/30 text-red-400 px-3 py-1.5 rounded-lg font-medium transition-colors border border-red-500/20">
              Удалить ({selected.size})
            </button>
          )}
          <button onClick={() => setShowImport(true)} className="btn-ghost text-sm">Импорт</button>
          <button onClick={() => setShowAdd(true)} className="btn-primary">+ Добавить</button>
        </div>
      </div>

      {/* Search */}
      <div className="mb-4">
        <input
          className="w-full bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-600 transition-colors"
          placeholder="Поиск по username, имени, компании, роли..."
          value={search}
          onChange={e => handleSearch(e.target.value)}
        />
      </div>

      {contacts.length === 0 ? (
        <div className="border border-dashed border-zinc-800 rounded-2xl p-12 text-center">
          <div className="text-4xl mb-3">👥</div>
          <p className="text-zinc-400 text-sm font-medium mb-1">База контактов пуста</p>
          <p className="text-zinc-600 text-xs mb-4">Добавь контакты вручную или импортируй CSV</p>
          <button onClick={() => setShowImport(true)} className="btn-primary text-sm">Импортировать</button>
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
          {/* Header */}
          <div className="grid grid-cols-[2rem_1fr_1fr_1fr_1fr_2.5rem] gap-3 px-4 py-2.5 border-b border-zinc-800 text-xs font-medium text-zinc-500">
            <div>
              <input type="checkbox" className="accent-blue-500"
                checked={selected.size === contacts.length && contacts.length > 0}
                onChange={toggleAll} />
            </div>
            <div>Username</div>
            <div>Имя</div>
            <div>Компания / Роль</div>
            <div>Теги / Заметка</div>
            <div></div>
          </div>
          {/* Rows */}
          <div className="divide-y divide-zinc-800/50">
            {contacts.map(c => (
              <div key={c.id}
                className={`grid grid-cols-[2rem_1fr_1fr_1fr_1fr_2.5rem] gap-3 px-4 py-3 items-center hover:bg-zinc-800/30 transition-colors ${selected.has(c.id) ? "bg-zinc-800/20" : ""}`}>
                <div>
                  <input type="checkbox" className="accent-blue-500"
                    checked={selected.has(c.id)}
                    onChange={() => toggleSelect(c.id)} />
                </div>
                <div className="text-sm text-blue-400 font-mono truncate">@{c.username}</div>
                <div className="text-sm text-zinc-200 truncate">{c.display_name || <span className="text-zinc-600">—</span>}</div>
                <div className="text-xs text-zinc-400 truncate">
                  {c.company && <span>{c.company}</span>}
                  {c.company && c.role && <span className="text-zinc-600"> · </span>}
                  {c.role && <span className="text-zinc-500">{c.role}</span>}
                  {!c.company && !c.role && <span className="text-zinc-600">—</span>}
                </div>
                <div className="text-xs truncate">
                  {c.tags && c.tags.split(",").map(t => t.trim()).filter(Boolean).map(t => (
                    <span key={t} className="inline-block bg-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded-full mr-1 mb-0.5">{t}</span>
                  ))}
                  {!c.tags && c.custom_note && <span className="text-zinc-500 truncate">{c.custom_note}</span>}
                  {!c.tags && !c.custom_note && <span className="text-zinc-600">—</span>}
                </div>
                <div>
                  <button onClick={() => handleDelete(c.id)}
                    className="text-zinc-600 hover:text-red-400 transition-colors text-sm px-1">×</button>
                </div>
              </div>
            ))}
          </div>
          <div className="px-4 py-2.5 border-t border-zinc-800 text-xs text-zinc-600">
            {contacts.length} контактов{selected.size > 0 && ` · ${selected.size} выбрано`}
          </div>
        </div>
      )}

      {showAdd && <AddModal onClose={() => setShowAdd(false)} onAdded={() => { setShowAdd(false); load(); }} />}
      {showImport && <ImportModal onClose={() => setShowImport(false)} onImported={() => load()} />}
    </div>
  );
}
