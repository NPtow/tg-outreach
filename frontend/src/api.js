const BASE = import.meta.env.VITE_API_URL || "";

async function req(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(BASE + path, opts);
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    const msg = err.detail || r.statusText;
    window.dispatchEvent(new CustomEvent("api-error", { detail: { message: msg, url: path, status: r.status } }));
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  // Accounts
  getAccounts: () => req("GET", "/api/accounts/"),
  createAccount: (data) => req("POST", "/api/accounts/", data),
  sendCode: (account_id) => req("POST", "/api/accounts/send-code", { account_id }),
  verifyCode: (data) => req("POST", "/api/accounts/verify-code", data),
  saveSession: (id) => req("POST", `/api/accounts/${id}/save-session`),
  reconnectAccount: (id) => req("POST", `/api/accounts/${id}/reconnect`),
  toggleReply: (id) => req("POST", `/api/accounts/${id}/toggle-reply`),
  setPrompt: (id, prompt_template_id) => req("POST", `/api/accounts/${id}/set-prompt`, { prompt_template_id }),
  deleteAccount: (id) => req("DELETE", `/api/accounts/${id}`),
  importTdata: (formData) =>
    fetch(BASE + "/api/accounts/import-tdata", { method: "POST", body: formData }).then(async (r) => {
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || r.statusText);
      }
      return r.json();
    }),

  // Conversations
  getConversations: (params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== "" && v !== null)
    ).toString();
    return req("GET", `/api/conversations/${q ? "?" + q : ""}`);
  },
  getMessages: (id) => req("GET", `/api/conversations/${id}/messages`),
  sendMessage: (id, text) => req("POST", `/api/conversations/${id}/send`, { text }),
  updateStatus: (id, status) => req("PATCH", `/api/conversations/${id}/status`, { status }),
  markRead: (id) => req("POST", `/api/conversations/${id}/mark-read`),
  toggleHot: (id) => req("PATCH", `/api/conversations/${id}/hot`),

  // Campaigns
  getCampaigns: () => req("GET", "/api/campaigns/"),
  createCampaign: (data) => req("POST", "/api/campaigns/", data),
  startCampaign: (id) => req("POST", `/api/campaigns/${id}/start`),
  pauseCampaign: (id) => req("POST", `/api/campaigns/${id}/pause`),
  retryFailed: (id) => req("POST", `/api/campaigns/${id}/retry-failed`),
  getCampaignTargets: (id, status) =>
    req("GET", `/api/campaigns/${id}/targets${status ? `?status=${status}` : ""}`),
  deleteCampaign: (id) => req("DELETE", `/api/campaigns/${id}`),

  // Prompts
  getPrompts: () => req("GET", "/api/prompts/"),
  createPrompt: (data) => req("POST", "/api/prompts/", data),
  updatePrompt: (id, data) => req("PUT", `/api/prompts/${id}`, data),
  deletePrompt: (id) => req("DELETE", `/api/prompts/${id}`),

  // Do Not Contact
  getDNC: () => req("GET", "/api/dnc/"),
  addDNC: (data) => req("POST", "/api/dnc/", data),
  removeDNC: (id) => req("DELETE", `/api/dnc/${id}`),

  // Contacts
  getContactBatches: () => req("GET", "/api/contacts/batches/"),
  deleteContactBatch: (id) => req("DELETE", `/api/contacts/batches/${id}`),
  getContacts: (search, batch_id) => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (batch_id !== undefined && batch_id !== null) params.set("batch_id", batch_id);
    const qs = params.toString();
    return req("GET", `/api/contacts/${qs ? "?" + qs : ""}`);
  },
  createContact: (data) => req("POST", "/api/contacts/", data),
  importContacts: (csv_text, batch_name = "") => req("POST", "/api/contacts/import", { csv_text, batch_name }),
  deleteContact: (id) => req("DELETE", `/api/contacts/${id}`),
  bulkDeleteContacts: (ids) => req("DELETE", "/api/contacts/bulk", { ids }),

  // Settings
  getSettings: () => req("GET", "/api/settings/"),
  saveSettings: (data) => req("PUT", "/api/settings/", data),
};
