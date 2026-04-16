import { useEffect, useState, useCallback } from "react";
import { api } from "../api";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function Badge({ children, color = "zinc" }) {
  const colors = {
    zinc: "bg-zinc-700 text-zinc-300",
    blue: "bg-blue-500/20 text-blue-400",
    green: "bg-green-500/20 text-green-400",
    yellow: "bg-yellow-500/20 text-yellow-400",
    red: "bg-red-500/20 text-red-400",
    purple: "bg-purple-500/20 text-purple-400",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colors[color] || colors.zinc}`}>
      {children}
    </span>
  );
}

function HealthGauge({ score }) {
  const color = score >= 70 ? "#22c55e" : score >= 40 ? "#eab308" : "#ef4444";
  const r = 18, circ = 2 * Math.PI * r;
  const dash = (score / 100) * circ;
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="48" height="48" className="-rotate-90">
        <circle cx="24" cy="24" r={r} fill="none" stroke="#27272a" strokeWidth="4" />
        <circle cx="24" cy="24" r={r} fill="none" stroke={color} strokeWidth="4"
          strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
          style={{ transition: "stroke-dasharray 0.5s ease" }} />
      </svg>
      <span className="text-xs font-semibold" style={{ color }}>{score}</span>
    </div>
  );
}

function StatusBadge({ status, phase }) {
  if (status === "maintenance") return <Badge color="purple">Maintenance</Badge>;
  if (status === "paused") return <Badge color="yellow">Paused</Badge>;
  if (status === "completed") return <Badge color="zinc">Done</Badge>;
  const phaseColors = { 1: "blue", 2: "blue", 3: "green" };
  return <Badge color={phaseColors[phase] || "blue"}>Phase {phase}</Badge>;
}

function ResultBadge({ result }) {
  const color =
    result === "success" ? "green" :
    result === "failed" ? "red" :
    result === "flood_wait" ? "yellow" :
    result === "skipped" ? "zinc" :
    "blue";
  return <Badge color={color}>{result}</Badge>;
}

function formatTs(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function describePhase(warming) {
  const cfg = warming?.current_phase_config || {};
  if (!warming) return "No active warming";
  const parts = [];
  if (cfg.online_sessions_per_day) parts.push(`${cfg.online_sessions_per_day} online/day`);
  if (cfg.subscriptions_per_day) parts.push(`${cfg.subscriptions_per_day} subscribe/day`);
  else parts.push("no subscriptions in this phase");
  if (cfg.searches_per_day) parts.push(`${cfg.searches_per_day} searches/day`);
  if (cfg.dialog_reads_per_day) parts.push(`${cfg.dialog_reads_per_day} dialog reads/day`);
  if (cfg.reactions_per_day) parts.push(`${cfg.reactions_per_day} reactions/day`);
  if (cfg.mutual_messages_per_day) {
    parts.push(
      warming.peer_account_ids?.length
        ? `${cfg.mutual_messages_per_day} peer msgs/day`
        : "peer msgs only if peers configured"
    );
  }
  return parts.join(" + ");
}

function actionLabel(action) {
  if (action.action_type === "online_session") return "online session";
  if (action.action_type === "read_dialog") return "read dialogs";
  if (action.action_type === "msg_sent") return "peer message";
  return action.action_type.replaceAll("_", " ");
}

const DEFAULT_CONFIG = {
  online_sessions_per_day: 4,
  mutual_messages_per_day: 4,
  subscriptions_per_day: 1,
  reactions_per_day: 0,
  searches_per_day: 3,
  dialog_reads_per_day: 4,
};

// ─── Tab: Dashboard ────────────────────────────────────────────────────────────

function TabDashboard({
  warmings,
  accounts,
  profiles,
  actions,
  selectedAccountId,
  onSelectAccount,
  onRefresh,
}) {
  const [starting, setStarting] = useState(null);
  const [form, setForm] = useState({ profileId: "", label: "", peerIds: "" });
  const [showStart, setShowStart] = useState(null); // account_id

  const warmingByAccount = Object.fromEntries(warmings.map((w) => [w.account_id, w]));
  const selectedWarming = warmings.find((w) => w.account_id === selectedAccountId) || null;
  const selectedAccount = accounts.find((acc) => acc.id === selectedAccountId) || null;

  async function doStart(accountId) {
    if (!form.profileId) return;
    setStarting(accountId);
    try {
      await api.startWarming(accountId, {
        profile_id: parseInt(form.profileId),
        campaign_label: form.label || null,
        peer_account_ids: form.peerIds
          ? form.peerIds.split(",").map((x) => parseInt(x.trim())).filter(Boolean)
          : [],
      });
      setShowStart(null);
      onRefresh();
    } catch { }
    setStarting(null);
  }

  async function doControl(accountId, action) {
    try {
      if (action === "pause") await api.pauseWarming(accountId);
      if (action === "resume") await api.resumeWarming(accountId);
      if (action === "stop") await api.stopWarming(accountId);
      onRefresh();
    } catch { }
  }

  return (
    <div className="space-y-3">
      {accounts.map((acc) => {
        const w = warmingByAccount[acc.id];
        const isSelected = selectedAccountId === acc.id;
        return (
          <div
            key={acc.id}
            onClick={() => w && onSelectAccount(acc.id)}
            className={`bg-zinc-900 border rounded-xl p-4 flex items-start gap-4 transition-colors ${
              isSelected ? "border-blue-500/60" : "border-zinc-800"
            } ${w ? "cursor-pointer" : ""}`}
          >
            <HealthGauge score={w?.health_score ?? 0} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-medium text-zinc-100 text-sm">{acc.name}</span>
                <span className="text-zinc-600 text-xs">{acc.phone}</span>
                {w && <StatusBadge status={w.status} phase={w.phase} />}
                {w?.is_running && <Badge color="green">Running</Badge>}
                {w?.campaign_label && <Badge color="zinc">{w.campaign_label}</Badge>}
              </div>
              {w ? (
                <div className="space-y-2">
                  <div className="grid grid-cols-2 xl:grid-cols-4 gap-x-4 gap-y-1 text-xs text-zinc-500">
                    <span>Attempted: <b className="text-zinc-300">{w.actions_attempted}</b></span>
                    <span>Succeeded: <b className="text-zinc-300">{w.actions_succeeded}</b></span>
                    <span>Today: <b className="text-zinc-300">{w.actions_today}</b></span>
                    <span>Total: <b className="text-zinc-300">{w.total_actions}</b></span>
                    <span>Subs today: <b className="text-zinc-300">{w.subscriptions_today}</b></span>
                    <span>Searches today: <b className="text-zinc-300">{w.searches_today}</b></span>
                    <span>Reads today: <b className="text-zinc-300">{w.dialog_reads_today}</b></span>
                    <span>Peer msgs today: <b className="text-zinc-300">{w.mutual_messages_today}</b></span>
                    <span>Last tick: <b className="text-zinc-300">{formatTs(w.last_tick_at)}</b></span>
                    <span>Next action: <b className="text-zinc-300">{formatTs(w.next_action_at)}</b></span>
                    <span>Last success: <b className="text-zinc-300">{formatTs(w.last_success_at)}</b></span>
                    <span>Ban events: <b className={w.ban_events > 0 ? "text-red-400" : "text-zinc-300"}>{w.ban_events}</b></span>
                  </div>
                  <div className="text-xs text-zinc-500">
                    <span className="text-zinc-400">Current phase:</span> {describePhase(w)}
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <Badge color="zinc">decision: {w.last_decision || "—"}</Badge>
                    <Badge color="zinc">subscribed: {w.subscribed_channels?.length ?? 0}</Badge>
                    {!w.is_running && <Badge color="yellow">worker idle</Badge>}
                  </div>
                  {w.last_error_message && (
                    <div className="text-xs text-red-400 truncate">
                      Last error: {w.last_error_message}
                    </div>
                  )}
                </div>
              ) : (
                <span className="text-xs text-zinc-600">Not warming</span>
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              {!w || w.status === "completed" ? (
                <button
                  onClick={() => setShowStart(acc.id)}
                  className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors">
                  Start Warming
                </button>
              ) : w.status === "paused" ? (
                <>
                  <button onClick={() => doControl(acc.id, "resume")}
                    className="px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-white text-xs font-medium transition-colors">
                    Resume
                  </button>
                  <button onClick={() => doControl(acc.id, "stop")}
                    className="px-3 py-1.5 rounded-lg bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-xs font-medium transition-colors">
                    Stop
                  </button>
                </>
              ) : (
                <>
                  <button onClick={() => doControl(acc.id, "pause")}
                    className="px-3 py-1.5 rounded-lg bg-yellow-600/80 hover:bg-yellow-500 text-white text-xs font-medium transition-colors">
                    Pause
                  </button>
                  <button onClick={() => doControl(acc.id, "stop")}
                    className="px-3 py-1.5 rounded-lg bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-xs font-medium transition-colors">
                    Stop
                  </button>
                </>
              )}
            </div>
          </div>
        );
      })}

      {selectedWarming && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="text-sm font-semibold text-zinc-100">
                Activity Feed: {selectedAccount?.name || `Account ${selectedWarming.account_id}`}
              </h3>
              <p className="text-xs text-zinc-500 mt-1">{describePhase(selectedWarming)}</p>
            </div>
            <div className="text-xs text-zinc-500 text-right">
              <div>Last tick: <span className="text-zinc-300">{formatTs(selectedWarming.last_tick_at)}</span></div>
              <div>Next action: <span className="text-zinc-300">{formatTs(selectedWarming.next_action_at)}</span></div>
            </div>
          </div>

          <div className="grid grid-cols-2 xl:grid-cols-6 gap-3 text-xs">
            <div className="rounded-lg bg-zinc-800/60 px-3 py-2 text-zinc-400">Online<div className="text-zinc-100 mt-1">{selectedWarming.online_sessions_today}</div></div>
            <div className="rounded-lg bg-zinc-800/60 px-3 py-2 text-zinc-400">Subscribe<div className="text-zinc-100 mt-1">{selectedWarming.subscriptions_today}</div></div>
            <div className="rounded-lg bg-zinc-800/60 px-3 py-2 text-zinc-400">React<div className="text-zinc-100 mt-1">{selectedWarming.reactions_today}</div></div>
            <div className="rounded-lg bg-zinc-800/60 px-3 py-2 text-zinc-400">Search<div className="text-zinc-100 mt-1">{selectedWarming.searches_today}</div></div>
            <div className="rounded-lg bg-zinc-800/60 px-3 py-2 text-zinc-400">Dialogs<div className="text-zinc-100 mt-1">{selectedWarming.dialog_reads_today}</div></div>
            <div className="rounded-lg bg-zinc-800/60 px-3 py-2 text-zinc-400">Peer msgs<div className="text-zinc-100 mt-1">{selectedWarming.mutual_messages_today}</div></div>
          </div>

          <div className="space-y-2">
            {actions.length ? actions.map((action) => (
              <div key={action.id} className="flex items-start gap-3 rounded-lg border border-zinc-800 px-3 py-2">
                <div className="pt-0.5"><ResultBadge result={action.result} /></div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-zinc-100">
                    {actionLabel(action)}
                    {action.target ? <span className="text-zinc-500"> · {action.target}</span> : null}
                  </div>
                  <div className="text-xs text-zinc-500 mt-1">
                    attempt {formatTs(action.attempted_at)} · done {formatTs(action.completed_at || action.executed_at)}
                  </div>
                  {action.error_message && (
                    <div className="text-xs text-red-400 mt-1">{action.error_message}</div>
                  )}
                  {action.details?.reason && (
                    <div className="text-xs text-zinc-500 mt-1">reason: {action.details.reason}</div>
                  )}
                  {action.decision_context && (
                    <div className="text-xs text-zinc-600 mt-1">
                      ctx: {Object.entries(action.decision_context).map(([k, v]) => `${k}=${v}`).join(" · ")}
                    </div>
                  )}
                </div>
              </div>
            )) : (
              <div className="text-sm text-zinc-500 py-6 text-center">
                No attempts logged yet for this account.
              </div>
            )}
          </div>
        </div>
      )}

      {showStart && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
          onClick={(e) => e.target === e.currentTarget && setShowStart(null)}>
          <div className="bg-zinc-900 border border-zinc-700 rounded-2xl p-6 w-full max-w-sm space-y-4">
            <h3 className="font-semibold text-zinc-100">Start Warming</h3>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Profile</label>
              <select value={form.profileId} onChange={(e) => setForm(f => ({ ...f, profileId: e.target.value }))}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none">
                <option value="">Select profile…</option>
                {profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">A/B Label (optional)</label>
              <input value={form.label} onChange={(e) => setForm(f => ({ ...f, label: e.target.value }))}
                placeholder="e.g. 7day, aggressive"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none placeholder-zinc-600" />
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Peer account IDs (comma-sep, for mutual messaging)</label>
              <input value={form.peerIds} onChange={(e) => setForm(f => ({ ...f, peerIds: e.target.value }))}
                placeholder="2, 5, 8"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none placeholder-zinc-600" />
            </div>
            <div className="flex gap-2 pt-1">
              <button onClick={() => doStart(showStart)} disabled={!form.profileId || starting}
                className="flex-1 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors disabled:opacity-50">
                {starting ? "Starting…" : "Start"}
              </button>
              <button onClick={() => setShowStart(null)}
                className="px-4 py-2 rounded-lg bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-sm transition-colors">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Tab: Profiles ────────────────────────────────────────────────────────────

const CONFIG_KEYS = [
  { key: "online_sessions_per_day", label: "Online sessions / day", max: 12 },
  { key: "mutual_messages_per_day", label: "Mutual messages / day", max: 20 },
  { key: "subscriptions_per_day", label: "Channel subs / day", max: 5 },
  { key: "reactions_per_day", label: "Reactions / day", max: 15 },
  { key: "searches_per_day", label: "Searches / day", max: 10 },
  { key: "dialog_reads_per_day", label: "Dialog reads / day", max: 10 },
];

function PhaseConfig({ label, value, onChange }) {
  return (
    <div>
      <p className="text-xs font-medium text-zinc-400 mb-2">{label}</p>
      <div className="space-y-2">
        {CONFIG_KEYS.map(({ key, label: kl, max }) => (
          <div key={key} className="flex items-center gap-3">
            <span className="text-xs text-zinc-500 w-40 shrink-0">{kl}</span>
            <input type="range" min={0} max={max} value={value[key] ?? 0}
              onChange={(e) => onChange({ ...value, [key]: parseInt(e.target.value) })}
              className="flex-1 accent-blue-500" />
            <span className="text-xs text-zinc-300 w-6 text-right">{value[key] ?? 0}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TabProfiles({ profiles, onRefresh }) {
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const emptyForm = {
    name: "", description: "", phase_1_days: 3, phase_2_days: 7,
    phase_1_config: { ...DEFAULT_CONFIG },
    phase_2_config: { ...DEFAULT_CONFIG, subscriptions_per_day: 2, reactions_per_day: 3 },
    phase_3_config: { ...DEFAULT_CONFIG, subscriptions_per_day: 1, reactions_per_day: 6, mutual_messages_per_day: 5 },
    maintenance_config: { online_sessions_per_day: 2, mutual_messages_per_day: 0, subscriptions_per_day: 0, reactions_per_day: 2, searches_per_day: 1, dialog_reads_per_day: 2 },
    permanent_maintenance: false,
  };
  const [form, setForm] = useState(emptyForm);

  function openNew() { setForm(emptyForm); setEditing("new"); }
  function openEdit(p) {
    setForm({ ...p });
    setEditing(p.id);
  }

  async function save() {
    setSaving(true);
    try {
      if (editing === "new") await api.createWarmingProfile(form);
      else await api.updateWarmingProfile(editing, form);
      setEditing(null);
      onRefresh();
    } catch { }
    setSaving(false);
  }

  async function del(id) {
    if (!confirm("Delete this profile?")) return;
    await api.deleteWarmingProfile(id);
    onRefresh();
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button onClick={openNew}
          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors">
          + New Profile
        </button>
      </div>

      {profiles.map(p => (
        <div key={p.id} className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <p className="font-medium text-zinc-100 text-sm">{p.name}</p>
            {p.description && <p className="text-xs text-zinc-500 mt-0.5">{p.description}</p>}
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs text-zinc-600">Phase 1: {p.phase_1_days}d · Phase 2: {p.phase_2_days}d</span>
              {p.permanent_maintenance && <Badge color="purple">Permanent</Badge>}
            </div>
          </div>
          <button onClick={() => openEdit(p)} className="px-3 py-1.5 rounded-lg bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-xs transition-colors">Edit</button>
          <button onClick={() => del(p.id)} className="px-3 py-1.5 rounded-lg bg-red-500/20 hover:bg-red-500/30 text-red-400 text-xs transition-colors">Del</button>
        </div>
      ))}

      {editing && (
        <div className="fixed inset-0 bg-black/60 flex items-start justify-center z-50 overflow-y-auto py-8"
          onClick={(e) => e.target === e.currentTarget && setEditing(null)}>
          <div className="bg-zinc-900 border border-zinc-700 rounded-2xl p-6 w-full max-w-2xl space-y-5 m-4">
            <h3 className="font-semibold text-zinc-100">{editing === "new" ? "New Profile" : "Edit Profile"}</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-zinc-500 mb-1 block">Name</label>
                <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none" />
              </div>
              <div>
                <label className="text-xs text-zinc-500 mb-1 block">Description</label>
                <input value={form.description || ""} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none" />
              </div>
              <div>
                <label className="text-xs text-zinc-500 mb-1 block">Phase 1 days</label>
                <input type="number" min={1} max={14} value={form.phase_1_days}
                  onChange={e => setForm(f => ({ ...f, phase_1_days: parseInt(e.target.value) }))}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none" />
              </div>
              <div>
                <label className="text-xs text-zinc-500 mb-1 block">Phase 2 days</label>
                <input type="number" min={1} max={30} value={form.phase_2_days}
                  onChange={e => setForm(f => ({ ...f, phase_2_days: parseInt(e.target.value) }))}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none" />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input type="checkbox" id="perm" checked={form.permanent_maintenance}
                onChange={e => setForm(f => ({ ...f, permanent_maintenance: e.target.checked }))}
                className="accent-purple-500" />
              <label htmlFor="perm" className="text-sm text-zinc-300">Permanent maintenance after Phase 3</label>
            </div>
            <div className="grid grid-cols-2 gap-6">
              <PhaseConfig label="Phase 1 (online + subscribe + reads)" value={form.phase_1_config}
                onChange={v => setForm(f => ({ ...f, phase_1_config: v }))} />
              <PhaseConfig label="Phase 2 (+ subscriptions)" value={form.phase_2_config}
                onChange={v => setForm(f => ({ ...f, phase_2_config: v }))} />
              <PhaseConfig label="Phase 3 (full activity)" value={form.phase_3_config}
                onChange={v => setForm(f => ({ ...f, phase_3_config: v }))} />
              <PhaseConfig label="Maintenance (keep-alive)" value={form.maintenance_config}
                onChange={v => setForm(f => ({ ...f, maintenance_config: v }))} />
            </div>
            <div className="flex gap-2 pt-1">
              <button onClick={save} disabled={saving || !form.name}
                className="flex-1 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors disabled:opacity-50">
                {saving ? "Saving…" : "Save"}
              </button>
              <button onClick={() => setEditing(null)}
                className="px-4 py-2 rounded-lg bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-sm transition-colors">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Tab: A/B Comparison ──────────────────────────────────────────────────────

function TabAB({ stats }) {
  if (!stats.length) return (
    <div className="text-center text-zinc-600 py-16">
      No labeled warming campaigns yet.<br />
      <span className="text-xs">Add an A/B label when starting warming to compare groups.</span>
    </div>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-xs text-zinc-500 text-left">
            <th className="pb-3 pr-4">Label</th>
            <th className="pb-3 pr-4">Accounts</th>
            <th className="pb-3 pr-4">Avg Health</th>
            <th className="pb-3 pr-4">Ban Rate</th>
            <th className="pb-3 pr-4">Campaign Ready</th>
            <th className="pb-3">Phases</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/50">
          {stats.map(s => (
            <tr key={s.label} className="text-zinc-300">
              <td className="py-3 pr-4 font-medium text-zinc-100">{s.label}</td>
              <td className="py-3 pr-4">{s.accounts_count}</td>
              <td className="py-3 pr-4">
                <span className={s.avg_health_score >= 70 ? "text-green-400" : s.avg_health_score >= 40 ? "text-yellow-400" : "text-red-400"}>
                  {s.avg_health_score}
                </span>
              </td>
              <td className="py-3 pr-4">
                <span className={s.ban_rate > 0.2 ? "text-red-400" : s.ban_rate > 0 ? "text-yellow-400" : "text-green-400"}>
                  {(s.ban_rate * 100).toFixed(0)}%
                </span>
              </td>
              <td className="py-3 pr-4 text-green-400">{s.campaign_ready_count} / {s.accounts_count}</td>
              <td className="py-3 text-xs text-zinc-500">
                {Object.entries(s.phase_distribution).map(([ph, cnt]) => cnt > 0 ? `P${ph}:${cnt}` : null).filter(Boolean).join(" · ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Tab: Channel Pool ────────────────────────────────────────────────────────

const NICHES = ["tech", "business", "general", "crypto", "marketing", "news", "humor", "finance", "other"];

function TabPool({ pool, onRefresh }) {
  const [form, setForm] = useState({ username: "", title: "", niche: "general", language: "ru" });
  const [adding, setAdding] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [showBulk, setShowBulk] = useState(false);

  async function add() {
    if (!form.username) return;
    setAdding(true);
    try {
      await api.addWarmingChannel({ ...form, username: form.username.replace("@", "") });
      setForm({ username: "", title: "", niche: "general", language: "ru" });
      onRefresh();
    } catch { }
    setAdding(false);
  }

  async function bulkImport() {
    const lines = bulkText.trim().split("\n").filter(Boolean);
    const channels = lines.map(line => {
      const [username, niche, language] = line.split(",").map(s => s.trim());
      return { username: username.replace("@", ""), niche: niche || "general", language: language || "ru" };
    });
    await api.importWarmingChannels(channels);
    setBulkText("");
    setShowBulk(false);
    onRefresh();
  }

  const grouped = pool.reduce((acc, c) => {
    (acc[c.niche || "other"] = acc[c.niche || "other"] || []).push(c);
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      <div className="flex items-end gap-3 bg-zinc-900 border border-zinc-800 rounded-xl p-4">
        <div className="flex-1">
          <label className="text-xs text-zinc-500 mb-1 block">Username</label>
          <input value={form.username} onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
            placeholder="@channel or channel"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none placeholder-zinc-600" />
        </div>
        <div>
          <label className="text-xs text-zinc-500 mb-1 block">Niche</label>
          <select value={form.niche} onChange={e => setForm(f => ({ ...f, niche: e.target.value }))}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none">
            {NICHES.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-zinc-500 mb-1 block">Lang</label>
          <select value={form.language} onChange={e => setForm(f => ({ ...f, language: e.target.value }))}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none">
            <option value="ru">RU</option>
            <option value="en">EN</option>
          </select>
        </div>
        <button onClick={add} disabled={!form.username || adding}
          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors disabled:opacity-50">
          Add
        </button>
        <button onClick={() => setShowBulk(v => !v)}
          className="px-4 py-2 rounded-lg bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-sm transition-colors">
          Bulk
        </button>
      </div>

      {showBulk && (
        <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4 space-y-3">
          <p className="text-xs text-zinc-500">One per line: <code className="bg-zinc-800 px-1 rounded">@username, niche, lang</code></p>
          <textarea value={bulkText} onChange={e => setBulkText(e.target.value)}
            rows={6} placeholder={"@durov,tech,ru\n@businessclub,business,ru\n@cryptonews,crypto,ru"}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 font-mono focus:outline-none placeholder-zinc-600 resize-none" />
          <button onClick={bulkImport} disabled={!bulkText.trim()}
            className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors disabled:opacity-50">
            Import
          </button>
        </div>
      )}

      {Object.entries(grouped).sort().map(([niche, channels]) => (
        <div key={niche}>
          <h4 className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-2">{niche}</h4>
          <div className="space-y-1">
            {channels.map(c => (
              <div key={c.id} className="flex items-center gap-3 bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2">
                <span className={`w-2 h-2 rounded-full shrink-0 ${c.is_active ? "bg-green-500" : "bg-zinc-600"}`} />
                <span className="text-sm text-zinc-300 font-mono">@{c.username}</span>
                {c.title && <span className="text-xs text-zinc-500 truncate flex-1">{c.title}</span>}
                <span className="text-xs text-zinc-600">{c.language}</span>
                <button onClick={() => api.toggleWarmingChannel(c.id).then(onRefresh)}
                  className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700">
                  {c.is_active ? "Disable" : "Enable"}
                </button>
                <button onClick={() => api.deleteWarmingChannel(c.id).then(onRefresh)}
                  className="text-xs text-red-500 hover:text-red-400 transition-colors">del</button>
              </div>
            ))}
          </div>
        </div>
      ))}
      {!pool.length && (
        <div className="text-center text-zinc-600 py-12">No channels yet. Add some to start warming.</div>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

const TABS = ["Dashboard", "Profiles", "A/B Campaigns", "Channel Pool"];

export default function Warming() {
  const [tab, setTab] = useState("Dashboard");
  const [warmings, setWarmings] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [pool, setPool] = useState([]);
  const [abStats, setAbStats] = useState([]);
  const [selectedAccountId, setSelectedAccountId] = useState(null);
  const [selectedActions, setSelectedActions] = useState([]);

  const load = useCallback(async () => {
    const [w, a, p, ch, ab] = await Promise.all([
      api.getWarmings().catch(() => []),
      api.getAccounts().catch(() => []),
      api.getWarmingProfiles().catch(() => []),
      api.getWarmingPool().catch(() => []),
      api.getWarmingAbStats().catch(() => []),
    ]);
    setWarmings(w);
    setAccounts(a);
    setProfiles(p);
    setPool(ch);
    setAbStats(ab);
    setSelectedAccountId((current) => {
      if (current && w.some((item) => item.account_id === current)) return current;
      return w[0]?.account_id ?? null;
    });
  }, []);

  const loadSelectedActions = useCallback(async (accountId) => {
    if (!accountId) {
      setSelectedActions([]);
      return;
    }
    const result = await api.getWarmingActions(accountId, 25, 0).catch(() => ({ items: [] }));
    setSelectedActions(result.items || []);
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    loadSelectedActions(selectedAccountId);
  }, [selectedAccountId, loadSelectedActions]);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      load();
      if (selectedAccountId) loadSelectedActions(selectedAccountId);
    }, 25000);
    return () => window.clearInterval(intervalId);
  }, [load, loadSelectedActions, selectedAccountId]);

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-zinc-100">Warming</h1>
        <p className="text-sm text-zinc-500 mt-0.5">Account warm-up and background maintenance</p>
      </div>

      <div className="flex gap-1 mb-6 bg-zinc-900 rounded-xl p-1 w-fit border border-zinc-800">
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              tab === t ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
            }`}>
            {t}
          </button>
        ))}
      </div>

      {tab === "Dashboard" && (
        <TabDashboard
          warmings={warmings}
          accounts={accounts}
          profiles={profiles}
          actions={selectedActions}
          selectedAccountId={selectedAccountId}
          onSelectAccount={setSelectedAccountId}
          onRefresh={load}
        />
      )}
      {tab === "Profiles" && <TabProfiles profiles={profiles} onRefresh={load} />}
      {tab === "A/B Campaigns" && <TabAB stats={abStats} />}
      {tab === "Channel Pool" && <TabPool pool={pool} onRefresh={load} />}
    </div>
  );
}
