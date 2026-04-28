import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { EmptyState, PageHeader, SectionLabel, Surface } from "../components/workspace";

const inputCls = "w-full rounded-2xl border border-white/10 bg-black/25 px-3.5 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition focus:border-sky-400/40 focus:bg-white/[0.05]";

const TABS = [
  { key: "scenarios", label: "Сценарии", hint: "База правил и ответов" },
  { key: "improve", label: "Очередь улучшений", hint: "Автопредложения" },
  { key: "sandbox", label: "Песочница", hint: "Проверка без отправки" },
  { key: "evals", label: "Проверки", hint: "Качество ответов" },
  { key: "runs", label: "Журнал", hint: "Логи решений" },
];

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

function statusTone(status) {
  if (status === "active") return "border-emerald-400/20 bg-emerald-400/10 text-emerald-200";
  if (status === "suggested") return "border-amber-400/20 bg-amber-400/10 text-amber-200";
  if (status === "draft") return "border-sky-400/20 bg-sky-400/10 text-sky-200";
  return "border-white/10 bg-white/5 text-zinc-300";
}

function statusLabel(scenario) {
  return scenario.status_label || {
    active: "Активен",
    suggested: "Предложен",
    draft: "Черновик",
    legacy: "Легаси",
  }[scenario.status] || scenario.status || "Без статуса";
}

function intentLabel(scenario) {
  return scenario.intent_label || scenario.intent || "Без типа";
}

