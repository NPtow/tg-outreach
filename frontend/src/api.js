const BASE = "http://localhost:8000";

async function req(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(BASE + path, opts);
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

export const api = {
  // Accounts
  getAccounts: () => req("GET", "/api/accounts/"),
  createAccount: (data) => req("POST", "/api/accounts/", data),
  sendCode: (account_id) => req("POST", "/api/accounts/send-code", { account_id }),
  verifyCode: (data) => req("POST", "/api/accounts/verify-code", data),
  toggleReply: (id) => req("POST", `/api/accounts/${id}/toggle-reply`),
  deleteAccount: (id) => req("DELETE", `/api/accounts/${id}`),
  importTdata: (formData) => {
    return fetch(BASE + "/api/accounts/import-tdata", { method: "POST", body: formData })
      .then(async (r) => {
        if (!r.ok) {
          const err = await r.json().catch(() => ({ detail: r.statusText }));
          throw new Error(err.detail || r.statusText);
        }
        return r.json();
      });
  },

  // Conversations
  getConversations: (params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
    return req("GET", `/api/conversations/${q ? "?" + q : ""}`);
  },
  getMessages: (id) => req("GET", `/api/conversations/${id}/messages`),
  sendMessage: (id, text) => req("POST", `/api/conversations/${id}/send`, { text }),
  updateStatus: (id, status) => req("PATCH", `/api/conversations/${id}/status`, { status }),

  // Campaigns
  getCampaigns: () => req("GET", "/api/campaigns/"),
  createCampaign: (data) => req("POST", "/api/campaigns/", data),
  startCampaign: (id) => req("POST", `/api/campaigns/${id}/start`),
  pauseCampaign: (id) => req("POST", `/api/campaigns/${id}/pause`),
  deleteCampaign: (id) => req("DELETE", `/api/campaigns/${id}`),

  // Settings
  getSettings: () => req("GET", "/api/settings/"),
  saveSettings: (data) => req("PUT", "/api/settings/", data),
};
