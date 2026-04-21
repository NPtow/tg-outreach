import { useEffect, useState } from "react";
import { api } from "../api";
import { useWsEvent } from "../ws";

const STEPS = { FORM: "form", CODE: "code", DONE: "done" };

const STATUS_META = {
  working: { label: "Работает", cls: "bg-emerald-500/10 text-emerald-400" },
  not_working: { label: "Не работает", cls: "bg-red-500/10 text-red-400" },
};

const DEBUG_META = {
  online: { label: "Online", cls: "bg-emerald-500/10 text-emerald-400" },
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
  eligible: { label: "Eligible", cls: "bg-emerald-500/10 text-emerald-400" },
  blocked_proxy: { label: "Blocked by proxy", cls: "bg-red-500/10 text-red-400" },
  blocked_auth: { label: "Blocked by auth", cls: "bg-amber-500/10 text-amber-400" },
};

function fmtTs(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function statusBadgeFor(key) {
  return STATUS_META[key] || { label: key || "unknown", cls: "bg-zinc-800 text-zinc-400" };
}

function debugBadgeFor(key) {
  return DEBUG_META[key] || { label: key || "unknown", cls: "bg-zinc-800 text-zinc-400" };
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

function AddAccountModal({ onClose, onAdded }) {
  const [step, setStep] = useState(STEPS.FORM);
  const [form, setForm] = useState({
    name: "", phone: "", app_id: "", app_hash: "",
    proxy_host: "", proxy_port: "", proxy_type: "SOCKS5", proxy_user: "", proxy_pass: "",
  });
  const [accountId, setAccountId] = useState(null);
  const [phoneCodeHash, setPhoneCodeHash] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    setError(""); setLoading(true);
    try {
      const payload = { ...form, proxy_port: form.proxy_port ? Number(form.proxy_port) : null };
      const acc = await api.createAccount(payload);
      setAccountId(acc.id);
      const result = await api.sendCode(acc.id);
      if (result.ok) { setPhoneCodeHash(result.phone_code_hash); setStep(STEPS.CODE); }
      else setError(result.error || "Ошибка отправки кода");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const handleVerify = async () => {
    setError(""); setLoading(true);
    try {
      const result = await api.verifyCode({ account_id: accountId, phone_code_hash: phoneCodeHash, code, password });
      if (result.ok) { setStep(STEPS.DONE); onAdded(); }
      else setError(result.error || "Неверный код");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <Modal title={step === STEPS.DONE ? "Готово!" : step === STEPS.CODE ? "Введи код" : "Добавить аккаунт"} onClose={onClose} wide={step === STEPS.FORM}>
      {step === STEPS.FORM && (
        <div className="space-y-3">
          <p className="text-xs text-zinc-500 bg-zinc-800/50 rounded-lg px-3 py-2">
            App ID и App Hash получи на <a href="https://my.telegram.org" target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">my.telegram.org</a>.
          </p>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Название"><Input placeholder="Мой аккаунт" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Номер телефона"><Input placeholder="+79001234567" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
            <Field label="App ID"><Input placeholder="12345678" value={form.app_id} onChange={(e) => setForm({ ...form, app_id: e.target.value })} /></Field>
            <Field label="App Hash"><Input placeholder="abcdef..." value={form.app_hash} onChange={(e) => setForm({ ...form, app_hash: e.target.value })} /></Field>
          </div>
          <ProxyFields form={form} setForm={setForm} />
        </div>
      )}
      {step === STEPS.CODE && (
        <div className="space-y-3">
          <p className="text-sm text-zinc-400">Код отправлен на <span className="text-zinc-200 font-medium">{form.phone}</span></p>
          <Field label="Код из Telegram"><Input placeholder="12345" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
          <Field label="2FA пароль (если есть)"><Input type="password" placeholder="••••••" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        </div>
      )}
      {step === STEPS.DONE && (
        <div className="text-center py-4">
          <div className="text-4xl mb-3">✅</div>
          <p className="text-zinc-300 text-sm">Аккаунт подключён и переведён в новый health-runtime</p>
        </div>
      )}
      {error && <p className="text-red-400 text-xs mt-3 bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>}
      <div className="flex gap-2 mt-5">
        {step === STEPS.FORM && <button onClick={handleCreate} disabled={loading} className="btn-primary">{loading ? "Отправляю..." : "Отправить код"}</button>}
        {step === STEPS.CODE && <button onClick={handleVerify} disabled={loading} className="btn-primary">{loading ? "Проверяю..." : "Подтвердить"}</button>}
        <button onClick={onClose} className="btn-ghost">{step === STEPS.DONE ? "Закрыть" : "Отмена"}</button>
      </div>
    </Modal>
  );
}

function EditAccountModal({ account, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: account.name || "",
    phone: account.phone || "",
    app_id: account.app_id || "",
    app_hash: "",
    proxy_host: account.proxy_host || "",
    proxy_port: account.proxy_port || "",
    proxy_type: account.proxy_type || "SOCKS5",
    proxy_user: account.proxy_user || "",
    proxy_pass: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSave = async () => {
    setLoading(true); setError("");
    try {
      await api.updateAccount(account.id, {
        ...form,
        proxy_port: form.proxy_port ? Number(form.proxy_port) : null,
      });
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
        <ProxyFields form={form} setForm={setForm} />
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
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSendCode = async () => {
    setError(""); setLoading(true);
    try {
      const result = await api.sendCode(account.id);
      if (result.ok) setPhoneCodeHash(result.phone_code_hash);
      else setError(result.error || "Ошибка отправки кода");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const handleVerify = async () => {
    setError(""); setLoading(true);
    try {
      const result = await api.verifyCode({ account_id: account.id, phone_code_hash: phoneCodeHash, code, password });
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
  const meta = statusBadgeFor(value);
  return <span className={`text-[11px] px-2 py-1 rounded-full font-medium ${meta.cls}`}>{meta.label}</span>;
}

function DebugBadge({ value }) {
  const meta = debugBadgeFor(value);
  return <span className={`text-[11px] px-2 py-1 rounded-full font-medium ${meta.cls}`}>{meta.label}</span>;
}

export default function Accounts() {
  const [accounts, setAccounts] = useState([]);
  const [prompts, setPrompts] = useState([]);
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

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-zinc-100">Accounts</h1>
          <p className="text-sm text-zinc-500 mt-0.5">Health-aware runtime для Telegram аккаунтов</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowTdata(true)} className="btn-secondary">+ Import tdata</button>
          <button onClick={() => setShowModal(true)} className="btn-primary">+ Add Account</button>
        </div>
      </div>

      <div className={`mb-4 rounded-xl border px-4 py-3 text-sm ${runtime?.ok ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : "border-red-500/20 bg-red-500/10 text-red-300"}`}>
        {runtime?.ok
          ? `Telegram worker online · role: ${runtime.role}`
          : "Telegram worker unreachable. Reconnect/start commands будут недоступны."}
      </div>

      {accounts.length === 0 ? (
        <div className="border border-dashed border-zinc-700 rounded-2xl p-12 text-center">
          <div className="text-4xl mb-3">👤</div>
          <p className="text-zinc-400 text-sm font-medium mb-1">Нет аккаунтов</p>
          <p className="text-zinc-600 text-xs">Добавь Telegram аккаунт чтобы начать</p>
        </div>
      ) : (
        <div className="space-y-3">
          {accounts.map((acc) => {
            const assignedPrompt = prompts.find((p) => p.id === acc.prompt_template_id);
            const health = acc.health || {};
            const debug = health.debug || {};
            const needsReauth = Boolean(
              debug.needs_reauth || ["missing", "expired", "recovery_failed"].includes(debug.session_state)
            );
            return (
              <div key={acc.id} className="bg-zinc-900 border border-zinc-800 rounded-xl px-5 py-4 hover:border-zinc-700 transition-colors">
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-3 flex-1 min-w-0">
                    <div className="flex items-center gap-3">
                      <div className={`w-2 h-2 rounded-full shrink-0 ${health.is_online ? "bg-emerald-500" : "bg-zinc-600"}`} />
                      <div>
                        <p className="text-sm font-medium text-zinc-100">{acc.name}</p>
                        <p className="text-xs text-zinc-500">
                          {acc.phone}
                          {acc.tdata_stored && <span className="ml-1.5 text-[10px] text-emerald-400/70">tdata ✓</span>}
                          {acc.proxy_host && <span className="ml-1.5 text-[10px] text-blue-400/70">{acc.proxy_type} {acc.proxy_host}:{acc.proxy_port}</span>}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      <HealthBadge value={health.status} />
                      <span className="text-xs text-zinc-500">
                        {health.reason}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-3 text-[11px] text-zinc-500">
                      <div>Онлайн: <span className="text-zinc-300">{health.is_online ? "Да" : "Нет"}</span></div>
                      <div>Принимает входящие: <span className="text-zinc-300">{health.can_receive ? "Да" : "Нет"}</span></div>
                      <div>Автоответ: <span className="text-zinc-300">{health.can_auto_reply ? "Готов" : "Недоступен"}</span></div>
                      <div>Рассылка: <span className="text-zinc-300">{health.can_receive ? "Готова" : "Недоступна"}</span></div>
                      <div>Обновлено: <span className="text-zinc-300">{fmtTs(health.updated_at)}</span></div>
                      <div>Прокси: <span className="text-zinc-300">{acc.proxy_host ? `${acc.proxy_type} ${acc.proxy_host}:${acc.proxy_port}` : "Без прокси"}</span></div>
                    </div>

                    <details className="rounded-lg border border-zinc-800 bg-zinc-950/60">
                      <summary className="cursor-pointer list-none px-3 py-2 text-xs text-zinc-400 hover:text-zinc-200 transition-colors">
                        Debug details
                      </summary>
                      <div className="px-3 pb-3 pt-1 space-y-3 border-t border-zinc-800">
                        <div className="flex flex-wrap gap-2">
                          <DebugBadge value={debug.connection_state} />
                          <DebugBadge value={debug.proxy_state} />
                          <DebugBadge value={debug.session_state} />
                          <DebugBadge value={debug.eligibility_state} />
                        </div>
                        <div className="grid grid-cols-2 gap-3 text-[11px] text-zinc-500">
                          <div>Last connect: <span className="text-zinc-300">{fmtTs(debug.last_connect_at)}</span></div>
                          <div>Last proxy check: <span className="text-zinc-300">{fmtTs(debug.last_proxy_check_at)}</span></div>
                          <div>Last seen online: <span className="text-zinc-300">{fmtTs(debug.last_seen_online_at)}</span></div>
                          <div>Proxy RTT: <span className="text-zinc-300">{debug.proxy_last_rtt_ms ? `${debug.proxy_last_rtt_ms} ms` : "—"}</span></div>
                          <div>Warmup level: <span className="text-zinc-300">{debug.warmup_level || 0}</span></div>
                          <div>Session source: <span className="text-zinc-300">{debug.session_source || "—"}</span></div>
                        </div>
                        {debug.last_error_message && (
                          <p className="text-xs text-red-300 bg-red-500/10 px-3 py-2 rounded-lg">
                            {debug.last_error_code ? `${debug.last_error_code}: ` : ""}{debug.last_error_message}
                          </p>
                        )}
                      </div>
                    </details>

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
                    {needsReauth ? (
                      <button onClick={() => setReauthAccount(acc)} className="text-xs bg-amber-600 hover:bg-amber-500 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
                        Авторизовать
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
              </div>
            );
          })}
        </div>
      )}

      {showModal && <AddAccountModal onClose={() => setShowModal(false)} onAdded={() => { setShowModal(false); load(); }} />}
      {showTdata && <ImportTdataModal onClose={() => setShowTdata(false)} onAdded={() => { setShowTdata(false); load(); }} />}
      {editAccount && <EditAccountModal account={editAccount} onClose={() => setEditAccount(null)} onSaved={() => { setEditAccount(null); load(); }} />}
      {reauthAccount && <ReauthModal account={reauthAccount} onClose={() => setReauthAccount(null)} onDone={() => { setReauthAccount(null); load(); }} />}
    </div>
  );
}
