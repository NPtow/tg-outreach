import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { EmptyState, PageHeader, SectionLabel, Surface } from "../components/workspace";

const inputCls = "w-full rounded-2xl border border-white/10 bg-black/25 px-3.5 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition focus:border-sky-400/40 focus:bg-white/[0.05]";

const TABS = [
  { key: "documents", label: "Документы", hint: "Папки и редактор" },
  { key: "scenarios", label: "Старые сценарии", hint: "Старый формат" },
  { key: "sandbox", label: "Песочница", hint: "Без отправки" },
  { key: "runs", label: "Журнал", hint: "Логи решений" },
  { key: "connection", label: "Подключение", hint: "Dify и импорт" },
];

const EMPTY_DRAFT = { name: "", text: "" };

function JsonBlock({ data }) {
  if (!data) return null;
  return (
    <pre className="max-h-[380px] overflow-auto rounded-2xl border border-white/8 bg-black/35 p-4 text-xs leading-5 text-zinc-300">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function Card({ title, children, action, className = "" }) {
  return (
    <Surface className={`p-5 ${className}`}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-[0.22em] text-zinc-500">{title}</h2>
        {action}
      </div>
      {children}
    </Surface>
  );
}

function Badge({ children, className = "" }) {
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-medium ${className}`}>
      {children}
    </span>
  );
}

function statusTone(status) {
  if (status === "active") return "border-emerald-400/20 bg-emerald-400/10 text-emerald-200";
  if (status === "suggested") return "border-amber-400/20 bg-amber-400/10 text-amber-200";
  if (status === "draft") return "border-sky-400/20 bg-sky-400/10 text-sky-200";
  if (status === "legacy") return "border-zinc-400/15 bg-zinc-400/10 text-zinc-300";
  return "border-white/10 bg-white/5 text-zinc-300";
}

function statusLabel(scenario) {
  return scenario.status_label || {
    active: "Активен",
    suggested: "Предложен",
    draft: "Черновик",
    legacy: "Архив",
  }[scenario.status] || scenario.status || "Без статуса";
}

function intentLabel(scenario) {
  return scenario.intent_label || scenario.intent || "Без типа";
}

function docStatusLabel(status) {
  return {
    completed: "готов",
    available: "готов",
    indexing: "индексируется",
    parsing: "читается",
    cleaning: "очищается",
    splitting: "режется",
    error: "ошибка",
    paused: "пауза",
  }[status] || status || "без статуса";
}

function docStatusTone(status) {
  if (["completed", "available"].includes(status)) return "border-emerald-400/20 bg-emerald-400/10 text-emerald-200";
  if (["indexing", "parsing", "cleaning", "splitting"].includes(status)) return "border-sky-400/20 bg-sky-400/10 text-sky-200";
  if (status === "error") return "border-rose-400/20 bg-rose-400/10 text-rose-200";
  return "border-white/10 bg-white/5 text-zinc-300";
}

function documentFolder(document) {
  const name = (document.name || "").toLowerCase();
  if (name.startsWith("scenario-") || name.includes("сценар")) return "Сценарии";
  if (name.startsWith("core-") || name.includes("context") || name.includes("контекст")) return "Контекст";
  if (name.includes("example") || name.includes("conversation") || name.includes("пример")) return "Примеры переписок";
  if (name.includes("negative") || name.includes("mistake") || name.includes("ошиб")) return "Негативные паттерны";
  if (name.includes("eval") || name.includes("test") || name.includes("провер")) return "Тестовые кейсы";
  return "Документы";
}

function groupDocuments(documents) {
  const groups = new Map();
  for (const document of documents) {
    const folder = documentFolder(document);
    if (!groups.has(folder)) groups.set(folder, []);
    groups.get(folder).push(document);
  }
  return Array.from(groups.entries()).map(([folder, items]) => ({
    folder,
    items: items.sort((a, b) => (a.name || "").localeCompare(b.name || "")),
  }));
}

function ScenarioItem({ scenario, selected, onSelect, onActivate }) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(scenario)}
      onKeyDown={(event) => {
        if (event.key === "Enter") onSelect(scenario);
      }}
      className={`w-full rounded-2xl border p-4 text-left transition ${
        selected ? "border-sky-400/35 bg-sky-400/10" : "border-white/8 bg-black/20 hover:border-white/16 hover:bg-white/[0.04]"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-white">{scenario.title}</div>
          <div className="mt-1 text-xs text-zinc-500">{intentLabel(scenario)}</div>
        </div>
        <Badge className={statusTone(scenario.status)}>{statusLabel(scenario)}</Badge>
      </div>
      <p className="mt-3 line-clamp-2 text-sm leading-6 text-zinc-300">{scenario.trigger_summary}</p>
      {scenario.status !== "active" && scenario.status !== "legacy" ? (
        <div className="mt-3">
          <button
            type="button"
            className="inline-flex rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-zinc-200"
            onClick={(event) => {
              event.stopPropagation();
              onActivate(scenario.id);
            }}
          >
            Одобрить
          </button>
        </div>
      ) : null}
    </div>
  );
}

function ScenarioDetail({ scenario, onActivate, onReplaySource }) {
  if (!scenario) {
    return (
      <Surface className="p-5">
        <EmptyState compact icon="С" title="Выбери сценарий" description="Это старый формат. Основная база теперь редактируется во вкладке «Документы»." />
      </Surface>
    );
  }

  return (
    <Surface className="sticky top-6 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.22em] text-zinc-500">Детали сценария</div>
          <h2 className="mt-3 text-xl font-semibold leading-tight text-white">{scenario.title}</h2>
          <div className="mt-2 text-sm text-zinc-500">{intentLabel(scenario)}</div>
        </div>
        <Badge className={statusTone(scenario.status)}>{statusLabel(scenario)}</Badge>
      </div>

      <div className="mt-5 space-y-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">ID и Dify</div>
          <div className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
            <div className="rounded-2xl border border-white/8 bg-black/20 p-3">
              <div className="text-zinc-500">ID сценария</div>
              <div className="mt-1 text-zinc-200">#{scenario.id}</div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/20 p-3">
              <div className="text-zinc-500">ID документа Dify</div>
              <div className="mt-1 truncate text-zinc-200">{scenario.dify_document_id || "нет"}</div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/20 p-3">
              <div className="text-zinc-500">Статус Dify</div>
              <div className="mt-1 truncate text-zinc-200">{scenario.dify_sync_status || "не синхронизирован"}</div>
            </div>
          </div>
          {scenario.dify_sync_error ? (
            <div className="mt-2 rounded-2xl border border-rose-400/20 bg-rose-400/10 p-3 text-xs leading-5 text-rose-100">
              {scenario.dify_sync_error}
            </div>
          ) : null}
        </div>
        <QuestionBlock questions={scenario.example_questions || []} />
        <DetailBlock title="Когда применять" text={scenario.trigger_summary} />
        <DetailBlock title="Как отвечать" text={scenario.recommended_reply} pre />
        {scenario.avoid_reply ? <DetailBlock title="Чего избегать" text={scenario.avoid_reply} /> : null}
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">Источник</div>
          <div className="mt-2 rounded-2xl border border-white/8 bg-black/20 p-3 text-sm text-zinc-300">
            {scenario.source_conversation_id ? `Переписка #${scenario.source_conversation_id}` : "Ручной сценарий или базовый пакет"}
          </div>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        {scenario.status !== "active" && scenario.status !== "legacy" ? (
          <button className="btn-primary" onClick={() => onActivate(scenario.id)}>Одобрить сценарий</button>
        ) : null}
        {scenario.source_conversation_id ? (
          <button className="btn-ghost" onClick={() => onReplaySource(scenario.source_conversation_id)}>Проверить источник в песочнице</button>
        ) : null}
      </div>
    </Surface>
  );
}

function QuestionBlock({ questions }) {
  if (!questions.length) return null;
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">На какие вопросы отвечает</div>
      <div className="mt-2 space-y-2">
        {questions.map((question) => (
          <div key={question} className="rounded-2xl border border-sky-400/12 bg-sky-400/8 px-3 py-2 text-sm leading-6 text-sky-100">
            {question}
          </div>
        ))}
      </div>
    </div>
  );
}

function DetailBlock({ title, text, pre = false }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">{title}</div>
      <div className={`mt-2 rounded-2xl border border-white/8 bg-black/20 p-3 text-sm leading-6 text-zinc-300 ${pre ? "whitespace-pre-wrap" : ""}`}>
        {text}
      </div>
    </div>
  );
}

