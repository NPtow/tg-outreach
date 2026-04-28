import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { EmptyState, PageHeader, Surface } from "../components/workspace";

const inputCls = "w-full rounded-2xl border border-white/10 bg-black/25 px-3.5 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition focus:border-sky-400/40 focus:bg-white/[0.05]";

function parseWorkflow(workflowJson) {
  if (!workflowJson) return {};
  try {
    return JSON.parse(workflowJson);
  } catch {
    return {};
  }
}

function embeddedPipelineConfig(workflow) {
  const candidates = [
    workflow?.pipeline_config,
    workflow?.tg_outreach,
    workflow?.meta?.tg_outreach,
    workflow?.settings?.tg_outreach,
  ];
  return candidates.find((item) => item && typeof item === "object" && !Array.isArray(item)) || {};
}

function webhookPathFromWorkflow(workflow) {
  const webhook = (workflow?.nodes || []).find((node) => (node.type || "").includes("webhook"));
  return webhook?.parameters?.path || "";
}

function workflowMeta(workflowJson) {
  const workflow = parseWorkflow(workflowJson);
  const config = embeddedPipelineConfig(workflow);
  const webhookUrl = config.webhook_url || config.production_webhook_url || workflow.webhook_url || workflow.production_webhook_url || "";
  return {
    workflow,
    config,
    name: workflow.name || config.workflow_name || "",
    webhookPath: config.webhook_path || webhookPathFromWorkflow(workflow),
    webhookUrl,
  };
}

function toPayload(form, projectId) {
  const meta = workflowMeta(form.workflow_json);
  const existingConfig = form.existing_config || {};
  const importedConfig = meta.config || {};
  const config = {
    ...existingConfig,
    ...importedConfig,
    mode: form.mode,
    workflow_json: form.workflow_json || existingConfig.workflow_json || "",
    workflow_name: meta.name || existingConfig.workflow_name || "",
    webhook_path: meta.webhookPath || existingConfig.webhook_path || "",
    webhook_url: importedConfig.webhook_url || existingConfig.webhook_url || "",
    production_webhook_url: importedConfig.production_webhook_url || meta.webhookUrl || existingConfig.production_webhook_url || "",
    shared_secret: importedConfig.shared_secret || form.shared_secret || "",
    timeout_s: Number(importedConfig.timeout_s || importedConfig.timeout || existingConfig.timeout_s || 20),
    meeting_window: importedConfig.meeting_window || existingConfig.meeting_window || "16:00-22:00",
    duration_minutes: Number(importedConfig.duration_minutes || existingConfig.duration_minutes || 30),
  };

  return {
    name: form.name.trim() || meta.name || "n8n pipeline",
    project_id: projectId,
    description: form.description,
    type: "n8n_webhook",
    status: form.status,
    config,
  };
}

function fromPipeline(pipeline) {
  const config = pipeline?.config || {};
  return {
    name: pipeline?.name || "",
    description: pipeline?.description || "",
    status: pipeline?.status || "draft",
    mode: config.mode || "sandbox",
    workflow_json: config.workflow_json || "",
    shared_secret: "",
    existing_config: config,
    imported_file_name: "",
  };
}

