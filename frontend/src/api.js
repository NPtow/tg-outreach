const BASE = import.meta.env.VITE_API_URL || "";
const APP_TOKEN = import.meta.env.VITE_APP_TOKEN || "";

function buildHeaders(contentType = "application/json") {
  const headers = {};
  if (contentType) headers["Content-Type"] = contentType;
  if (APP_TOKEN) headers["X-App-Token"] = APP_TOKEN;
  return headers;
}

async function readError(r, path) {
  const payload = await r.json().catch(() => ({ detail: r.statusText }));
  const detail = payload?.detail ?? payload;
  let message = r.statusText;
  if (typeof detail === "string") message = detail;
  else if (detail?.error) message = detail.error;
  else if (detail?.reason) message = detail.reason;
  else message = JSON.stringify(detail);
  window.dispatchEvent(new CustomEvent("api-error", { detail: { message, url: path, status: r.status, payload: detail } }));
  const error = new Error(message);
  error.payload = detail;
  error.status = r.status;
  throw error;
}

async function req(method, path, body) {
  const opts = { method, headers: buildHeaders() };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(BASE + path, opts);
  if (!r.ok) return readError(r, path);
  return r.json();
}

function withProject(path, projectId) {
  if (!projectId) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}project_id=${encodeURIComponent(projectId)}`;
}

export const api = {
  getRuntimeStatus: () => req("GET", "/api/runtime/status"),

  // Projects
  getProjects: () => req("GET", "/api/projects/"),
  createProject: (data) => req("POST", "/api/projects/", data),
  updateProject: (id, data) => req("PATCH", `/api/projects/${id}`, data),
  getProjectResources: (id) => req("GET", `/api/projects/${id}/resources`),
  attachProjectAccount: (projectId, accountId) => req("POST", `/api/projects/${projectId}/accounts/${accountId}/attach`),
  attachProjectProxy: (projectId, proxyId) => req("POST", `/api/projects/${projectId}/proxies/${proxyId}/attach`),

  // Accounts
  getAccounts: () => req("GET", "/api/accounts/"),
  createAccount: (data) => req("POST", "/api/accounts/", data),
  updateAccount: (id, data) => req("PATCH", `/api/accounts/${id}`, data),
  sendCode: (account_id) => req("POST", "/api/accounts/send-code", { account_id }),
  verifyCode: (data) => req("POST", "/api/accounts/verify-code", data),
  saveSession: (id) => req("POST", `/api/accounts/${id}/save-session`),
  reconnectAccount: (id) => req("POST", `/api/accounts/${id}/reconnect`),
  setSession: (id, session_string) => req("POST", `/api/accounts/${id}/set-session`, { session_string }),
  proxyTestAccount: (id) => req("POST", `/api/accounts/${id}/proxy-test`),
  toggleReply: (id) => req("POST", `/api/accounts/${id}/toggle-reply`),
  setPrompt: (id, prompt_template_id) => req("POST", `/api/accounts/${id}/set-prompt`, { prompt_template_id }),
  deleteAccount: (id) => req("DELETE", `/api/accounts/${id}`),
  importTdata: (formData) =>
    fetch(BASE + "/api/accounts/import-tdata", {
      method: "POST",
      body: formData,
      headers: APP_TOKEN ? { "X-App-Token": APP_TOKEN } : {},
    }).then(async (r) => {
      if (!r.ok) return readError(r, "/api/accounts/import-tdata");
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
  scheduleMeeting: (id) => req("POST", `/api/conversations/${id}/schedule-meeting`),
  updateStatus: (id, status) => req("PATCH", `/api/conversations/${id}/status`, { status }),
  markRead: (id) => req("POST", `/api/conversations/${id}/mark-read`),
  toggleHot: (id) => req("PATCH", `/api/conversations/${id}/hot`),

  // Agent Lab
  getAgentRuns: (params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== "" && v !== null)
    ).toString();
    return req("GET", `/api/agents/runs${q ? "?" + q : ""}`);
  },
  getScenarios: (status = "", projectId) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (projectId) params.set("project_id", projectId);
    const qs = params.toString();
    return req("GET", `/api/scenarios/${qs ? `?${qs}` : ""}`);
  },
  getGroupedScenarios: (status = "", projectId) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (projectId) params.set("project_id", projectId);
    const qs = params.toString();
    return req("GET", `/api/scenarios/grouped${qs ? `?${qs}` : ""}`);
  },
  seedFounderResearchPack: (projectId) => req("POST", withProject("/api/scenarios/seed-founder-research-pack", projectId)),
  analyzeConversationsForScenarios: (limit = 50, projectId) => {
    const path = `/api/scenarios/analyze-conversations?limit=${limit}`;
    return req("POST", withProject(path, projectId));
  },
  getDifyStatus: () => req("GET", "/api/scenarios/dify/status"),
  getDifyConnectionStatus: () => req("GET", "/api/dify/status"),
  getDifyDocuments: (params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== "" && v !== null)
    ).toString();
    return req("GET", `/api/dify/documents${q ? "?" + q : ""}`);
  },
  getDifyDocument: (id) => req("GET", `/api/dify/documents/${id}`),
  createDifyDocument: (data) => req("POST", "/api/dify/documents", data),
  updateDifyDocument: (id, data) => req("PUT", `/api/dify/documents/${id}`, data),
  deleteDifyDocument: (id) => req("DELETE", `/api/dify/documents/${id}`),
  syncDifyScenarios: (status = "active") => req("POST", `/api/scenarios/dify/sync?status=${status}`),
  legacyFounderResearchPack: () => req("POST", "/api/scenarios/legacy/founder-research-pack"),
  createScenario: (data) => req("POST", "/api/scenarios/", data),
  activateScenario: (id) => req("POST", `/api/scenarios/${id}/activate`),
  mineScenario: (conversation_id) => req("POST", `/api/scenarios/mine?conversation_id=${conversation_id}`),
  replaySandbox: (data) => req("POST", "/api/sandbox/replay", data),
  runEvals: (cases) => req("POST", "/api/evals/run", cases ? { cases } : {}),

  // Campaigns
  getCampaigns: (projectId) => req("GET", withProject("/api/campaigns/", projectId)),
  createCampaign: (data) => req("POST", "/api/campaigns/", data),
  startCampaign: (id) => req("POST", `/api/campaigns/${id}/start`),
  pauseCampaign: (id) => req("POST", `/api/campaigns/${id}/pause`),
  retryFailed: (id) => req("POST", `/api/campaigns/${id}/retry-failed`),
  getCampaignTargets: (id, status) =>
    req("GET", `/api/campaigns/${id}/targets${status ? `?status=${status}` : ""}`),
  deleteCampaign: (id) => req("DELETE", `/api/campaigns/${id}`),

  // Prompts
  getPrompts: (projectId) => req("GET", withProject("/api/prompts/", projectId)),
  createPrompt: (data) => req("POST", "/api/prompts/", data),
  updatePrompt: (id, data) => req("PUT", `/api/prompts/${id}`, data),
  deletePrompt: (id) => req("DELETE", `/api/prompts/${id}`),

  // Agent Pipelines
  getPipelines: (projectId) => req("GET", withProject("/api/agent-pipelines/", projectId)),
  createPipeline: (data) => req("POST", "/api/agent-pipelines/", data),
  updatePipeline: (id, data) => req("PUT", `/api/agent-pipelines/${id}`, data),
  archivePipeline: (id) => req("DELETE", `/api/agent-pipelines/${id}`),
  replayPipeline: (id, data) => req("POST", `/api/agent-pipelines/${id}/replay`, data),
  listN8nWorkflows: (data) => req("POST", "/api/agent-pipelines/n8n/workflows", data),
  getN8nWorkflow: (data, workflow_id) => req("POST", `/api/agent-pipelines/n8n/workflows/get?workflow_id=${encodeURIComponent(workflow_id)}`, data),
  importN8nWorkflow: (data) => req("POST", "/api/agent-pipelines/n8n/workflows/import", data),
  bindN8nWorkflow: (id, data) => req("POST", `/api/agent-pipelines/${id}/bind-n8n-workflow`, data),

  // Do Not Contact
  getDNC: () => req("GET", "/api/dnc/"),
  addDNC: (data) => req("POST", "/api/dnc/", data),
  removeDNC: (id) => req("DELETE", `/api/dnc/${id}`),

  // Contacts
  getContactBatches: (projectId) => req("GET", withProject("/api/contacts/batches/", projectId)),
  deleteContactBatch: (id) => req("DELETE", `/api/contacts/batches/${id}`),
  getContacts: (search, batch_id, projectId) => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (batch_id !== undefined && batch_id !== null) params.set("batch_id", batch_id);
    if (projectId) params.set("project_id", projectId);
    const qs = params.toString();
    return req("GET", `/api/contacts/${qs ? "?" + qs : ""}`);
  },
  createContact: (data) => req("POST", "/api/contacts/", data),
  importContacts: (csv_text, batch_name = "", projectId) => req("POST", "/api/contacts/import", { csv_text, batch_name, project_id: projectId }),
  deleteContact: (id) => req("DELETE", `/api/contacts/${id}`),
  bulkDeleteContacts: (ids) => req("DELETE", "/api/contacts/bulk", { ids }),

  // Settings
  getSettings: () => req("GET", "/api/settings/"),
  saveSettings: (data) => req("PUT", "/api/settings/", data),
  getGoogleAuthUrl: () => req("GET", "/api/integrations/google/auth-url"),

  // Proxy Pool
  getProxies: () => req("GET", "/api/proxy-pool/"),
  addProxy: (line) => req("POST", "/api/proxy-pool/", { line }),
  testProxy: (id) => req("POST", `/api/proxy-pool/${id}/test`),
  deleteProxy: (id) => req("DELETE", `/api/proxy-pool/${id}`),
};
