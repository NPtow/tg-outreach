import { useEffect, useState } from "react";
import { api } from "../api";
import { EmptyState, PageHeader, Surface } from "../components/workspace";

export default function ProxyPool() {
  const [proxies, setProxies] = useState([]);
  const [line, setLine] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");

  const load = () => api.getProxies().then(setProxies);
  useEffect(() => { load(); }, []);

  const handleAdd = async () => {
    if (!line.trim()) return;
    setAdding(true); setError("");
    try {
      await api.addProxy(line.trim());
      setLine("");
      load();
    } catch (e) { setError(e.message); }
    finally { setAdding(false); }
  };

  const handleDelete = async (id) => {
    if (!confirm("Удалить прокси?")) return;
    await api.deleteProxy(id);
    load();
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Infrastructure"
        title="Proxy Pool"
        description="Один прокси на один аккаунт. Тип определяется автоматически; можно явно указать HTTP:host:port:user:pass"
        stats={[
          { label: "Proxies", value: proxies.length, tone: proxies.length ? "blue" : "neutral", caption: "In pool" },
          { label: "In use", value: proxies.filter(p => p.used_by).length, tone: "neutral", caption: "Assigned to accounts" },
          { label: "Free", value: proxies.filter(p => !p.used_by).length, tone: proxies.filter(p => !p.used_by).length ? "emerald" : "neutral", caption: "Available" },
        ]}
      />

      {/* Add proxy */}
      <Surface className="p-5">
        <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">Добавить прокси</p>
        <div className="flex gap-2">
          <input
            className="flex-1 bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500 font-mono"
            placeholder="82.39.223.11:18184:user:pass  или  HTTP:82.39.223.11:18184:user:pass"
            value={line}
            onChange={e => setLine(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleAdd()}
          />
          <button onClick={handleAdd} disabled={adding || !line.trim()} className="btn-primary shrink-0">
            {adding ? "Добавляю..." : "+ Добавить"}
          </button>
        </div>
        {error && <p className="text-red-400 text-xs mt-2">{error}</p>}
        <p className="text-[11px] text-zinc-600 mt-2">
          Форматы: <span className="font-mono text-zinc-500">host:port</span>, <span className="font-mono text-zinc-500">host:port:user:pass</span> или <span className="font-mono text-zinc-500">HTTP:host:port:user:pass</span>
        </p>
      </Surface>

      {proxies.length === 0 ? (
        <EmptyState icon="🔌" title="Прокси пока нет" description="Добавь первый прокси в формате host:port:user:pass" />
      ) : (
        <div className="space-y-2">
          {proxies.map(p => (
            <Surface key={p.id} className="px-5 py-3 flex items-center gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-zinc-100">{p.host}:{p.port}</span>
                  <span className="text-xs bg-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded font-mono">{p.proxy_type || "AUTO"}</span>
                  {p.username && <span className="text-xs text-zinc-500 font-mono">{p.username}</span>}
                  {p.has_password && <span className="text-xs text-zinc-600">🔐</span>}
                </div>
                {p.label && <p className="text-xs text-zinc-500 mt-0.5">{p.label}</p>}
              </div>
              <div className="shrink-0">
                {p.used_by ? (
                  <span className="text-xs bg-blue-500/15 text-blue-400 px-2 py-0.5 rounded-full">
                    {p.used_by}
                  </span>
                ) : (
                  <span className="text-xs bg-emerald-500/15 text-emerald-400 px-2 py-0.5 rounded-full">
                    Свободен
                  </span>
                )}
              </div>
              <button onClick={() => handleDelete(p.id)}
                className="text-xs text-zinc-600 hover:text-red-400 transition-colors shrink-0 px-2 py-1">
                Удалить
              </button>
            </Surface>
          ))}
        </div>
      )}
    </div>
  );
}
