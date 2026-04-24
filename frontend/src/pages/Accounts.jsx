import { useEffect, useState } from "react";
import { api } from "../api";
import { EmptyState, PageHeader, Surface } from "../components/workspace";
import { useWsEvent } from "../ws";

const STEPS = { FORM: "form", CODE: "code", DONE: "done" };

const STATE_META = {
  online: { label: "Connected", cls: "bg-emerald-500/10 text-emerald-400" },
  connecting: { label: "Connecting", cls: "bg-blue-500/10 text-blue-400" },
  offline: { label: "Offline", cls: "bg-zinc-800 text-zinc-400" },
  degraded: { label: "Degraded", cls: "bg-orange-500/10 text-orange-400" },
  reauth_required: { label: "Needs reauth", cls: "bg-amber-500/10 text-amber-400" },
  ok: { label: "Proxy ok", cls: "bg-emerald-500/10 text-emerald-400" },
  failed: { label: "Proxy failed", cls: "bg-red-500/10 text-red-400" },
  timeout: { label: "Proxy timeout", cls: "bg-orange-500/10 text-orange-400" },
  auth_failed: { label: "Proxy auth", cls: "bg-red-500/10 text-red-400" },
  valid: { label: "Session valid", cls: "bg-emerald-500/10 text-emerald-400" },
  expired: { label: "Session expired", cls: "bg-amber-500/10 text-amber-400" },
  recovering: { label: "Recovering", cls: "bg-blue-500/10 text-blue-400" },
  recovery_failed: { label: "Recovery failed", cls: "bg-red-500/10 text-red-400" },
  missing: { label: "No session", cls: "bg-zinc-800 text-zinc-400" },
  eligible: { label: "Ready for campaigns", cls: "bg-emerald-500/10 text-emerald-400" },
  blocked_proxy: { label: "Blocked by proxy", cls: "bg-red-500/10 text-red-400" },
  blocked_auth: { label: "Blocked by auth", cls: "bg-amber-500/10 text-amber-400" },
  blocked_resolution: { label: "Blocked by resolve", cls: "bg-orange-500/10 text-orange-400" },
};

