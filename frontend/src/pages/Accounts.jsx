import { useEffect, useState } from "react";
import { api } from "../api";

const STEPS = { FORM: "form", CODE: "code", DONE: "done" };

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
    setError("");
    setLoading(true);
    try {
      const acc = await api.createAccount(form);
      setAccountId(acc.id);
      const result = await api.sendCode(acc.id);
      if (result.ok) {
        setPhoneCodeHash(result.phone_code_hash);
        setStep(STEPS.CODE);
      } else {
        setError(result.error || "Failed to send code");
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async () => {
    setError("");
    setLoading(true);
    try {
      const result = await api.verifyCode({
        account_id: accountId,
        phone_code_hash: phoneCodeHash,
        code,
        password,
      });
      if (result.ok) {
        setStep(STEPS.DONE);
        onAdded();
      } else {
        setError(result.error || "Wrong code");
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg p-6 w-full max-w-md border border-gray-600">
        <h2 className="text-lg font-bold mb-4">
          {step === STEPS.FORM && "Добавить аккаунт"}
          {step === STEPS.CODE && "Введи код из Telegram"}
          {step === STEPS.DONE && "Готово!"}
        </h2>

        {step === STEPS.FORM && (
          <div className="space-y-3">
            <p className="text-xs text-gray-400">
              App ID и App Hash получи на{" "}
              <a href="https://my.telegram.org" target="_blank" rel="noreferrer" className="text-blue-400 underline">
                my.telegram.org
              </a>{" "}
              → API development tools
            </p>
            {[
              { key: "name", label: "Название (любое)", placeholder: "Мой аккаунт" },
              { key: "phone", label: "Номер телефона", placeholder: "+79001234567" },
              { key: "app_id", label: "App ID", placeholder: "12345678" },
              { key: "app_hash", label: "App Hash", placeholder: "abcdef..." },
            ].map(({ key, label, placeholder }) => (
              <div key={key}>
                <label className="text-xs text-gray-400 block mb-1">{label}</label>
                <input
                  className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
                  placeholder={placeholder}
                  value={form[key]}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                />
              </div>
            ))}
          </div>
        )}

        {step === STEPS.CODE && (
          <div className="space-y-3">
            <p className="text-sm text-gray-300">Код отправлен на {form.phone}</p>
            <div>
              <label className="text-xs text-gray-400 block mb-1">Код из Telegram</label>
              <input
                className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm tracking-widest"
                placeholder="12345"
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 block mb-1">2FA пароль (если есть)</label>
              <input
                type="password"
                className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>
        )}

        {step === STEPS.DONE && (
          <p className="text-green-400 text-sm">Аккаунт подключён и слушает сообщения!</p>
        )}

        {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

        <div className="flex gap-3 mt-5">
          {step === STEPS.FORM && (
            <button
              onClick={handleCreate}
              disabled={loading}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-4 py-2 rounded text-sm"
            >
              {loading ? "..." : "Отправить код"}
            </button>
          )}
          {step === STEPS.CODE && (
            <button
              onClick={handleVerify}
              disabled={loading}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-4 py-2 rounded text-sm"
            >
              {loading ? "..." : "Подтвердить"}
            </button>
          )}
          <button onClick={onClose} className="text-gray-400 hover:text-white px-4 py-2 rounded text-sm">
            {step === STEPS.DONE ? "Закрыть" : "Отмена"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ImportTdataModal({ onClose, onAdded }) {
  const [form, setForm] = useState({
    name: "", phone: "", proxy_host: "", proxy_port: "", proxy_type: "HTTP",
    proxy_user: "", proxy_pass: "",
  });
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
      setDone(true);
      onAdded();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg p-6 w-full max-w-md border border-gray-600 max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-bold mb-4">Импорт tdata</h2>

        {done ? (
          <p className="text-green-400 text-sm">Аккаунт подключён!</p>
        ) : (
          <div className="space-y-3">
            {[
              { k: "name", label: "Название", placeholder: "Аккаунт США" },
              { k: "phone", label: "Номер телефона", placeholder: "+14508507294" },
            ].map(({ k, label, placeholder }) => (
              <div key={k}>
                <label className="text-xs text-gray-400 block mb-1">{label}</label>
                <input className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
                  placeholder={placeholder} value={form[k]} onChange={(e) => set(k, e.target.value)} />
              </div>
            ))}

            <div>
              <label className="text-xs text-gray-400 block mb-1">Zip-файл с tdata</label>
              <input type="file" accept=".zip"
                className="w-full text-sm text-gray-300 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:bg-gray-600 file:text-white"
                onChange={(e) => setFile(e.target.files[0])} />
            </div>

            <p className="text-xs text-gray-500 pt-1">Прокси (США, HTTP или SOCKS5)</p>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs text-gray-400 block mb-1">Хост</label>
                <input className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
                  placeholder="102.129.221.128" value={form.proxy_host} onChange={(e) => set("proxy_host", e.target.value)} />
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">Порт</label>
                <input className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
                  placeholder="9671" value={form.proxy_port} onChange={(e) => set("proxy_port", e.target.value)} />
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-400 block mb-1">Тип</label>
              <select className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
                value={form.proxy_type} onChange={(e) => set("proxy_type", e.target.value)}>
                <option>HTTP</option>
                <option>SOCKS5</option>
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs text-gray-400 block mb-1">Логин</label>
                <input className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
                  placeholder="EzH26g" value={form.proxy_user} onChange={(e) => set("proxy_user", e.target.value)} />
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">Пароль</label>
                <input className="w-full bg-gray-700 border border-gray-500 rounded px-3 py-2 text-sm"
                  placeholder="5zpqxr" value={form.proxy_pass} onChange={(e) => set("proxy_pass", e.target.value)} />
              </div>
            </div>
          </div>
        )}

        {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

        <div className="flex gap-3 mt-5">
          {!done && (
            <button onClick={handleSubmit} disabled={loading}
              className="bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white px-4 py-2 rounded text-sm">
              {loading ? "Импортирую..." : "Импортировать"}
            </button>
          )}
          <button onClick={onClose} className="text-gray-400 hover:text-white px-4 py-2 rounded text-sm">
            {done ? "Закрыть" : "Отмена"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Accounts() {
  const [accounts, setAccounts] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [showTdata, setShowTdata] = useState(false);

  const load = () => api.getAccounts().then(setAccounts);

  useEffect(() => { load(); }, []);

  const handleDelete = async (id) => {
    if (!confirm("Удалить аккаунт?")) return;
    await api.deleteAccount(id);
    load();
  };

  const handleToggle = async (id) => {
    await api.toggleReply(id);
    load();
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Accounts</h1>
        <div className="flex gap-2">
          <button onClick={() => setShowTdata(true)}
            className="bg-green-700 hover:bg-green-600 text-white px-4 py-2 rounded text-sm font-medium">
            + Import tdata
          </button>
          <button onClick={() => setShowModal(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded text-sm font-medium">
            + Add Account
          </button>
        </div>
      </div>

      {accounts.length === 0 ? (
        <div className="text-gray-500 text-sm">Нет аккаунтов. Добавь первый.</div>
      ) : (
        <div className="space-y-3">
          {accounts.map((acc) => (
            <div key={acc.id} className="bg-gray-800 border border-gray-700 rounded-lg p-4 flex items-center justify-between">
              <div>
                <div className="font-medium">{acc.name}</div>
                <div className="text-sm text-gray-400">{acc.phone}</div>
              </div>
              <div className="flex items-center gap-4">
                <span className={`text-xs px-2 py-1 rounded-full ${acc.is_active ? "bg-green-900 text-green-300" : "bg-gray-700 text-gray-400"}`}>
                  {acc.is_active ? "Online" : "Offline"}
                </span>
                <label className="flex items-center gap-2 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    checked={acc.auto_reply}
                    onChange={() => handleToggle(acc.id)}
                    className="w-4 h-4"
                  />
                  Auto-reply
                </label>
                <button
                  onClick={() => handleDelete(acc.id)}
                  className="text-red-400 hover:text-red-300 text-sm"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <AddAccountModal onClose={() => { setShowModal(false); load(); }} onAdded={load} />
      )}
      {showTdata && (
        <ImportTdataModal onClose={() => { setShowTdata(false); load(); }} onAdded={load} />
      )}
    </div>
  );
}