function PipelineEditor({ projectId, selected, onSaved }) {
  const [form, setForm] = useState(() => fromPipeline(selected));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const fileRef = useRef(null);
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));

  useEffect(() => {
    setForm(fromPipeline(selected));
    setMessage("");
  }, [selected?.id]);

  const importJsonFile = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setMessage("");
    try {
      const text = await file.text();
      const workflow = JSON.parse(text);
      const formattedJson = JSON.stringify(workflow, null, 2);
      const meta = workflowMeta(formattedJson);
      setForm((current) => ({
        ...current,
        workflow_json: formattedJson,
        imported_file_name: file.name,
        name: current.name || meta.name,
      }));
      setMessage("JSON импортирован. Проверь название и сохрани pipeline.");
    } catch {
      setMessage("Файл не похож на валидный JSON.");
    } finally {
      event.target.value = "";
    }
  };

  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      const payload = toPayload(form, projectId);
      const saved = selected?.id
        ? await api.updatePipeline(selected.id, payload)
        : await api.createPipeline(payload);
      setMessage("Pipeline сохранён.");
      onSaved(saved);
    } catch (e) {
      setMessage(e.message);
    } finally {
      setSaving(false);
    }
  };

  const meta = workflowMeta(form.workflow_json);
  const hasJson = Boolean(form.workflow_json);
  const existingWebhookUrl = form.existing_config?.webhook_url || form.existing_config?.production_webhook_url || "";
  const hasWebhook = Boolean(meta.webhookUrl || existingWebhookUrl);

  return (
    <Surface className="p-5">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.22em] text-zinc-500">Pipeline file</div>
          <div className="mt-1 text-sm leading-6 text-zinc-500">Загружаешь n8n workflow JSON. Технические URL/timeout/secret должны лежать внутри JSON config.</div>
        </div>
        <button className="btn-primary" disabled={saving} onClick={save}>{saving ? "Сохраняю..." : selected?.id ? "Save pipeline" : "Create pipeline"}</button>
      </div>

      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-3">
          <input className={inputCls} placeholder={meta.name || "Название pipeline"} value={form.name} onChange={(e) => set("name", e.target.value)} />
          <input className={inputCls} placeholder="Описание, необязательно" value={form.description} onChange={(e) => set("description", e.target.value)} />
          <div className="grid grid-cols-2 gap-2">
            <select className={inputCls} value={form.status} onChange={(e) => set("status", e.target.value)}>
              <option value="draft">draft</option>
              <option value="active">active</option>
              <option value="archived">archived</option>
            </select>
            <select className={inputCls} value={form.mode} onChange={(e) => set("mode", e.target.value)}>
              <option value="sandbox">sandbox</option>
              <option value="shadow">shadow</option>
              <option value="live">live</option>
            </select>
          </div>

          <input ref={fileRef} className="hidden" type="file" accept="application/json,.json" onChange={importJsonFile} />
          <button className="w-full rounded-2xl border border-sky-400/25 bg-sky-400/10 px-4 py-3 text-left text-sm font-medium text-sky-100 transition hover:border-sky-300/45 hover:bg-sky-400/15" onClick={() => fileRef.current?.click()}>
            Import n8n JSON file
          </button>

          <div className="rounded-2xl border border-white/8 bg-black/25 p-3 text-xs leading-5 text-zinc-400">
            <div>Файл: <span className="font-mono text-zinc-200">{form.imported_file_name || (hasJson ? "уже загружен" : "не выбран")}</span></div>
            <div>Workflow: <span className="font-mono text-zinc-200">{meta.name || "не найден"}</span></div>
            <div>Webhook URL: <span className={hasWebhook ? "font-mono text-emerald-200" : "font-mono text-amber-200"}>{hasWebhook ? "найден в JSON/config" : "не найден в JSON"}</span></div>
          </div>

          {!hasWebhook && hasJson && (
            <div className="rounded-2xl border border-amber-400/15 bg-amber-400/10 p-3 text-xs leading-5 text-amber-100">
              В JSON нет `production_webhook_url` или `webhook_url`. Pipeline сохранится, но auto-reply не сможет вызвать n8n, пока URL не будет внутри config.
            </div>
          )}
          {message && <div className="rounded-2xl border border-white/8 bg-black/25 p-3 text-xs leading-5 text-zinc-300">{message}</div>}
        </div>

        <div className="flex min-h-[320px] items-center justify-center rounded-3xl border border-dashed border-white/10 bg-black/20 p-8 text-center">
          <div className="max-w-md">
            <div className="text-lg font-semibold text-zinc-100">{hasJson ? "JSON загружен" : "Импортируй n8n workflow JSON"}</div>
            <div className="mt-2 text-sm leading-6 text-zinc-500">
              Ручного редактора JSON больше нет: пайплайн приходит файлом, а runtime-настройки берутся из config внутри этого файла.
            </div>
            <button className="mt-5 rounded-2xl border border-white/10 px-4 py-2 text-sm text-zinc-200 transition hover:border-white/20 hover:bg-white/5" onClick={() => fileRef.current?.click()}>
              {hasJson ? "Заменить файл" : "Выбрать файл"}
            </button>
          </div>
        </div>
      </div>
    </Surface>
  );
}