export default function AgentsLab({ projectId }) {
  const [activeTab, setActiveTab] = useState("documents");
  const [scenarios, setScenarios] = useState([]);
  const [scenarioGroups, setScenarioGroups] = useState([]);
  const [selectedScenario, setSelectedScenario] = useState(null);
  const [runs, setRuns] = useState([]);
  const [conversationId, setConversationId] = useState("");
  const [candidatePrompt, setCandidatePrompt] = useState("");
  const [sandboxEngine, setSandboxEngine] = useState("local");
  const [sandboxResult, setSandboxResult] = useState(null);
  const [analyzeResult, setAnalyzeResult] = useState(null);
  const [difyStatus, setDifyStatus] = useState(null);
  const [difyResult, setDifyResult] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [documentDetail, setDocumentDetail] = useState(null);
  const [documentDraft, setDocumentDraft] = useState(EMPTY_DRAFT);
  const [savedDocumentDraft, setSavedDocumentDraft] = useState(EMPTY_DRAFT);
  const [documentSearch, setDocumentSearch] = useState("");
  const [documentResult, setDocumentResult] = useState(null);
  const [documentError, setDocumentError] = useState("");
  const [documentLoading, setDocumentLoading] = useState(false);
  const [scenarioForm, setScenarioForm] = useState({
    title: "",
    intent: "context_question",
    trigger_summary: "",
    recommended_reply: "",
    tags: "",
    status: "draft",
  });
  const [busy, setBusy] = useState("");

  const loadDocuments = async (keyword = documentSearch) => {
    try {
      setDocumentError("");
      const payload = await api.getDifyDocuments({ limit: 100, keyword });
      const items = payload.data || [];
      setDocuments(items);
      setSelectedDocumentId((current) => {
        if (current && items.some((item) => item.id === current)) return current;
        return items[0]?.id || "";
      });
    } catch (error) {
      setDocuments([]);
      setDocumentError(error.message);
    }
  };

  const load = async () => {
    const [scenarioData, groupedScenarioData, runData, difyStatusData] = await Promise.all([
      api.getScenarios("", projectId),
      api.getGroupedScenarios("", projectId),
      api.getAgentRuns({ project_id: projectId }),
      api.getDifyConnectionStatus().catch(() => api.getDifyStatus()),
    ]);
    setScenarios(scenarioData);
    setScenarioGroups(groupedScenarioData);
    setRuns(runData);
    setDifyStatus(difyStatusData);
    setSelectedScenario((current) => {
      if (current && scenarioData.some((item) => item.id === current.id)) {
        return scenarioData.find((item) => item.id === current.id);
      }
      return scenarioData[0] || null;
    });
    if (difyStatusData.configured) {
      await loadDocuments(documentSearch);
    } else {
      setDocuments([]);
      setDocumentError("");
    }
  };

  useEffect(() => { load(); }, [projectId]);

  useEffect(() => {
    if (!selectedDocumentId) {
      setDocumentDetail(null);
      return;
    }
    let cancelled = false;
    setDocumentLoading(true);
    api.getDifyDocument(selectedDocumentId)
      .then((detail) => {
        if (cancelled) return;
        const nextDraft = {
          name: detail.document?.name || "document.md",
          text: detail.text || "",
        };
        setDocumentDetail(detail);
        setDocumentDraft(nextDraft);
        setSavedDocumentDraft(nextDraft);
        setDocumentResult(null);
      })
      .catch((error) => {
        if (!cancelled) setDocumentError(error.message);
      })
      .finally(() => {
        if (!cancelled) setDocumentLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDocumentId]);

  const documentGroups = useMemo(() => groupDocuments(documents), [documents]);
  const activeCount = scenarios.filter((item) => item.status === "active").length;
  const archivedCount = scenarios.filter((item) => item.status === "legacy").length;
  const selectedId = selectedScenario?.id;
  const selectedDocument = documents.find((item) => item.id === selectedDocumentId) || documentDetail?.document || null;
  const hasDocumentChanges = documentDraft.name !== savedDocumentDraft.name || documentDraft.text !== savedDocumentDraft.text;

  const runSandbox = async () => {
    if (!conversationId) return;
    setBusy("sandbox");
    try {
      const result = await api.replaySandbox({
        conversation_id: Number(conversationId),
        candidate_prompt: candidatePrompt,
        dry_run_tools: true,
        engine: sandboxEngine,
        model: sandboxEngine === "n8n" ? "n8n-agent" : "local-heuristic-agent",
      });
      setSandboxResult(result);
      await load();
    } finally {
      setBusy("");
    }
  };

  const mineScenario = async () => {
    if (!conversationId) return;
    setBusy("mine");
    try {
      const scenario = await api.mineScenario(Number(conversationId));
      setSelectedScenario(scenario);
      setActiveTab("scenarios");
      await load();
    } finally {
      setBusy("");
    }
  };

  const createScenario = async () => {
    setBusy("create");
    try {
      const scenario = await api.createScenario({ ...scenarioForm, project_id: projectId });
      setSelectedScenario(scenario);
      setScenarioForm({ title: "", intent: "context_question", trigger_summary: "", recommended_reply: "", tags: "", status: "draft" });
      await load();
    } finally {
      setBusy("");
    }
  };

  const seedFounderPack = async () => {
    setBusy("seed-pack");
    try {
      await api.seedFounderResearchPack(projectId);
      await load();
      setActiveTab("scenarios");
    } finally {
      setBusy("");
    }
  };

  const analyzeConversations = async () => {
    setBusy("analyze");
    try {
      const result = await api.analyzeConversationsForScenarios(50, projectId);
      setAnalyzeResult(result);
      await load();
      setActiveTab("scenarios");
    } finally {
      setBusy("");
    }
  };

  const syncDify = async () => {
    setBusy("dify-sync");
    try {
      const result = await api.syncDifyScenarios("active");
      setDifyResult(result);
      await load();
    } finally {
      setBusy("");
    }
  };

  const activateScenario = async (id) => {
    const scenario = await api.activateScenario(id);
    setSelectedScenario(scenario);
    await load();
  };

  const replaySource = (id) => {
    setConversationId(String(id));
    setActiveTab("sandbox");
  };

  const createNewDocument = () => {
    const nextDraft = {
      name: "new-knowledge-note.md",
      text: "# Новый документ\n\nОпиши здесь правило, пример переписки или контекст для агента.",
    };
    setSelectedDocumentId("");
    setDocumentDetail(null);
    setDocumentDraft(nextDraft);
    setSavedDocumentDraft(EMPTY_DRAFT);
    setDocumentResult(null);
    setDocumentError("");
  };

  const saveDocument = async () => {
    if (!documentDraft.name.trim() || !documentDraft.text.trim()) return;
    setBusy("document-save");
    try {
      const payload = {
        name: documentDraft.name.trim(),
        text: documentDraft.text.trim(),
      };
      const result = selectedDocumentId
        ? await api.updateDifyDocument(selectedDocumentId, payload)
        : await api.createDifyDocument(payload);
      setDocumentResult(result);
      setSavedDocumentDraft(payload);
      await loadDocuments(documentSearch);
      if (!selectedDocumentId && result.document_id) {
        setSelectedDocumentId(result.document_id);
      } else if (selectedDocumentId) {
        const detail = await api.getDifyDocument(selectedDocumentId);
        const nextDraft = {
          name: detail.document?.name || payload.name,
          text: detail.text || payload.text,
        };
        setDocumentDetail(detail);
        setDocumentDraft(nextDraft);
        setSavedDocumentDraft(nextDraft);
      }
    } finally {
      setBusy("");
    }
  };

  const renderTab = () => {
    if (activeTab === "documents") {
      return (
        <KnowledgeDocumentsWorkspace
          difyStatus={difyStatus}
          documents={documents}
          documentGroups={documentGroups}
          selectedDocument={selectedDocument}
          selectedDocumentId={selectedDocumentId}
          documentDetail={documentDetail}
          documentDraft={documentDraft}
          setDocumentDraft={setDocumentDraft}
          setSelectedDocumentId={setSelectedDocumentId}
          documentSearch={documentSearch}
          setDocumentSearch={setDocumentSearch}
          documentError={documentError}
          documentLoading={documentLoading}
          documentResult={documentResult}
          hasDocumentChanges={hasDocumentChanges}
          busy={busy}
          createNewDocument={createNewDocument}
          saveDocument={saveDocument}
          reloadDocuments={() => loadDocuments(documentSearch)}
        />
      );
    }

    if (activeTab === "scenarios") {
      return (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_580px]">
          <div className="space-y-5">
            <Card
              title="Старые сценарии"
              action={
                <div className="flex flex-wrap gap-2">
                  <button className="btn-ghost" onClick={seedFounderPack} disabled={busy === "seed-pack"}>Загрузить базовый пакет</button>
                  <button className="btn-primary" onClick={analyzeConversations} disabled={busy === "analyze"}>{busy === "analyze" ? "Анализирую..." : "Проанализировать переписки"}</button>
                </div>
              }
            >
              <div className="mb-5 rounded-3xl border border-white/8 bg-white/[0.03] p-4 text-sm leading-6 text-zinc-400">
                Это старый структурированный слой. Он оставлен для совместимости и переноса в Dify. Новую информацию лучше хранить во вкладке «Документы».
              </div>
              {analyzeResult ? (
                <div className="mb-4 grid gap-3 sm:grid-cols-4">
                  <Metric label="Создано" value={analyzeResult.created} />
                  <Metric label="Обновлено" value={analyzeResult.updated || 0} />
                  <Metric label="Пропущено" value={analyzeResult.skipped} />
                  <Metric label="В очереди" value={analyzeResult.total_suggested} />
                </div>
              ) : null}
              <div className="space-y-3">
                {scenarioGroups.length === 0 ? (
                  <EmptyState
                    compact
                    icon="С"
                    title="Старые сценарии не загружены"
                    description="Можно загрузить базовый пакет или анализировать переписки. Основной редактор базы находится во вкладке «Документы»."
                    action={<button className="btn-primary" onClick={seedFounderPack} disabled={busy === "seed-pack"}>Загрузить базовый пакет</button>}
                  />
                ) : scenarioGroups.map((group) => (
                  <details key={group.key} className="rounded-3xl border border-white/8 bg-white/[0.03] p-4" open={["core", "faq", "scheduling"].includes(group.key)}>
                    <summary className="cursor-pointer list-none">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-white">{group.label}</div>
                          {group.description ? <div className="mt-1 text-xs leading-5 text-zinc-500">{group.description}</div> : null}
                        </div>
                        <span className="rounded-full border border-white/10 bg-black/25 px-2.5 py-1 text-xs text-zinc-300">{group.count}</span>
                      </div>
                    </summary>
                    <div className="mt-4 grid gap-3 lg:grid-cols-2">
                      {group.cards.map((scenario) => (
                        <ScenarioItem
                          key={scenario.id}
                          scenario={scenario}
                          selected={selectedId === scenario.id}
                          onSelect={setSelectedScenario}
                          onActivate={activateScenario}
                        />
                      ))}
                    </div>
                  </details>
                ))}
              </div>
            </Card>
            <ManualScenarioCard
              scenarioForm={scenarioForm}
              setScenarioForm={setScenarioForm}
              createScenario={createScenario}
              busy={busy}
            />
          </div>
          <ScenarioDetail scenario={selectedScenario} onActivate={activateScenario} onReplaySource={replaySource} />
        </div>
      );
    }

    if (activeTab === "sandbox") {
      return (
        <Card title="Песочница">
          <div className="grid gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
            <div className="space-y-3">
              <input
                className={inputCls}
                placeholder="Номер переписки"
                value={conversationId}
                onChange={(e) => setConversationId(e.target.value)}
              />
              <select
                className={inputCls}
                value={sandboxEngine}
                onChange={(e) => setSandboxEngine(e.target.value)}
              >
                <option value="local">Локальная эвристика</option>
                <option value="n8n">n8n вебхук</option>
              </select>
              <textarea
                className={`${inputCls} min-h-[140px] resize-y`}
                placeholder="Временная замена инструкции, необязательно"
                value={candidatePrompt}
                onChange={(e) => setCandidatePrompt(e.target.value)}
              />
              <div className="flex flex-wrap gap-2">
                <button className="btn-primary" disabled={!conversationId || busy === "sandbox"} onClick={runSandbox}>
                  {busy === "sandbox" ? "Проверяю..." : "Проверить без отправки"}
                </button>
                <button className="btn-ghost" disabled={!conversationId || busy === "mine"} onClick={mineScenario}>
                  {busy === "mine" ? "Извлекаю..." : "Создать старый сценарий"}
                </button>
              </div>
            </div>
            <JsonBlock data={sandboxResult} />
          </div>
        </Card>
      );
    }

    if (activeTab === "runs") {
      return (
        <Card title="Журнал решений">
          <SectionLabel title="Последние записи" description="Логи проверок и решений. Реальные ответы через Telegram здесь не отправляются." />
          <div className="space-y-3">
            {runs.length === 0 ? (
              <EmptyState compact icon="Ж" title="Логов пока нет" description="Запусти проверку в песочнице, чтобы увидеть первую запись." />
            ) : runs.map((run) => (
              <details key={run.id} className="rounded-2xl border border-white/8 bg-black/20 p-4">
                <summary className="cursor-pointer text-sm font-medium text-zinc-200">
                  #{run.id} {run.run_type} · переписка {run.conversation_id || "нет"} · {run.status}
                </summary>
                <div className="mt-3 grid gap-3 lg:grid-cols-2">
                  <JsonBlock data={run.input} />
                  <JsonBlock data={run.output} />
                </div>
              </details>
            ))}
          </div>
        </Card>
      );
    }

    return (
      <DifyConnectionCard
        difyStatus={difyStatus}
        difyResult={difyResult}
        busy={busy}
        syncDify={syncDify}
        documentsCount={documents.length}
      />
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="База знаний"
        title="База знаний"
        description="Единый редактор документов Dify. Открыл документ, поправил текст, сохранил — база знаний обновилась без отдельного ручного копирования."
        actions={
          <div className="flex flex-wrap gap-2">
            <button className="btn-ghost" onClick={() => loadDocuments(documentSearch)}>
              Обновить документы
            </button>
            <button className="btn-primary" onClick={createNewDocument}>
              Новый документ
            </button>
          </div>
        }
        stats={[
          { label: "Документы", value: documents.length, tone: documents.length ? "blue" : "neutral", caption: difyStatus?.configured ? "Из Dify" : "Dify не подключен" },
          { label: "Старые сценарии", value: scenarios.length, tone: scenarios.length ? "violet" : "neutral", caption: `${activeCount} активных / ${archivedCount} архивных` },
          { label: "Записи", value: runs.length, tone: runs.length ? "blue" : "neutral", caption: "Журнал решений" },
          { label: "Подключение", value: difyStatus?.configured ? "Dify" : "Нет", tone: difyStatus?.configured ? "emerald" : "amber", caption: difyStatus?.configured ? "Ключ задан" : "Нужны переменные" },
        ]}
      />

      <div className="rounded-[28px] border border-white/10 bg-black/20 p-2">
        <div className="grid gap-2 md:grid-cols-5">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`rounded-2xl px-4 py-3 text-left transition ${
                activeTab === tab.key ? "bg-white/10 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]" : "text-zinc-500 hover:bg-white/[0.04] hover:text-zinc-200"
              }`}
            >
              <div className="text-sm font-semibold">{tab.label}</div>
              <div className="mt-1 text-xs opacity-70">{tab.hint}</div>
            </button>
          ))}
        </div>
      </div>

      {renderTab()}
    </div>
  );
}

