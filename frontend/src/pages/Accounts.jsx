import { useEffect, useState } from "react";
import { api } from "../api";

const STEPS = { FORM: "form", CODE: "code", DONE: "done" };

function Field({ label, ...props }) {
  return (
    <div>
      <label className="text-xs font-medium text-zinc-400 block mb-1.5">{label}</label>
      <input className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500 transition-colors" {...props} />
    </div>
  );
}

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 rounded-2xl w-full max-w-md border border-zinc-700/50 shadow-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
          <h2 className="text-base font-semibold text-zinc-100">{title}</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200 text-xl leading-none w-7 h-7 flex items-center justify-center rounded-lg hover:bg-zinc-800 transition-colors">×</button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

function AddAccountModal({ onClose, onAdded }) {
  const [step, setStep] = useState(STEPS.FORM);
  const [form, setForm] = useState({ name: "", phone: "", app_id: "", app_hash: "" });
  const [accountId, setAccountId] = useState(null);
  const [phoneCodeHash, setPhoneCodeHash] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    setError(""); setLoading(true);
    try {
      const acc = await api.createAccount(form);
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
    <Modal title={step === STEPS.DONE ? "Готово!" : step === STEPS.CODE ? "Введи код" : "Добавить аккаунт"} onClose={onClose}>
      {step === STEPS.FORM && (
        <div className="space-y-3">
          <p className="text-xs text-zinc-500 bg-zinc-800/50 rounded-lg px-3 py-2">
            App ID и App Hash получи на <a href="https://my.telegram.org" target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">my.telegram.org</a> → API development tools
          </p>
          <Field label="Название" placeholder="Мой аккаунт" value={form.name} onChange={e => setForm({...form, name: e.target.value})} />
          <Field label="Номер телефона" placeholder="+79001234567" value={form.phone} onChange={e => setForm({...form, phone: e.target.value})} />
          <Field label="App ID" placeholder="12345678" value={form.app_id} onChange={e => setForm({...form, app_id: e.target.value})} />
          <Field label="App Hash" placeholder="abcdef..." value={form.app_hash} onChange={e => setForm({...form, app_hash: e.target.value})} />
        </div>
      )}
      {step === STEPS.CODE && (
        <div className="space-y-3">
          <p className="text-sm text-zinc-400">Код отправлен на <span className="text-zinc-200 font-medium">{form.phone}</span></p>
          <Field label="Код из Telegram" placeholder="12345" value={code} onChange={e => setCode(e.target.value)} />
          <Field label="2FA пароль (если есть)" type="password" placeholder="••••••" value={password} onChange={e => setPassword(e.target.value)} />
        </div>
      )}
      {step === STEPS.DONE && (
        <div className="text-center py-4">
          <div className="text-4xl mb-3">✅</div>
          <p className="text-zinc-300 text-sm">Аккаунт подключён и слушает сообщения</p>
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

function ImportTdataModal({ onClose, onAdded }) {
  const [form, setForm] = useState({ name: "", phone: "", proxy_host: "", proxy_port: "", proxy_type: "HTTP", proxy_user: "", proxy_pass: "" });
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

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
    <Modal title="Импорт tdata" onClose={onClose}>
      {done ? (
        <div className="text-center py-4">
          <div className="text-4xl mb-3">✅</div>
          <p className="text-zinc-300 text-sm">Аккаунт импортирован и запущен</p>
        </div>
      ) : (
        <div className="space-y-3">
          <Field label="Название" placeholder="USA Account #1" value={form.name} onChange={e => set("name", e.target.value)} />
          <Field label="Номер телефона" placeholder="+14508507294" value={form.phone} onChange={e => set("phone", e.target.value)} />
          <div>
            <label className="text-xs font-medium text-zinc-400 block mb-1.5">Zip-файл с tdata</label>
            <input type="file" accept=".zip"
              className="w-full text-sm text-zinc-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-zinc-800 file:text-zinc-300 file:hover:bg-zinc-700 file:transition-colors"
              onChange={e => setFile(e.target.files[0])} />
          </div>
          <div className="border-t border-zinc-800 pt-3">
            <p className="text-xs font-medium text-zinc-500 mb-2.5">Прокси (рекомендуется для USA аккаунтов)</p>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Хост" placeholder="102.129.221.128" value={form.proxy_host} onChange={e => set("proxy_host", e.target.value)} />
              <Field label="Порт" placeholder="9671" value={form.proxy_port} onChange={e => set("proxy_port", e.target.value)} />
            </div>
            <div className="grid grid-cols-3 gap-2 mt-2">
              <div>
                <label className="text-xs font-medium text-zinc-400 block mb-1.5">Тип</label>
                <select className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-blue-500"
                  value={form.proxy_type} onChange={e => set("proxy_type", e.target.value)}>
                  <option>HTTP</option><option>SOCKS5</option>
                </select>
              </div>
              <Field label="Логин" placeholder="user" value={form.proxy_user} onChange={e => set("proxy_user", e.target.value)} />
              <Field label="Пароль" placeholder="pass" value={form.proxy_pass} onChange={e => set("proxy_pass", e.target.value)} />
            </div>
          </div>
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
  const [step, setStep] = useState("code"); // code | done
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
      if (result.ok) { setStep("done"); onDone(); }
      else setError(result.error || "Неверный код");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <Modal title="Повторная авторизация" onClose={onClose}>
      {step === "done" ? (
        <div className="text-center py-4">
          <div className="text-4xl mb-3">✅</div>
          <p className="text-zinc-300 text-sm">Аккаунт переподключён</p>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-zinc-400 bg-zinc-800/50 rounded-lg px-3 py-2">
            Аккаунт <span className="text-zinc-200 font-medium">{account.name}</span> ({account.phone}) — сессия истекла. Авторизуйся заново без удаления аккаунта.
          </p>
          {!phoneCodeHash ? (
            <p className="text-sm text-zinc-400">Нажми кнопку ниже — код придёт в Telegram</p>
          ) : (
            <>
              <p className="text-sm text-zinc-400">Код отправлен на <span className="text-zinc-200 font-medium">{account.phone}</span></p>
              <Field label="Код из Telegram" placeholder="12345" value={code} onChange={e => setCode(e.target.value)} />
              <Field label="2FA пароль (если есть)" type="password" placeholder="••••••" value={password} onChange={e => setPassword(e.target.value)} />
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
      )}
    </Modal>
  );
}

export default function Accounts() {
  const [accounts, setAccounts] = useState([]);
  const [prompts, setPrompts] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [showTdata, setShowTdata] = useState(false);
  const [reauthAccount, setReauthAccount] = useState(null);
  const [reconnecting, setReconnecting] = useState({});

  const load = () => api.getAccounts().then(setAccounts);

  useEffect(() => {
    load();
    api.getPrompts().then(setPrompts);
  }, []);

  const handleSetPrompt = async (accId, promptId) => {
    await api.setPrompt(accId, promptId ? Number(promptId) : null);
    load();
  };

  const handleReconnect = async (accId) => {
    setReconnecting(r => ({ ...r, [accId]: true }));
    try {
      await api.reconnectAccount(accId);
      load();
    } finally {
      setReconnecting(r => ({ ...r, [accId]: false }));
    }
  };

  return (
    <div className="p-8 max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-zinc-100">Accounts</h1>
          <p className="text-sm text-zinc-500 mt-0.5">{accounts.length} аккаунт{accounts.length !== 1 ? "а" : ""} подключено</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowTdata(true)} className="btn-secondary">+ Import tdata</button>
          <button onClick={() => setShowModal(true)} className="btn-primary">+ Add Account</button>
        </div>
      </div>

      {accounts.length === 0 ? (
        <div className="border border-dashed border-zinc-700 rounded-2xl p-12 text-center">
          <div className="text-4xl mb-3">👤</div>
          <p className="text-zinc-400 text-sm font-medium mb-1">Нет аккаунтов</p>
          <p className="text-zinc-600 text-xs">Добавь Telegram аккаунт чтобы начать</p>
        </div>
      ) : (
        <div className="space-y-2">
          {accounts.map(acc => {
            const assignedPrompt = prompts.find(p => p.id === acc.prompt_template_id);
            return (
              <div key={acc.id} className="bg-zinc-900 border border-zinc-800 rounded-xl px-5 py-4 hover:border-zinc-700 transition-colors">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full shrink-0 ${acc.is_active ? "bg-emerald-500" : "bg-zinc-600"}`} />
                    <div>
                      <p className="text-sm font-medium text-zinc-100">{acc.name}</p>
                      <p className="text-xs text-zinc-500">{acc.phone}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap justify-end">
                    {acc.needs_reauth ? (
                      <span className="text-xs px-2 py-1 rounded-full font-medium bg-amber-500/10 text-amber-400">
                        Нужна авторизация
                      </span>
                    ) : (
                      <span className={`text-xs px-2 py-1 rounded-full font-medium ${acc.is_active ? "bg-emerald-500/10 text-emerald-400" : "bg-zinc-800 text-zinc-500"}`}>
                        {acc.is_active ? "Online" : "Offline"}
                      </span>
                    )}
                    {acc.needs_reauth ? (
                      <button onClick={() => setReauthAccount(acc)}
                        className="text-xs bg-amber-600 hover:bg-amber-500 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
                        Авторизовать
                      </button>
                    ) : acc.is_active ? (
                      <button onClick={() => api.saveSession(acc.id).then(() => alert('Сессия сохранена ✓'))}
                        className="text-xs bg-zinc-700 hover:bg-zinc-600 text-zinc-300 px-3 py-1.5 rounded-lg font-medium transition-colors">
                        💾 Сохранить сессию
                      </button>
                    ) : !acc.is_active ? (
                      <button onClick={() => handleReconnect(acc.id)} disabled={reconnecting[acc.id]}
                        className="text-xs bg-zinc-700 hover:bg-zinc-600 text-zinc-300 px-3 py-1.5 rounded-lg font-medium transition-colors disabled:opacity-50">
                        {reconnecting[acc.id] ? "Подключаю..." : "↺ Переподключить"}
                      </button>
                    ) : null}
                    <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer select-none">
                      <div className={`relative w-8 h-4 rounded-full transition-colors ${acc.auto_reply ? "bg-blue-600" : "bg-zinc-700"}`}
                        onClick={() => api.toggleReply(acc.id).then(load)}>
                        <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${acc.auto_reply ? "left-[18px]" : "left-0.5"}`} />
                      </div>
                      Auto-reply
                    </label>
                    <button onClick={() => { if (confirm("Удалить?")) api.deleteAccount(acc.id).then(load); }}
                      className="text-xs text-zinc-600 hover:text-red-400 transition-colors">Delete</button>
                  </div>
                </div>
                {/* Prompt selector */}
                <div className="mt-3 pt-3 border-t border-zinc-800/60 flex items-center gap-2">
                  <span className="text-[11px] text-zinc-500 shrink-0">Промпт агента:</span>
                  <select
                    className="flex-1 bg-zinc-950 border border-zinc-800 rounded-lg px-2.5 py-1 text-xs text-zinc-300 focus:outline-none focus:border-blue-500 transition-colors"
                    value={acc.prompt_template_id || ""}
                    onChange={e => handleSetPrompt(acc.id, e.target.value)}
                  >
                    <option value="">— глобальный (из Settings) —</option>
                    {prompts.map(p => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                  {assignedPrompt && (
                    <span className="text-[10px] bg-violet-500/15 text-violet-400 px-1.5 py-0.5 rounded-full shrink-0">{assignedPrompt.name}</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {showModal && <AddAccountModal onClose={() => { setShowModal(false); load(); }} onAdded={load} />}
      {showTdata && <ImportTdataModal onClose={() => { setShowTdata(false); load(); }} onAdded={load} />}
      {reauthAccount && (
        <ReauthModal
          account={reauthAccount}
          onClose={() => setReauthAccount(null)}
          onDone={() => { setReauthAccount(null); load(); }}
        />
      )}
    </div>
  );
}