function fmtTs(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function badgeFor(key) {
  return STATE_META[key] || { label: key || "unknown", cls: "bg-zinc-800 text-zinc-400" };
}

function Field({ label, children }) {
  return (
    <div>
      <label className="text-xs font-medium text-zinc-400 block mb-1.5">{label}</label>
      {children}
    </div>
  );
}

function Input(props) {
  return <input className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500 transition-colors" {...props} />;
}

function Modal({ title, onClose, children, wide = false }) {
  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className={`bg-zinc-900 rounded-2xl w-full ${wide ? "max-w-2xl" : "max-w-md"} border border-zinc-700/50 shadow-2xl max-h-[90vh] overflow-y-auto`}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
          <h2 className="text-base font-semibold text-zinc-100">{title}</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200 text-xl leading-none w-7 h-7 flex items-center justify-center rounded-lg hover:bg-zinc-800 transition-colors">×</button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

function ProxyFields({ form, setForm }) {
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  return (
    <div className="border-t border-zinc-800 pt-3 space-y-3">
      <p className="text-xs font-medium text-zinc-500">Proxy</p>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Host">
          <Input placeholder="102.129.221.128" value={form.proxy_host} onChange={(e) => set("proxy_host", e.target.value)} />
        </Field>
        <Field label="Port">
          <Input placeholder="1080" value={form.proxy_port} onChange={(e) => set("proxy_port", e.target.value)} />
        </Field>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Field label="Type">
          <select className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-blue-500"
            value={form.proxy_type} onChange={(e) => set("proxy_type", e.target.value)}>
            <option value="SOCKS5">SOCKS5</option>
            <option value="SOCKS4">SOCKS4</option>
            <option value="HTTP">HTTP</option>
          </select>
        </Field>
        <Field label="User">
          <Input placeholder="user" value={form.proxy_user} onChange={(e) => set("proxy_user", e.target.value)} />
        </Field>
        <Field label="Password">
          <Input type="password" placeholder="••••••" value={form.proxy_pass} onChange={(e) => set("proxy_pass", e.target.value)} />
        </Field>
      </div>
      <p className="text-[11px] text-zinc-600">По умолчанию рекомендуем стабильный SOCKS5 на один аккаунт.</p>
    </div>
  );
}

function proxyMatchesAccount(proxy, account) {
  return (
    proxy.host === account.proxy_host &&
    Number(proxy.port) === Number(account.proxy_port) &&
    (proxy.username || "") === (account.proxy_user || "")
  );
}

function proxyLabel(proxy) {
  const used = proxy.used_by ? ` — занят: ${proxy.used_by}` : "";
  const health = proxy.proxy_state === "ok" ? "работает" : proxy.proxy_state || "не проверен";
  return `${proxy.proxy_type || "AUTO"} ${proxy.host}:${proxy.port}${proxy.username ? ` (${proxy.username})` : ""} · ${health}${used}`;
}

function AddAccountModal({ onClose, onAdded }) {
  const [step, setStep] = useState(STEPS.FORM);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [proxyId, setProxyId] = useState("");
  const [proxies, setProxies] = useState([]);
  const [accountId, setAccountId] = useState(null);
  const [phoneCodeHash, setPhoneCodeHash] = useState("");
  const [partialSession, setPartialSession] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => { api.getProxies().then(setProxies); }, []);

  const handleCreate = async () => {
    setError(""); setLoading(true);
    try {
      const selectedProxy = proxies.find(p => String(p.id) === String(proxyId));
      const payload = {
        name, phone,
        ...(selectedProxy ? {
          proxy_id: selectedProxy.id,
        } : {}),
      };
      const acc = await api.createAccount(payload);
      setAccountId(acc.id);
      const result = await api.sendCode(acc.id);
      if (result.ok) {
        setPhoneCodeHash(result.phone_code_hash);
        setPartialSession(result.partial_session || "");
        setStep(STEPS.CODE);
      } else {
        // Clean up zombie account so user can retry with the same phone
        try { await api.deleteAccount(acc.id); } catch (_) {}
        setAccountId(null);
        setError(result.error || "Ошибка отправки кода");
      }
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const handleVerify = async () => {
    setError(""); setLoading(true);
    try {
      const result = await api.verifyCode({ account_id: accountId, phone_code_hash: phoneCodeHash, code, password, partial_session: partialSession || undefined });
      if (result.ok) { setStep(STEPS.DONE); onAdded(); }
      else setError(result.error || "Неверный код");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <Modal title={step === STEPS.DONE ? "Готово!" : step === STEPS.CODE ? "Введи код из Telegram" : "Добавить аккаунт"} onClose={onClose}>
      {step === STEPS.FORM && (
        <div className="space-y-4">
          <Field label="Название">
            <Input placeholder="Kenny" value={name} onChange={e => setName(e.target.value)} />
          </Field>
          <Field label="Номер телефона">
            <Input placeholder="+573126523653" value={phone} onChange={e => setPhone(e.target.value)} />
          </Field>
          <Field label="Прокси">
            <select
              className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-blue-500"
              value={proxyId} onChange={e => setProxyId(e.target.value)}>
              <option value="">— без прокси —</option>
              {proxies.map(p => (
                <option key={p.id} value={p.id}>
                  {p.proxy_type || "AUTO"} {p.host}:{p.port}{p.username ? ` (${p.username})` : ""}{p.used_by ? ` — занят: ${p.used_by}` : ""}
                </option>
              ))}
            </select>
            {proxies.length === 0 && (
              <p className="text-[11px] text-zinc-600 mt-1">Нет прокси в пуле — добавь на странице <span className="text-blue-400">Proxies</span></p>
            )}
          </Field>
        </div>
      )}
      {step === STEPS.CODE && (
        <div className="space-y-4">
          <p className="text-sm text-zinc-400">Код отправлен на <span className="text-zinc-200 font-medium">{phone}</span></p>
          <Field label="Код из Telegram"><Input placeholder="12345" value={code} onChange={e => setCode(e.target.value)} autoFocus /></Field>
          <Field label="2FA пароль (если есть)"><Input type="password" placeholder="••••••" value={password} onChange={e => setPassword(e.target.value)} /></Field>
        </div>
      )}
      {step === STEPS.DONE && (
        <div className="text-center py-4">
          <div className="text-4xl mb-3">✅</div>
          <p className="text-zinc-300 text-sm">Аккаунт подключён, сессия сохранена</p>
        </div>
      )}
      {error && <p className="text-red-400 text-xs mt-3 bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>}
      <div className="flex gap-2 mt-5">
        {step === STEPS.FORM && <button onClick={handleCreate} disabled={loading || !name || !phone} className="btn-primary">{loading ? "Отправляю..." : "Отправить код"}</button>}
        {step === STEPS.CODE && <button onClick={handleVerify} disabled={loading || !code} className="btn-primary">{loading ? "Проверяю..." : "Подтвердить"}</button>}
        <button onClick={onClose} className="btn-ghost">{step === STEPS.DONE ? "Закрыть" : "Отмена"}</button>
      </div>
    </Modal>
  );
}

function EditAccountModal({ account, proxies, onClose, onSaved }) {
  const currentProxy = proxies.find((p) => proxyMatchesAccount(p, account));
  const currentProxyIsSelectable = Boolean(currentProxy?.proxy_state === "ok" && (!currentProxy.used_by_account_id || currentProxy.used_by_account_id === account.id));
  const [proxyChoice, setProxyChoice] = useState(currentProxyIsSelectable ? String(currentProxy.id) : (account.proxy_host ? "__current__" : "__none__"));
  const [form, setForm] = useState({
    name: account.name || "",
    phone: account.phone || "",
    app_id: account.app_id || "",
    app_hash: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const selectableProxies = proxies.filter((p) => (
    p.proxy_state === "ok" &&
    (!p.used_by_account_id || p.used_by_account_id === account.id)
  ));

  const handleSave = async () => {
    setLoading(true); setError("");
    try {
      const payload = { ...form };
      if (proxyChoice === "__none__") {
        payload.clear_proxy = true;
      } else if (proxyChoice === "__current__") {
        // Keep legacy/manual proxy unchanged.
      } else {
        payload.proxy_id = Number(proxyChoice);
      }
      await api.updateAccount(account.id, payload);
      onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal title="Редактировать аккаунт" onClose={onClose} wide>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <Field label="Название"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Номер телефона"><Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
          <Field label="App ID"><Input value={form.app_id} onChange={(e) => setForm({ ...form, app_id: e.target.value })} /></Field>
          <Field label="Новый App Hash"><Input placeholder="Оставь пустым чтобы не менять" value={form.app_hash} onChange={(e) => setForm({ ...form, app_hash: e.target.value })} /></Field>
        </div>
        <div className="border-t border-zinc-800 pt-3 space-y-3">
          <p className="text-xs font-medium text-zinc-500">Proxy</p>
          <Field label="Выбрать рабочий прокси из пула">
            <select
              className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-blue-500"
              value={proxyChoice}
              onChange={(e) => setProxyChoice(e.target.value)}
            >
              <option value="__none__">— без прокси —</option>
              {account.proxy_host && !currentProxyIsSelectable && (
                <option value="__current__">
                  текущий: {account.proxy_type || "AUTO"} {account.proxy_host}:{account.proxy_port}{account.proxy_user ? ` (${account.proxy_user})` : ""} — оставить как есть
                </option>
              )}
              {selectableProxies.map((p) => (
                <option key={p.id} value={p.id}>{proxyLabel(p)}</option>
              ))}
            </select>
            <p className="text-[11px] text-zinc-600 mt-1">
              Показываются только прокси со статусом “работает” и без другого аккаунта. Проверь прокси на вкладке Proxies, если его нет в списке.
            </p>
          </Field>
          {account.proxy_host && (
            <p className="text-[11px] text-zinc-500 bg-zinc-950/60 border border-zinc-800 rounded-lg px-3 py-2">
              Текущий прокси аккаунта: <span className="font-mono text-zinc-300">{account.proxy_type || "AUTO"} {account.proxy_host}:{account.proxy_port}</span>
              {account.proxy_state && <span className="ml-2 text-zinc-400">status: {badgeFor(account.proxy_state).label}</span>}
            </p>
          )}
        </div>
      </div>
      {error && <p className="text-red-400 text-xs mt-3 bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>}
      <div className="flex gap-2 mt-5">
        <button onClick={handleSave} disabled={loading} className="btn-primary">{loading ? "Сохраняю..." : "Сохранить"}</button>
        <button onClick={onClose} className="btn-ghost">Отмена</button>
      </div>
    </Modal>
  );
}

function ImportTdataModal({ onClose, onAdded }) {
  const [form, setForm] = useState({ name: "", phone: "", proxy_host: "", proxy_port: "", proxy_type: "SOCKS5", proxy_user: "", proxy_pass: "" });
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const handleSubmit = async () => {
    if (!file) { setError("Выбери zip-файл с tdata"); return; }
    setError(""); setLoading(true);
    try {
      const fd = new FormData();
      Object.entries(form).forEach(([k, v]) => fd.append(k, v));
      fd.append("tdata_zip", file);
      await api.importTdata(fd);
      setDone(true); onAdded();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <Modal title="Импорт tdata" onClose={onClose} wide>
      {done ? (
        <div className="text-center py-4">
          <div className="text-4xl mb-3">✅</div>
          <p className="text-zinc-300 text-sm">Аккаунт импортирован и поставлен под автоподдержку</p>
        </div>
      ) : (
        <div className="space-y-3">
          <Field label="Название"><Input placeholder="USA Account #1" value={form.name} onChange={(e) => set("name", e.target.value)} /></Field>
          <Field label="Номер телефона"><Input placeholder="+14508507294" value={form.phone} onChange={(e) => set("phone", e.target.value)} /></Field>
          <div>
            <label className="text-xs font-medium text-zinc-400 block mb-1.5">Zip-файл с tdata</label>
            <input type="file" accept=".zip" className="w-full text-sm text-zinc-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-zinc-800 file:text-zinc-300 file:hover:bg-zinc-700 file:transition-colors"
              onChange={(e) => setFile(e.target.files[0])} />
          </div>
          <ProxyFields form={form} setForm={setForm} />
        </div>
      )}
      {error && <p className="text-red-400 text-xs mt-3 bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>}
      <div className="flex gap-2 mt-5">
        {!done && <button onClick={handleSubmit} disabled={loading} className="btn-primary">{loading ? "Импортирую..." : "Импортировать"}</button>}
        <button onClick={onClose} className="btn-ghost">{done ? "Закрыть" : "Отмена"}</button>
      </div>
    </Modal>
  );
}

function ReauthModal({ account, onClose, onDone }) {
  const [phoneCodeHash, setPhoneCodeHash] = useState("");
  const [partialSession, setPartialSession] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSendCode = async () => {
    setError(""); setLoading(true);
    try {
      const result = await api.sendCode(account.id);
      if (result.ok) {
        setPhoneCodeHash(result.phone_code_hash);
        setPartialSession(result.partial_session || "");
      } else setError(result.error || "Ошибка отправки кода");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const handleVerify = async () => {
    setError(""); setLoading(true);
    try {
      const result = await api.verifyCode({ account_id: account.id, phone_code_hash: phoneCodeHash, code, password, partial_session: partialSession || undefined });
      if (result.ok) onDone();
      else setError(result.error || "Неверный код");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <Modal title="Повторная авторизация" onClose={onClose}>
      <div className="space-y-3">
        <p className="text-xs text-zinc-400 bg-zinc-800/50 rounded-lg px-3 py-2">
          Аккаунт <span className="text-zinc-200 font-medium">{account.name}</span> требует повторной авторизации.
        </p>
        {!phoneCodeHash ? (
          <p className="text-sm text-zinc-400">Нажми кнопку ниже — код придёт в Telegram</p>
        ) : (
          <>
            <Field label="Код из Telegram"><Input placeholder="12345" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
            <Field label="2FA пароль"><Input type="password" placeholder="••••••" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          </>
        )}
        {error && <p className="text-red-400 text-xs bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>}
        <div className="flex gap-2 mt-4">
          {!phoneCodeHash
            ? <button onClick={handleSendCode} disabled={loading} className="btn-primary">{loading ? "Отправляю..." : "Отправить код"}</button>
            : <button onClick={handleVerify} disabled={loading} className="btn-primary">{loading ? "Проверяю..." : "Подтвердить"}</button>}
          <button onClick={onClose} className="btn-ghost">Отмена</button>
        </div>
      </div>
    </Modal>
  );
}

function HealthBadge({ value }) {
  const meta = badgeFor(value);
  return <span className={`text-[11px] px-2 py-1 rounded-full font-medium ${meta.cls}`}>{meta.label}</span>;
}

export default function Accounts() {
  const [accounts, setAccounts] = useState([]);
  const [prompts, setPrompts] = useState([]);
  const [proxies, setProxies] = useState([]);
  const [runtime, setRuntime] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [showTdata, setShowTdata] = useState(false);
  const [editAccount, setEditAccount] = useState(null);
  const [reauthAccount, setReauthAccount] = useState(null);
  const [reconnecting, setReconnecting] = useState({});
  const [reconnectError, setReconnectError] = useState({});
  const [proxyTesting, setProxyTesting] = useState({});

  const load = () => Promise.all([
    api.getAccounts().then(setAccounts),
    api.getPrompts().then(setPrompts),
    api.getProxies().then(setProxies),
    api.getRuntimeStatus().then(setRuntime).catch(() => setRuntime({ ok: false, owns_runtime: false })),
  ]);

  useEffect(() => { load(); }, []);
  useWsEvent((event) => {
    if (event.event === "account_health") load();
  });

  const handleSetPrompt = async (accId, promptId) => {
    await api.setPrompt(accId, promptId ? Number(promptId) : null);
    load();
  };

  const handleReconnect = async (accId) => {
    setReconnecting((r) => ({ ...r, [accId]: true }));
    setReconnectError((e) => ({ ...e, [accId]: null }));
    try {
      await api.reconnectAccount(accId);
      load();
    } catch (e) {
      setReconnectError((r) => ({ ...r, [accId]: e.message }));
      load();
    } finally {
      setReconnecting((r) => ({ ...r, [accId]: false }));
    }
  };

  const handleProxyTest = async (accId) => {
    setProxyTesting((s) => ({ ...s, [accId]: true }));
    try {
      await api.proxyTestAccount(accId);
      load();
    } finally {
      setProxyTesting((s) => ({ ...s, [accId]: false }));
    }
  };

  const readyCount = accounts.filter((account) => account.eligibility_state === "eligible").length;
  const needsReauthCount = accounts.filter((account) => account.needs_reauth).length;
  const onlineCount = accounts.filter((account) => account.connection_state === "online").length;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Runtime"
        title="Accounts"
        description="Health-aware control plane for Telegram sessions, proxies, reauth, and safe campaign readiness."
        actions={(
          <>
            <button onClick={() => setShowTdata(true)} className="btn-secondary">+ Import tdata</button>
            <button onClick={() => setShowModal(true)} className="btn-primary">+ Add Account</button>
          </>
        )}
        stats={[
          { label: "Accounts", value: accounts.length, tone: "neutral", caption: "Configured identities" },
          { label: "Campaign ready", value: readyCount, tone: readyCount ? "emerald" : "neutral", caption: "Eligible to launch" },
          { label: "Live now", value: onlineCount, tone: onlineCount ? "blue" : "neutral", caption: "Connected workers" },
          { label: "Needs reauth", value: needsReauthCount, tone: needsReauthCount ? "amber" : "neutral", caption: "Manual recovery queue" },
        ]}
      />

      <Surface className={`px-5 py-4 text-sm ${runtime?.ok ? "border-emerald-400/15 bg-[linear-gradient(180deg,rgba(14,30,27,0.96),rgba(10,15,17,0.94))] text-emerald-200" : "border-rose-400/15 bg-[linear-gradient(180deg,rgba(44,16,24,0.96),rgba(12,10,14,0.94))] text-rose-200"}`}>
        {runtime?.ok
          ? `Telegram worker online · role: ${runtime.role}`
          : "Telegram worker unreachable. Reconnect/start commands будут недоступны."}
      </Surface>

      {accounts.length === 0 ? (
        <EmptyState icon="👤" title="No Telegram accounts yet" description="Добавьте первый аккаунт или импортируйте tdata, чтобы включить campaigns и inbox monitoring." />
      ) : (
        <div className="space-y-3">
          {accounts.map((acc) => {
            const assignedPrompt = prompts.find((p) => p.id === acc.prompt_template_id);
            return (
              <Surface key={acc.id} className="px-5 py-4 transition-colors hover:border-white/16">
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-3 flex-1 min-w-0">
                    <div className="flex items-center gap-3">
                      <div className={`w-2 h-2 rounded-full shrink-0 ${acc.connection_state === "online" ? "bg-emerald-500" : "bg-zinc-600"}`} />
                      <div>
                        <p className="text-sm font-medium text-zinc-100">{acc.name}</p>
                        <p className="text-xs text-zinc-500">
                          {acc.phone}
                          {acc.tdata_stored && <span className="ml-1.5 text-[10px] text-emerald-400/70">tdata ✓</span>}
                          {acc.proxy_host && <span className="ml-1.5 text-[10px] text-blue-400/70">{acc.proxy_type} {acc.proxy_host}:{acc.proxy_port}</span>}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <HealthBadge value={acc.connection_state} />
                      <HealthBadge value={acc.proxy_state} />
                      <HealthBadge value={acc.session_state} />
                      <HealthBadge value={acc.eligibility_state} />
                    </div>

                    <div className="grid grid-cols-2 gap-3 text-[11px] text-zinc-500">
                      <div>Last connect: <span className="text-zinc-300">{fmtTs(acc.last_connect_at)}</span></div>
                      <div>Last proxy check: <span className="text-zinc-300">{fmtTs(acc.last_proxy_check_at)}</span></div>
                      <div>Last seen online: <span className="text-zinc-300">{fmtTs(acc.last_seen_online_at)}</span></div>
                      <div>Proxy RTT: <span className="text-zinc-300">{acc.proxy_last_rtt_ms ? `${acc.proxy_last_rtt_ms} ms` : "—"}</span></div>
                      <div>Session source: <span className="text-zinc-300">{acc.session_source || "—"}</span></div>
                    </div>

                    {acc.last_error_message && (
                      <p className="text-xs text-red-300 bg-red-500/10 px-3 py-2 rounded-lg">
                        {acc.last_error_code ? `${acc.last_error_code}: ` : ""}{acc.last_error_message}
                      </p>
                    )}

                    <div className="flex items-center gap-2 pt-1">
                      <span className="text-[11px] text-zinc-500 shrink-0">Промпт агента:</span>
                      <select
                        className="flex-1 bg-zinc-950 border border-zinc-800 rounded-lg px-2.5 py-1 text-xs text-zinc-300 focus:outline-none focus:border-blue-500 transition-colors"
                        value={acc.prompt_template_id || ""}
                        onChange={(e) => handleSetPrompt(acc.id, e.target.value)}
                      >
                        <option value="">— глобальный (из Settings) —</option>
                        {prompts.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                      {assignedPrompt && (
                        <span className="text-[10px] bg-violet-500/15 text-violet-400 px-1.5 py-0.5 rounded-full shrink-0">{assignedPrompt.name}</span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 flex-wrap justify-end shrink-0 max-w-[320px]">
                    <button onClick={() => handleProxyTest(acc.id)} disabled={proxyTesting[acc.id]} className="text-xs bg-zinc-700 hover:bg-zinc-600 text-zinc-300 px-3 py-1.5 rounded-lg font-medium transition-colors disabled:opacity-50">
                      {proxyTesting[acc.id] ? "Тестирую..." : "Test Proxy"}
                    </button>
                    {(acc.needs_reauth || acc.session_state === "expired" || acc.session_state === "missing") ? (
                      <button onClick={() => setReauthAccount(acc)} className="text-xs bg-amber-600 hover:bg-amber-500 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
                        Re-auth
                      </button>
                    ) : (
                      <button onClick={() => handleReconnect(acc.id)} disabled={reconnecting[acc.id]} className="text-xs bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded-lg font-medium transition-colors disabled:opacity-50">
                        {reconnecting[acc.id] ? "Подключаю..." : "Reconnect"}
                      </button>
                    )}
                    <button onClick={() => api.saveSession(acc.id).then(load)} className="text-xs bg-zinc-700 hover:bg-zinc-600 text-zinc-300 px-3 py-1.5 rounded-lg font-medium transition-colors">
                      Save Session
                    </button>
                    <button onClick={() => setEditAccount(acc)} className="text-xs bg-zinc-700 hover:bg-zinc-600 text-zinc-300 px-3 py-1.5 rounded-lg font-medium transition-colors">
                      Edit
                    </button>
                    <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer select-none">
                      <div className={`relative w-8 h-4 rounded-full transition-colors ${acc.auto_reply ? "bg-blue-600" : "bg-zinc-700"}`}
                        onClick={() => api.toggleReply(acc.id).then(load)}>
                        <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${acc.auto_reply ? "left-[18px]" : "left-0.5"}`} />
                      </div>
                      Auto-reply
                    </label>
                    <button onClick={() => { if (confirm("Удалить?")) api.deleteAccount(acc.id).then(load); }}
                      className="text-xs text-zinc-600 hover:text-red-400 transition-colors">Delete</button>
                    {reconnectError[acc.id] && (
                      <span className="text-xs text-red-400 bg-red-500/10 px-2 py-1 rounded-lg max-w-[220px]" title={reconnectError[acc.id]}>
                        {reconnectError[acc.id]}
                      </span>
                    )}
                  </div>
                </div>
              </Surface>
            );
          })}
        </div>
      )}

      {showModal && <AddAccountModal onClose={() => setShowModal(false)} onAdded={() => { setShowModal(false); load(); }} />}
      {showTdata && <ImportTdataModal onClose={() => setShowTdata(false)} onAdded={() => { setShowTdata(false); load(); }} />}
      {editAccount && <EditAccountModal account={editAccount} proxies={proxies} onClose={() => setEditAccount(null)} onSaved={() => { setEditAccount(null); load(); }} />}
      {reauthAccount && <ReauthModal account={reauthAccount} onClose={() => setReauthAccount(null)} onDone={() => { setReauthAccount(null); load(); }} />}
    </div>
  );
}