function KnowledgeDocumentsWorkspace({
  difyStatus,
  documents,
  documentGroups,
  selectedDocument,
  selectedDocumentId,
  documentDetail,
  documentDraft,
  setDocumentDraft,
  setSelectedDocumentId,
  documentSearch,
  setDocumentSearch,
  documentError,
  documentLoading,
  documentResult,
  hasDocumentChanges,
  busy,
  createNewDocument,
  saveDocument,
  reloadDocuments,
}) {
  const configured = Boolean(difyStatus?.configured);
  const segmentCount = documentDetail?.segments?.length || selectedDocument?.segment_count || 0;

  return (
    <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
      <div className="space-y-5">
        <Card
          title="Документы"
          action={<button className="btn-primary text-sm" onClick={createNewDocument}>Новый</button>}
        >
          <div className={`mb-4 rounded-3xl border p-4 ${configured ? "border-emerald-400/15 bg-emerald-400/10" : "border-amber-400/15 bg-amber-400/10"}`}>
            <div className={`text-sm font-medium ${configured ? "text-emerald-100" : "text-amber-100"}`}>
              {configured ? "Dify подключен" : "Dify не подключен"}
            </div>
            <div className={`mt-2 text-sm leading-6 ${configured ? "text-emerald-100/70" : "text-amber-100/70"}`}>
              {configured
                ? "Список ниже читается из подключенной базы знаний. Сохранение в редакторе сразу обновляет документ в Dify."
                : "Нужно задать DIFY_API_BASE_URL, DIFY_API_KEY и DIFY_DATASET_ID на сервере."}
            </div>
          </div>

          <div className="mb-4 flex gap-2">
            <input
              className={inputCls}
              placeholder="Поиск по документам"
              value={documentSearch}
              onChange={(e) => setDocumentSearch(e.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") reloadDocuments();
              }}
            />
            <button className="btn-ghost shrink-0 text-sm" onClick={reloadDocuments}>Найти</button>
          </div>

          {documentError ? (
            <div className="mb-4 rounded-2xl border border-rose-400/20 bg-rose-400/10 p-3 text-sm leading-6 text-rose-100">
              {documentError}
            </div>
          ) : null}

          {documents.length === 0 ? (
            <EmptyState compact icon="Б" title="Документы не найдены" description="Если Dify подключен, нажми «Новый» и создай первый документ прямо здесь." />
          ) : (
            <div className="max-h-[680px] space-y-3 overflow-auto pr-1">
              {documentGroups.map((group) => (
                <details key={group.folder} open className="rounded-3xl border border-white/8 bg-white/[0.03] p-3">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-1 py-1">
                    <span className="text-sm font-semibold text-white">{group.folder}</span>
                    <span className="rounded-full border border-white/10 bg-black/25 px-2.5 py-1 text-xs text-zinc-300">{group.items.length}</span>
                  </summary>
                  <div className="mt-2 space-y-2">
                    {group.items.map((document) => (
                      <button
                        key={document.id}
                        type="button"
                        onClick={() => setSelectedDocumentId(document.id)}
                        className={`w-full rounded-2xl border p-3 text-left transition ${
                          selectedDocumentId === document.id
                            ? "border-sky-400/35 bg-sky-400/10"
                            : "border-white/8 bg-black/20 hover:border-white/16 hover:bg-white/[0.04]"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-zinc-100">{document.name}</div>
                            <div className="mt-1 truncate text-xs text-zinc-500">{document.id}</div>
                          </div>
                          <Badge className={docStatusTone(document.indexing_status)}>{docStatusLabel(document.indexing_status)}</Badge>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-zinc-500">
                          <span>{document.word_count || 0} слов</span>
                          <span>{document.segment_count || 0} сегм.</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Surface className="min-h-[760px] p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-[0.22em] text-zinc-500">Редактор документа</div>
            <h2 className="mt-3 text-2xl font-semibold leading-tight text-white">
              {documentDraft.name || selectedDocument?.name || "Новый документ"}
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">
              Это прямой редактор базы знаний. После сохранения текст отправляется в Dify, отдельная вкладка синхронизации для этого не нужна.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {hasDocumentChanges ? <Badge className="border-amber-400/20 bg-amber-400/10 text-amber-200">есть изменения</Badge> : null}
            {documentLoading ? <Badge className="border-sky-400/20 bg-sky-400/10 text-sky-200">загрузка</Badge> : null}
            <button
              className="btn-primary"
              disabled={busy === "document-save" || !documentDraft.name.trim() || !documentDraft.text.trim()}
              onClick={saveDocument}
            >
              {busy === "document-save" ? "Сохраняю..." : "Сохранить в Dify"}
            </button>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_180px]">
          <input
            className={inputCls}
            placeholder="Название документа"
            value={documentDraft.name}
            onChange={(e) => setDocumentDraft({ ...documentDraft, name: e.target.value })}
          />
          <InfoPill label="Сегменты" value={segmentCount || "нет"} />
          <InfoPill label="Статус" value={docStatusLabel(selectedDocument?.indexing_status)} />
        </div>

        <textarea
          className={`${inputCls} mt-4 min-h-[560px] resize-y font-mono text-[13px] leading-6`}
          placeholder="Текст документа"
          value={documentDraft.text}
          onChange={(e) => setDocumentDraft({ ...documentDraft, text: e.target.value })}
        />

        {documentResult ? (
          <div className="mt-4 rounded-2xl border border-emerald-400/20 bg-emerald-400/10 p-3 text-sm leading-6 text-emerald-100">
            Документ сохранен в Dify. ID: {documentResult.document_id || selectedDocumentId || "не указан"}
          </div>
        ) : null}

        {documentDetail?.segments?.length ? (
          <details className="mt-4 rounded-2xl border border-white/8 bg-black/20 p-4">
            <summary className="cursor-pointer text-sm font-medium text-zinc-200">Посмотреть сегменты Dify</summary>
            <div className="mt-3 space-y-3">
              {documentDetail.segments.map((segment) => (
                <div key={segment.id || segment.position} className="rounded-2xl border border-white/8 bg-white/[0.03] p-3">
                  <div className="mb-2 flex items-center justify-between gap-2 text-xs text-zinc-500">
                    <span>Сегмент {segment.position || segment.id}</span>
                    <span>{segment.word_count || 0} слов</span>
                  </div>
                  <div className="whitespace-pre-wrap text-sm leading-6 text-zinc-300">{segment.content}</div>
                </div>
              ))}
            </div>
          </details>
        ) : null}
      </Surface>
    </div>
  );
}

function InfoPill({ label, value }) {
  return (
    <div className="rounded-2xl border border-white/8 bg-black/20 px-3 py-2 text-xs">
      <div className="text-zinc-500">{label}</div>
      <div className="mt-1 truncate text-sm text-zinc-200">{value}</div>
    </div>
  );
}

function ManualScenarioCard({ scenarioForm, setScenarioForm, createScenario, busy }) {
  return (
    <Card title="Ручной старый сценарий">
      <SectionLabel
        title="Не основной путь"
        description="Этот блок оставлен для совместимости. Для новой базы лучше создавать документы Dify во вкладке «Документы»."
      />
      <div className="grid gap-3 lg:grid-cols-2">
        <input className={inputCls} placeholder="Название" value={scenarioForm.title} onChange={(e) => setScenarioForm({ ...scenarioForm, title: e.target.value })} />
        <select className={inputCls} value={scenarioForm.intent} onChange={(e) => setScenarioForm({ ...scenarioForm, intent: e.target.value })}>
          <option value="context_question">Уточнение контекста</option>
          <option value="sales_objection">Возражение: продажа</option>
          <option value="book_meeting">Назначить встречу</option>
          <option value="closing_not_interested">Вежливо завершить</option>
        </select>
        <textarea className={`${inputCls} min-h-[90px]`} placeholder="Когда применять" value={scenarioForm.trigger_summary} onChange={(e) => setScenarioForm({ ...scenarioForm, trigger_summary: e.target.value })} />
        <textarea className={`${inputCls} min-h-[90px]`} placeholder="Как отвечать" value={scenarioForm.recommended_reply} onChange={(e) => setScenarioForm({ ...scenarioForm, recommended_reply: e.target.value })} />
        <input className={inputCls} placeholder="Служебные метки, необязательно" value={scenarioForm.tags} onChange={(e) => setScenarioForm({ ...scenarioForm, tags: e.target.value })} />
        <button className="btn-primary" disabled={!scenarioForm.title || !scenarioForm.trigger_summary || !scenarioForm.recommended_reply || busy === "create"} onClick={createScenario}>
          Сохранить черновик
        </button>
      </div>
    </Card>
  );
}

function DifyConnectionCard({ difyStatus, difyResult, busy, syncDify, documentsCount }) {
  const configured = Boolean(difyStatus?.configured);
  return (
    <Card
      title="Подключение к Dify"
      action={
        <button className="btn-primary" onClick={syncDify} disabled={!configured || busy === "dify-sync"}>
          {busy === "dify-sync" ? "Отправляю..." : "Синхронизировать старые сценарии"}
        </button>
      }
    >
      <div className={`rounded-3xl border p-4 ${configured ? "border-emerald-400/15 bg-emerald-400/10" : "border-amber-400/15 bg-amber-400/10"}`}>
        <div className={`text-sm font-medium ${configured ? "text-emerald-100" : "text-amber-100"}`}>
          {configured ? "Dify настроен" : "Dify не настроен"}
        </div>
        <div className={`mt-2 text-sm leading-6 ${configured ? "text-emerald-100/70" : "text-amber-100/70"}`}>
          {configured
            ? "Редактор документов работает напрямую с Dify. Кнопка справа нужна только для переноса старых сценариев."
            : "Нужно указать DIFY_API_BASE_URL, DIFY_API_KEY и DIFY_DATASET_ID в окружении серверной части."}
        </div>
        {difyStatus ? (
          <div className="mt-3 grid gap-2 text-xs text-zinc-400 sm:grid-cols-4">
            <div className="rounded-2xl border border-white/8 bg-black/20 p-3">
              <div className="text-zinc-500">Адрес API</div>
              <div className="mt-1 truncate text-zinc-200">{difyStatus.api_base_url || "не задан"}</div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/20 p-3">
              <div className="text-zinc-500">База Dify</div>
              <div className="mt-1 truncate text-zinc-200">{difyStatus.dataset_id || "не задана"}</div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/20 p-3">
              <div className="text-zinc-500">Ключ API</div>
              <div className="mt-1 text-zinc-200">{difyStatus.has_api_key ? "задан" : "не задан"}</div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/20 p-3">
              <div className="text-zinc-500">Документы</div>
              <div className="mt-1 text-zinc-200">{documentsCount}</div>
            </div>
          </div>
        ) : null}
      </div>
      {difyResult ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-4">
          <Metric label="Всего" value={difyResult.total} />
          <Metric label="Создано" value={difyResult.created} tone="emerald" />
          <Metric label="Обновлено" value={difyResult.updated} tone="sky" />
          <Metric label="Ошибки" value={difyResult.failed} tone={difyResult.failed ? "rose" : "zinc"} />
        </div>
      ) : null}
    </Card>
  );
}

function Metric({ label, value, tone = "zinc" }) {
  const tones = {
    zinc: "border-white/8 bg-white/4 text-zinc-200",
    emerald: "border-emerald-400/20 bg-emerald-400/10 text-emerald-100",
    rose: "border-rose-400/20 bg-rose-400/10 text-rose-100",
    sky: "border-sky-400/20 bg-sky-400/10 text-sky-100",
  };
  return (
    <div className={`rounded-2xl border p-3 text-sm ${tones[tone] || tones.zinc}`}>
      {label} <span className="float-right text-white">{value}</span>
    </div>
  );
}