function Badge({ children, className = "" }) {
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-medium ${className}`}>
      {children}
    </span>
  );
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
      {scenario.status !== "active" ? (
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
        <EmptyState compact icon="С" title="Выбери сценарий" description="Кликни по сценарию, чтобы увидеть вопросы, условия применения, ответ и источник." />
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
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">ID и синхронизация</div>
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
        {scenario.status !== "active" ? (
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
  const [activeTab, setActiveTab] = useState("scenarios");
  const [scenarios, setScenarios] = useState([]);
  const [scenarioGroups, setScenarioGroups] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [selectedScenario, setSelectedScenario] = useState(null);
  const [runs, setRuns] = useState([]);
  const [conversationId, setConversationId] = useState("");
  const [candidatePrompt, setCandidatePrompt] = useState("");
  const [sandboxEngine, setSandboxEngine] = useState("local");
  const [sandboxResult, setSandboxResult] = useState(null);
  const [evalResult, setEvalResult] = useState(null);
  const [analyzeResult, setAnalyzeResult] = useState(null);
  const [difyStatus, setDifyStatus] = useState(null);
  const [difyResult, setDifyResult] = useState(null);
  const [scenarioForm, setScenarioForm] = useState({
    title: "",
    intent: "context_question",
    trigger_summary: "",
    recommended_reply: "",
    tags: "",
    status: "draft",
  });
  const [busy, setBusy] = useState("");

  const load = async () => {
    const [scenarioData, groupedScenarioData, suggestionData, runData, difyStatusData] = await Promise.all([
      api.getScenarios("", projectId),
      api.getGroupedScenarios("", projectId),
      api.getScenarios("suggested", projectId),
      api.getAgentRuns({ project_id: projectId }),
      api.getDifyStatus(),
    ]);
    setScenarios(scenarioData);
    setScenarioGroups(groupedScenarioData);
    setSuggestions(suggestionData);
    setRuns(runData);
    setDifyStatus(difyStatusData);
    setSelectedScenario((current) => {
      if (current && scenarioData.some((item) => item.id === current.id)) {
        return scenarioData.find((item) => item.id === current.id);
      }
      return scenarioData[0] || null;
    });
  };

  useEffect(() => { load(); }, [projectId]);

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
      setActiveTab("improve");
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

  const runEvals = async () => {
    setBusy("evals");
    try {
      setEvalResult(await api.runEvals());
    } finally {
      setBusy("");
    }
  };

  const activeCount = scenarios.filter((item) => item.status === "active").length;
  const draftCount = scenarios.filter((item) => item.status === "draft").length;
  const selectedId = selectedScenario?.id;

  const tabContent = useMemo(() => ({
    scenarios: (
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_580px]">
        <div className="space-y-5">
          <DifySyncCard
            difyStatus={difyStatus}
            difyResult={difyResult}
            busy={busy}
            syncDify={syncDify}
          />
          <Card
            title="Библиотека сценариев"
            action={
              <div className="flex flex-wrap gap-2">
                <button className="btn-ghost" onClick={seedFounderPack} disabled={busy === "seed-pack"}>Загрузить базу</button>
                <button className="btn-primary" onClick={analyzeConversations} disabled={busy === "analyze"}>{busy === "analyze" ? "Анализирую..." : "Проанализировать переписки"}</button>
              </div>
            }
          >
            <div className="space-y-3">
              {scenarioGroups.length === 0 ? (
                <EmptyState
                  compact
                  icon="С"
                  title="Сценарии не загружены"
                  description="Загрузи базовый пакет или проанализируй переписки, чтобы получить предложенные сценарии."
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
    ),
    improve: (
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_580px]">
        <Card
          title="Очередь улучшений"
          action={<button className="btn-primary" onClick={analyzeConversations} disabled={busy === "analyze"}>{busy === "analyze" ? "Анализирую..." : "Проанализировать переписки"}</button>}
        >
          <div className="mb-5 rounded-3xl border border-amber-400/15 bg-amber-400/10 p-4">
            <div className="text-sm font-medium text-amber-100">Как работает автоматическое пополнение</div>
            <div className="mt-2 text-sm leading-6 text-amber-100/70">
              Система смотрит последние переписки, находит повторяющиеся вопросы, возражения и согласия на созвон, а затем создает предложенные сценарии. Они не влияют на реальные ответы, пока ты не нажмешь «Одобрить».
            </div>
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
            {suggestions.length === 0 ? (
              <EmptyState
                compact
                icon="О"
                title="Очередь пустая"
                description="Нажми «Проанализировать переписки». Если появятся новые повторяющиеся ситуации, они будут здесь с источником."
                action={<button className="btn-primary" onClick={analyzeConversations} disabled={busy === "analyze"}>Проанализировать переписки</button>}
              />
            ) : suggestions.map((scenario) => (
              <ScenarioItem
                key={scenario.id}
                scenario={scenario}
                selected={selectedId === scenario.id}
                onSelect={setSelectedScenario}
                onActivate={activateScenario}
              />
            ))}
          </div>
        </Card>
        <ScenarioDetail scenario={selectedScenario} onActivate={activateScenario} onReplaySource={replaySource} />
      </div>
    ),
    sandbox: (
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
              <option value="local">Local heuristic</option>
              <option value="n8n">n8n webhook</option>
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
                {busy === "mine" ? "Извлекаю..." : "Создать черновик сценария"}
              </button>
            </div>
          </div>
          <JsonBlock data={sandboxResult} />
        </div>
      </Card>
    ),
    evals: (
      <Card title="Проверки качества" action={<button className="btn-primary" onClick={runEvals} disabled={busy === "evals"}>{busy === "evals" ? "Проверяю..." : "Запустить проверки"}</button>}>
        {evalResult ? (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-4">
              <Metric label="Всего" value={evalResult.total} />
              <Metric label="Прошли" value={evalResult.passed} tone="emerald" />
              <Metric label="Провалены" value={evalResult.failed} tone="rose" />
              <Metric label="Оценка" value={evalResult.score} tone="sky" />
            </div>
            <JsonBlock data={evalResult.failures} />
          </div>
        ) : (
          <EmptyState compact icon="П" title="Проверок еще не было" description="Запусти проверки, чтобы увидеть оценку действий, ответов и ограничений." />
        )}
      </Card>
    ),
    runs: (
      <Card title="Журнал решений агента">
        <SectionLabel title="Последние записи" description="Каждая проверка в песочнице пишет лог: входные данные и результат можно посмотреть здесь." />
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
    ),
  }), [activeTab, analyzeResult, busy, candidatePrompt, conversationId, difyResult, difyStatus, evalResult, runs, sandboxEngine, sandboxResult, scenarioForm, scenarioGroups, selectedId, selectedScenario, suggestions]);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Управление агентом"
        title="Лаборатория агента"
        description="Библиотека сценариев, очередь улучшений, песочница, проверки и журнал решений. Предложенные сценарии не влияют на реальные ответы до одобрения."
        actions={
          <div className="flex flex-wrap gap-2">
            <button className="btn-ghost" onClick={seedFounderPack} disabled={busy === "seed-pack"}>
              {busy === "seed-pack" ? "Загружаю..." : "Загрузить базу"}
            </button>
            <button className="btn-primary" onClick={analyzeConversations} disabled={busy === "analyze"}>
              {busy === "analyze" ? "Анализирую..." : "Проанализировать переписки"}
            </button>
          </div>
        }
        stats={[
          { label: "Сценарии", value: scenarios.length, tone: scenarios.length ? "violet" : "neutral", caption: `${activeCount} активных / ${draftCount} черновиков` },
          { label: "На одобрение", value: suggestions.length, tone: suggestions.length ? "amber" : "neutral", caption: "Ждут решения" },
          { label: "Записи", value: runs.length, tone: runs.length ? "blue" : "neutral", caption: "Журнал решений" },
          { label: "Песочница", value: "Без отправки", tone: "emerald", caption: "Не пишет в Telegram" },
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

      {tabContent[activeTab]}
    </div>
  );
}

function ManualScenarioCard({ scenarioForm, setScenarioForm, createScenario, busy }) {
  return (
    <Card title="Ручной сценарий">
      <SectionLabel
        title="Необязательно"
        description="Для точечной ручной карточки. Автоматические предложения находятся во вкладке «Очередь улучшений»."
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

function DifySyncCard({ difyStatus, difyResult, busy, syncDify }) {
  const configured = Boolean(difyStatus?.configured);
  return (
    <Card
      title="Синхронизация с Dify"
      action={
        <button className="btn-primary" onClick={syncDify} disabled={!configured || busy === "dify-sync"}>
          {busy === "dify-sync" ? "Отправляю..." : "Отправить активные сценарии"}
        </button>
      }
    >
      <div className={`rounded-3xl border p-4 ${configured ? "border-emerald-400/15 bg-emerald-400/10" : "border-amber-400/15 bg-amber-400/10"}`}>
        <div className={`text-sm font-medium ${configured ? "text-emerald-100" : "text-amber-100"}`}>
          {configured ? "Dify настроен" : "Dify не настроен"}
        </div>
        <div className={`mt-2 text-sm leading-6 ${configured ? "text-emerald-100/70" : "text-amber-100/70"}`}>
          {configured
            ? "Активные сценарии можно отправить в базу знаний Dify. Черновики и предложения не синхронизируются."
            : "Нужно указать DIFY_API_BASE_URL, DIFY_API_KEY и DIFY_DATASET_ID в окружении серверной части."}
        </div>
        {difyStatus ? (
          <div className="mt-3 grid gap-2 text-xs text-zinc-400 sm:grid-cols-3">
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