function PipelineList({ pipelines, selectedId, onSelect, onArchive }) {
  if (pipelines.length === 0) {
    return <EmptyState icon="🧩" title="No pipelines yet" description="Импортируй n8n workflow JSON и создай первый pipeline." />;
  }
  return (
    <div className="space-y-2">
      {pipelines.map((pipeline) => {
        const config = pipeline.config || {};
        const selected = selectedId === pipeline.id;
        return (
          <Surface key={pipeline.id} className={`cursor-pointer p-4 transition-colors ${selected ? "border-sky-400/35 bg-sky-400/10" : "hover:border-white/16"}`} onClick={() => onSelect(pipeline.id)}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="truncate text-sm font-medium text-zinc-100">{pipeline.name}</div>
                  <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-zinc-300">{pipeline.status}</span>
                  <span className="rounded-full border border-blue-400/20 bg-blue-400/10 px-2 py-0.5 text-[10px] text-blue-200">{config.mode || "sandbox"}</span>
                </div>
                <div className="mt-1 truncate text-xs text-zinc-500">{pipeline.description || config.workflow_name || "n8n workflow file"}</div>
              </div>
              <button className="text-xs text-zinc-600 hover:text-red-400" onClick={(e) => { e.stopPropagation(); onArchive(pipeline.id); }}>Архив</button>
            </div>
          </Surface>
        );
      })}
    </div>
  );
}

function ReplayPanel({ pipelines }) {
  const activePipelines = pipelines.filter((item) => item.status === "active");
  const [pipelineId, setPipelineId] = useState("");
  const [conversationId, setConversationId] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!pipelineId && activePipelines[0]) setPipelineId(String(activePipelines[0].id));
  }, [activePipelines, pipelineId]);

  const run = async () => {
    if (!pipelineId || !conversationId) return;
    setBusy(true);
    try {
      setResult(await api.replayPipeline(Number(pipelineId), { conversation_id: Number(conversationId), dry_run_tools: true }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Surface className="p-5">
      <div className="mb-4">
        <div className="text-sm font-semibold uppercase tracking-[0.22em] text-zinc-500">Replay test</div>
        <div className="mt-1 text-sm text-zinc-500">Проверка pipeline на conversation_id без отправки в Telegram.</div>
      </div>
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_auto]">
        <select className={inputCls} value={pipelineId} onChange={(e) => setPipelineId(e.target.value)}>
          {activePipelines.length === 0 ? <option value="">Нет active pipeline</option> : null}
          {activePipelines.map((pipeline) => <option key={pipeline.id} value={pipeline.id}>{pipeline.name}</option>)}
        </select>
        <input className={inputCls} placeholder="conversation_id" value={conversationId} onChange={(e) => setConversationId(e.target.value)} />
        <button className="btn-primary" disabled={!pipelineId || !conversationId || busy} onClick={run}>{busy ? "Проверяю..." : "Test"}</button>
      </div>
      {result && <pre className="mt-4 max-h-[360px] overflow-auto rounded-2xl border border-white/8 bg-black/35 p-4 text-xs leading-5 text-zinc-300">{JSON.stringify(result, null, 2)}</pre>}
    </Surface>
  );
}

export default function Prompts({ projectId }) {
  const [pipelines, setPipelines] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const load = async () => {
    const data = await api.getPipelines(projectId);
    setPipelines(data);
    setSelectedId((current) => data.find((item) => item.id === current)?.id || data[0]?.id || null);
  };

  useEffect(() => { load(); }, [projectId]);

  const selected = useMemo(() => pipelines.find((item) => item.id === selectedId) || null, [pipelines, selectedId]);
  const activeCount = pipelines.filter((item) => item.status === "active").length;

  const handleSaved = async (saved) => {
    await load();
    setSelectedId(saved.id);
  };

  const archive = async (id) => {
    if (!confirm("Архивировать pipeline?")) return;
    await api.archivePipeline(id);
    await load();
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="AI Layer"
        title="Agent Pipelines"
        description="Минимальный экран: импортируешь n8n workflow JSON, сохраняешь pipeline, привязываешь его к кампании и тестируешь replay."
        actions={<button onClick={() => setSelectedId(null)} className="btn-primary">+ New Pipeline</button>}
        stats={[
          { label: "Pipelines", value: pipelines.length, tone: pipelines.length ? "violet" : "neutral", caption: "n8n JSON files" },
          { label: "Active", value: activeCount, tone: activeCount ? "emerald" : "neutral", caption: "Available for campaigns" },
        ]}
      />

      <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <PipelineList pipelines={pipelines} selectedId={selectedId} onSelect={setSelectedId} onArchive={archive} />
        <PipelineEditor projectId={projectId} selected={selected} onSaved={handleSaved} />
      </div>

      <ReplayPanel pipelines={pipelines} />
    </div>
  );
}
