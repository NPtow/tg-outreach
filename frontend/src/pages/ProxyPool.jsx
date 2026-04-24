import { useEffect, useState } from "react";
import { api } from "../api";
import { EmptyState, PageHeader, Surface } from "../components/workspace";

const PROXY_STATE_META = {
  ok: { label: "Работает", cls: "bg-emerald-500/15 text-emerald-400" },
  timeout: { label: "Timeout", cls: "bg-orange-500/15 text-orange-400" },
  failed: { label: "Ошибка", cls: "bg-red-500/15 text-red-400" },
  auth_failed: { label: "Auth", cls: "bg-red-500/15 text-red-400" },
  unknown: { label: "Не проверен", cls: "bg-zinc-800 text-zinc-400" },
};

function fmtTs(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function proxyStateMeta(value) {
  return PROXY_STATE_META[value || "unknown"] || PROXY_STATE_META.unknown;
}

export default function ProxyPool() {
  const [proxies, setProxies] = useState([]);
  const [line, setLine] = useState("");
  const [adding, setAdding] = useState(false);
  const [testing, setTesting] = useState({});
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

  const handleTest = async (id) => {
    setTesting((s) => ({ ...s, [id]: true }));
    setError("");
    try {
      const tested = await api.testProxy(id);
      setProxies((items) => items.map((p) => p.id === id ? { ...p, ...tested } : p));
    } catch (e) {
      setError(e.message);
      load();
    } finally {
      setTesting((s) => ({ ...s, [id]: false }));
    }
  };

  const workingCount = proxies.filter((p) => p.proxy_state === "ok").length;
  const badCount = proxies.filter((p) => ["timeout", "failed", "auth_failed"].includes(p.proxy_state)).length;
  const unknownCount = proxies.filter((p) => !p.proxy_state || p.proxy_state === "unknown").length;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Infrastructure"
        title="Proxy Pool"
        description="Один прокси на один аккаунт. Тип определяется автоматически; можно явно указать HTTP:host:port:user:pass"
        stats={[
          { label: "Proxies", value: proxies.length, tone: proxies.length ? "blue" : "neutral", caption: "In pool" },
          { label: "Working", value: workingCount, tone: workingCount ? "emerald" : "neutral", caption: "Tested ok" },
          { label: "Broken", value: badCount, tone: badCount ? "amber" : "neutral", caption: "Timeout or failed" },
          { label: "Untested", value: unknownCount, tone: "neutral", caption: "Needs check" },
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
                  <span className={`text-xs px-2 py-0.5 rounded-full ${proxyStateMeta(p.proxy_state).cls}`}>
                    {proxyStateMeta(p.proxy_state).label}
                  </span>
                  {p.username && <span className="text-xs text-zinc-500 font-mono">{p.username}</span>}
                  {p.has_password && <span className="text-xs text-zinc-600">🔐</span>}
                </div>
                {p.label && <p className="text-xs text-zinc-500 mt-0.5">{p.label}</p>}
                <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-zinc-600 mt-1">
                  <span>Last check: <span className="text-zinc-400">{fmtTs(p.last_proxy_check_at)}</span></span>
                  <span>RTT: <span className="text-zinc-400">{p.proxy_last_rtt_ms ? `${p.proxy_last_rtt_ms} ms` : "—"}</span></span>
                  {p.last_error_message && <span className="text-orange-300 truncate max-w-[520px]" title={p.last_error_message}>{p.last_error_message}</span>}
                </div>
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
              <button onClick={() => handleTest(p.id)} disabled={testing[p.id]}
                className="text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50 shrink-0">
                {testing[p.id] ? "Тест..." : "Test"}
              </button>
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
