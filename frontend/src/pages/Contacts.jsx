import { useEffect, useState, useRef } from "react";
import { api } from "../api";
import { PageHeader } from "../components/workspace";

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
  const [batchName, setBatchName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const fileRef = useRef();

  const handleFile = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (!batchName) setBatchName(file.name.replace(/\.[^.]+$/, ""));
    const reader = new FileReader();
    reader.onload = ev => setCsvText(ev.target.result);
    reader.readAsText(file, "UTF-8");
  };

  const handleImport = async () => {
    if (!csvText.trim()) { setError("Вставь CSV или загрузи файл"); return; }
    setLoading(true); setError(""); setResult(null);
    try {
      const r = await api.importContacts(csvText, batchName);
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
          <label className="text-xs font-medium text-zinc-400 block mb-1">Название батча</label>
          <input
            className="w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500 transition-colors"
            placeholder="Например: ProductConf 2024"
            value={batchName}
            onChange={e => setBatchName(e.target.value)}
          />
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
            <p className="text-sm text-emerald-400 font-medium">Импортировано: {result.added} контактов в батч «{result.batch_name}»</p>
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

// ── Batch list view ──────────────────────────────────────────────────────────

function BatchList({ onDrillDown, onRefresh }) {
  const [batches, setBatches] = useState([]);

  const load = () => api.getContactBatches().then(setBatches);
  useEffect(() => { load(); }, []);

  // expose refresh
  useEffect(() => { onRefresh(load); }, []);

  const handleDelete = async (id, name) => {
    if (!confirm(`Удалить батч «${name}» и все его контакты?`)) return;
    await api.deleteContactBatch(id);
    load();
  };

  if (batches.length === 0) {
    return (
      <div className="border border-dashed border-zinc-800 rounded-2xl p-12 text-center">
        <div className="text-4xl mb-3">📦</div>
        <p className="text-zinc-400 text-sm font-medium mb-1">Нет батчей контактов</p>
        <p className="text-zinc-600 text-xs">Импортируй CSV или добавь контакты вручную</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {batches.map(b => (
        <div key={b.id} className="bg-zinc-900 border border-zinc-800 rounded-xl px-5 py-4 flex items-center gap-4 hover:border-zinc-700 transition-colors">
          <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 font-bold text-sm shrink-0">
            {b.count}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-zinc-100 truncate">{b.name}</p>
            <p className="text-xs text-zinc-500 mt-0.5">
              {b.count} контактов · {new Date(b.created_at).toLocaleDateString("ru-RU")}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => onDrillDown(b)}
              className="text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-3 py-1.5 rounded-lg transition-colors"
            >
              Открыть →
            </button>
            <button
              onClick={() => handleDelete(b.id, b.name)}
              className="text-zinc-600 hover:text-red-400 transition-colors text-sm px-1"
            >×</button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Contact table (inside a batch) ──────────────────────────────────────────

function ContactTable({ batchId, onBack, onBatchDeleted }) {
  const [contacts, setContacts] = useState([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(new Set());

  const load = (q = search) => api.getContacts(q, batchId).then(setContacts);
  useEffect(() => { load(); }, [batchId]);

  const handleSearch = v => { setSearch(v); load(v); };

  const toggleSelect = id => setSelected(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

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

  const handleDelete = async id => {
    await api.deleteContact(id);
    setSelected(prev => { const n = new Set(prev); n.delete(id); return n; });
    load();
  };

  return (
    <div>
      <div className="flex items-center gap-3 mb-5">
        <button onClick={onBack} className="btn-ghost text-sm">← Назад</button>
        {selected.size > 0 && (
          <button onClick={handleBulkDelete}
            className="text-sm bg-red-600/20 hover:bg-red-600/30 text-red-400 px-3 py-1.5 rounded-lg font-medium transition-colors border border-red-500/20">
            Удалить ({selected.size})
          </button>
        )}
      </div>

      <div className="mb-4">
        <input
          className="w-full bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-600 transition-colors"
          placeholder="Поиск по username, имени, компании..."
          value={search}
          onChange={e => handleSearch(e.target.value)}
        />
      </div>

      {contacts.length === 0 ? (
        <div className="border border-dashed border-zinc-800 rounded-2xl p-10 text-center">
          <p className="text-zinc-500 text-sm">Нет контактов</p>
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
          <div className="grid grid-cols-[2rem_1fr_1fr_1fr_1fr_2.5rem] gap-3 px-4 py-2.5 border-b border-zinc-800 text-xs font-medium text-zinc-500">
            <div><input type="checkbox" className="accent-blue-500" checked={selected.size === contacts.length && contacts.length > 0} onChange={toggleAll} /></div>
            <div>Username</div>
            <div>Имя</div>
            <div>Компания / Роль</div>
            <div>Теги / Заметка</div>
            <div></div>
          </div>
          <div className="divide-y divide-zinc-800/50">
            {contacts.map(c => (
              <div key={c.id}
                className={`grid grid-cols-[2rem_1fr_1fr_1fr_1fr_2.5rem] gap-3 px-4 py-3 items-center hover:bg-zinc-800/30 transition-colors ${selected.has(c.id) ? "bg-zinc-800/20" : ""}`}>
                <div><input type="checkbox" className="accent-blue-500" checked={selected.has(c.id)} onChange={() => toggleSelect(c.id)} /></div>
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
                  <button onClick={() => handleDelete(c.id)} className="text-zinc-600 hover:text-red-400 transition-colors text-sm px-1">×</button>
                </div>
              </div>
            ))}
          </div>
          <div className="px-4 py-2.5 border-t border-zinc-800 text-xs text-zinc-600">
            {contacts.length} контактов{selected.size > 0 && ` · ${selected.size} выбрано`}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function Contacts() {
  const [activeBatch, setActiveBatch] = useState(null); // null = batch list view
  const [showAdd, setShowAdd] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [refreshBatches, setRefreshBatches] = useState(null);

  const handleImported = () => {
    if (refreshBatches) refreshBatches();
  };

  const handleAdded = () => {
    setShowAdd(false);
    if (refreshBatches) refreshBatches();
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Audience"
        title="Contacts"
        description={activeBatch ? `Работа с батчем «${activeBatch.name}»: поиск, ручное редактирование и очистка отдельных записей.` : "База контактов, сгруппированная по импортам и готовая к campaigns и ручной работе."}
        actions={(
          <>
            <button onClick={() => setShowImport(true)} className="btn-ghost text-sm">Импорт CSV</button>
            <button onClick={() => setShowAdd(true)} className="btn-primary">+ Добавить</button>
          </>
        )}
      />

      {activeBatch ? (
        <ContactTable
          batchId={activeBatch.id}
          onBack={() => setActiveBatch(null)}
          onBatchDeleted={() => { setActiveBatch(null); if (refreshBatches) refreshBatches(); }}
        />
      ) : (
        <BatchList
          onDrillDown={setActiveBatch}
          onRefresh={fn => setRefreshBatches(() => fn)}
        />
      )}

      {showAdd && <AddModal onClose={() => setShowAdd(false)} onAdded={handleAdded} />}
      {showImport && <ImportModal onClose={() => setShowImport(false)} onImported={handleImported} />}
    </div>
  );
}
