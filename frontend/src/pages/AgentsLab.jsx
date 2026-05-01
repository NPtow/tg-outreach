import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { EmptyState } from "../components/workspace";

const inputCls = "w-full rounded-2xl border border-white/10 bg-black/25 px-3.5 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition focus:border-sky-400/40 focus:bg-white/[0.05]";
const EMPTY_DRAFT = { name: "", text: "" };

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
  const name = (document.name || "").trim();
  const normalized = name.toLowerCase();
  if (name.includes("/")) return name.split("/").slice(0, -1).join("/") || "Корень";
  if (normalized.startsWith("core-") || normalized.includes("context") || normalized.includes("контекст")) return "Контекст";
  if (normalized.startsWith("scenario-") || normalized.includes("сценар")) return "Сценарии";
  if (normalized.includes("example") || normalized.includes("conversation") || normalized.includes("пример")) return "Примеры";
  if (normalized.includes("negative") || normalized.includes("mistake") || normalized.includes("ошиб")) return "Ошибки";
  if (normalized.includes("eval") || normalized.includes("test") || normalized.includes("провер")) return "Тесты";
  return "Корень";
}

function groupDocuments(documents) {
  const groups = new Map();
  for (const document of documents) {
    const folder = documentFolder(document);
    if (!groups.has(folder)) groups.set(folder, []);
    groups.get(folder).push(document);
  }
  return Array.from(groups.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([folder, items]) => ({
      folder,
      items: items.sort((a, b) => (a.name || "").localeCompare(b.name || "")),
    }));
}

function fileName(name = "") {
  return name.split("/").filter(Boolean).at(-1) || name || "Без названия";
}

function formatDate(value) {
  if (!value) return "нет";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function Badge({ children, className = "" }) {
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-medium ${className}`}>
      {children}
    </span>
  );
}

function ToolbarButton({ children, onClick, disabled = false, danger = false }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`rounded-2xl border px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-45 ${
        danger
          ? "border-rose-400/20 bg-rose-400/10 text-rose-100 hover:bg-rose-400/15"
          : "border-white/10 bg-white/[0.04] text-zinc-200 hover:border-white/20 hover:bg-white/[0.08]"
      }`}
    >
      {children}
    </button>
  );
}

function MarkdownPreview({ text }) {
  const lines = text.split("\n");
  if (!text.trim()) {
    return <div className="p-8 text-sm text-zinc-500">Документ пустой.</div>;
  }
  return (
    <div className="space-y-3 p-8 text-zinc-200">
      {lines.map((line, index) => {
        const key = `${index}-${line}`;
        if (!line.trim()) return <div key={key} className="h-2" />;
        if (line.startsWith("# ")) return <h1 key={key} className="text-3xl font-semibold tracking-tight text-white">{line.slice(2)}</h1>;
        if (line.startsWith("## ")) return <h2 key={key} className="pt-4 text-xl font-semibold text-white">{line.slice(3)}</h2>;
        if (line.startsWith("### ")) return <h3 key={key} className="pt-3 text-base font-semibold text-zinc-100">{line.slice(4)}</h3>;
        if (line.startsWith("- ")) return <div key={key} className="pl-4 text-sm leading-7 text-zinc-300">• {line.slice(2)}</div>;
        if (/^\d+\.\s/.test(line)) return <div key={key} className="pl-4 text-sm leading-7 text-zinc-300">{line}</div>;
        if (line.startsWith("```")) return <div key={key} className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 font-mono text-xs text-zinc-400">{line}</div>;
        return <p key={key} className="text-sm leading-7 text-zinc-300">{line}</p>;
      })}
    </div>
  );
}

export default function AgentsLab() {
  const [difyStatus, setDifyStatus] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [documentDetail, setDocumentDetail] = useState(null);
  const [documentDraft, setDocumentDraft] = useState(EMPTY_DRAFT);
  const [savedDocumentDraft, setSavedDocumentDraft] = useState(EMPTY_DRAFT);
  const [documentSearch, setDocumentSearch] = useState("");
  const [documentError, setDocumentError] = useState("");
  const [documentMessage, setDocumentMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [mode, setMode] = useState("edit");

  const selectedDocument = documents.find((item) => item.id === selectedDocumentId) || documentDetail?.document || null;
  const documentGroups = useMemo(() => groupDocuments(documents), [documents]);
  const filteredGroups = useMemo(() => {
    const query = documentSearch.trim().toLowerCase();
    if (!query) return documentGroups;
    return groupDocuments(
      documents.filter((document) => {
        const name = (document.name || "").toLowerCase();
        const folder = documentFolder(document).toLowerCase();
        return name.includes(query) || folder.includes(query);
      })
    );
  }, [documentGroups, documents, documentSearch]);
  const hasChanges = documentDraft.name !== savedDocumentDraft.name || documentDraft.text !== savedDocumentDraft.text;

  const loadDocuments = async () => {
    setDocumentError("");
    const payload = await api.getDifyDocuments({ limit: 100 });
    const items = payload.data || [];
    setDocuments(items);
    setSelectedDocumentId((current) => {
      if (current && items.some((item) => item.id === current)) return current;
      return items[0]?.id || "";
    });
  };

  const loadAll = async () => {
    setBusy("load");
    try {
      const status = await api.getDifyConnectionStatus().catch(() => api.getDifyStatus());
      setDifyStatus(status);
      if (status.configured) {
        await loadDocuments();
      } else {
        setDocuments([]);
        setDocumentError("Dify не подключен. Проверь переменные окружения сервера.");
      }
    } catch (error) {
      setDocumentError(error.message);
    } finally {
      setBusy("");
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  useEffect(() => {
    if (!selectedDocumentId) return;
    let cancelled = false;
    setBusy("detail");
    setDocumentMessage("");
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
      })
      .catch((error) => {
        if (!cancelled) setDocumentError(error.message);
      })
      .finally(() => {
        if (!cancelled) setBusy("");
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDocumentId]);

  const createNewDocument = () => {
    const nextDraft = {
      name: "Новый документ.md",
      text: "# Новый документ\n\nДобавь сюда правило, пример, контекст или инструкцию для базы знаний.",
    };
    setSelectedDocumentId("");
    setDocumentDetail(null);
    setDocumentDraft(nextDraft);
    setSavedDocumentDraft(EMPTY_DRAFT);
    setDocumentMessage("Новый документ еще не сохранен в Dify.");
    setMode("edit");
  };

  const saveDocument = async () => {
    if (!documentDraft.name.trim() || !documentDraft.text.trim()) return;
    setBusy("save");
    setDocumentError("");
    try {
      const payload = { name: documentDraft.name.trim(), text: documentDraft.text.trim() };
      const result = selectedDocumentId
        ? await api.updateDifyDocument(selectedDocumentId, payload)
        : await api.createDifyDocument(payload);
      setSavedDocumentDraft(payload);
      setDocumentMessage("Сохранено в Dify.");
      await loadDocuments();
      if (!selectedDocumentId && result.document_id) {
        setSelectedDocumentId(result.document_id);
      }
    } catch (error) {
      setDocumentError(error.message);
    } finally {
      setBusy("");
    }
  };

  const deleteDocument = async () => {
    if (!selectedDocumentId || !selectedDocument) return;
    const ok = window.confirm(`Удалить документ «${selectedDocument.name}» из Dify?`);
    if (!ok) return;
    setBusy("delete");
    setDocumentError("");
    try {
      await api.deleteDifyDocument(selectedDocumentId);
      setDocumentDetail(null);
      setDocumentDraft(EMPTY_DRAFT);
      setSavedDocumentDraft(EMPTY_DRAFT);
      setDocumentMessage("Документ удален.");
      const payload = await api.getDifyDocuments({ limit: 100 });
      const items = payload.data || [];
      setDocuments(items);
      setSelectedDocumentId(items[0]?.id || "");
    } catch (error) {
      setDocumentError(error.message);
    } finally {
      setBusy("");
    }
  };

  const insertText = (before, after = "") => {
    setDocumentDraft((current) => ({ ...current, text: `${current.text}${current.text.endsWith("\n") || !current.text ? "" : "\n"}${before}${after}` }));
  };

  return (
    <div className="min-h-[calc(100vh-120px)] overflow-hidden rounded-[32px] border border-white/10 bg-[#0b0c10] shadow-[0_30px_120px_rgba(0,0,0,0.35)]">
      <div className="grid min-h-[calc(100vh-120px)] lg:grid-cols-[320px_minmax(0,1fr)] 2xl:grid-cols-[320px_minmax(0,1fr)_300px]">
        <aside className="border-b border-white/10 bg-black/25 p-4 lg:border-b-0 lg:border-r">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Dify</div>
              <h1 className="mt-1 text-xl font-semibold tracking-tight text-white">База знаний</h1>
            </div>
            <ToolbarButton onClick={createNewDocument}>+</ToolbarButton>
          </div>

          <div className="mt-4">
            <input
              className={inputCls}
              placeholder="Найти документ"
              value={documentSearch}
              onChange={(event) => setDocumentSearch(event.target.value)}
            />
          </div>

          <div className="mt-4 flex items-center justify-between rounded-2xl border border-white/8 bg-white/[0.03] px-3 py-2 text-xs text-zinc-400">
            <span>{documents.length} документов</span>
            <button type="button" className="text-zinc-300 transition hover:text-white" onClick={loadAll}>
              Обновить
            </button>
          </div>

          <div className="mt-4 max-h-[calc(100vh-360px)] space-y-3 overflow-auto pr-1">
            {filteredGroups.length === 0 ? (
              <EmptyState compact icon="Б" title="Пусто" description="Документы не найдены." />
            ) : filteredGroups.map((group) => (
              <details key={group.folder} open className="group">
                <summary className="flex cursor-pointer list-none items-center gap-2 rounded-xl px-2 py-1.5 text-xs font-medium uppercase tracking-[0.16em] text-zinc-500 transition hover:bg-white/[0.04] hover:text-zinc-300">
                  <span className="text-zinc-600 group-open:rotate-90">›</span>
                  <span className="truncate">{group.folder}</span>
                  <span className="ml-auto rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] text-zinc-500">{group.items.length}</span>
                </summary>
                <div className="mt-1 space-y-1 pl-2">
                  {group.items.map((document) => (
                    <button
                      key={document.id}
                      type="button"
                      onClick={() => setSelectedDocumentId(document.id)}
                      className={`flex w-full items-start gap-2 rounded-2xl px-3 py-2.5 text-left transition ${
                        selectedDocumentId === document.id
                          ? "bg-sky-400/12 text-white"
                          : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-100"
                      }`}
                    >
                      <span className="mt-0.5 text-sm text-zinc-500">□</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{fileName(document.name)}</span>
                        <span className="mt-0.5 block truncate text-xs text-zinc-600">{docStatusLabel(document.indexing_status)}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </details>
            ))}
          </div>

          <ConnectionBox difyStatus={difyStatus} />
        </aside>

        <main className="min-w-0 bg-[radial-gradient(circle_at_top_right,rgba(14,165,233,0.08),transparent_34%),linear-gradient(180deg,rgba(255,255,255,0.025),transparent)]">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-5 py-3">
            <div className="min-w-0">
              <div className="truncate text-xs text-zinc-500">
                {selectedDocument ? `${documentFolder(selectedDocument)} / ${fileName(selectedDocument.name)}` : "Новый документ"}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                {hasChanges ? <Badge className="border-amber-400/20 bg-amber-400/10 text-amber-200">не сохранено</Badge> : <Badge className="border-white/10 bg-white/5 text-zinc-400">сохранено</Badge>}
                {selectedDocument ? <Badge className={docStatusTone(selectedDocument.indexing_status)}>{docStatusLabel(selectedDocument.indexing_status)}</Badge> : <Badge className="border-sky-400/20 bg-sky-400/10 text-sky-200">новый</Badge>}
                {busy === "detail" ? <Badge className="border-sky-400/20 bg-sky-400/10 text-sky-200">загрузка</Badge> : null}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <ToolbarButton onClick={() => setMode(mode === "edit" ? "preview" : "edit")}>
                {mode === "edit" ? "Предпросмотр" : "Редактор"}
              </ToolbarButton>
              <ToolbarButton onClick={deleteDocument} disabled={!selectedDocumentId || busy === "delete"} danger>
                Удалить
              </ToolbarButton>
              <button
                type="button"
                onClick={saveDocument}
                disabled={busy === "save" || !documentDraft.name.trim() || !documentDraft.text.trim()}
                className="rounded-2xl bg-sky-400 px-4 py-2 text-sm font-semibold text-white shadow-[0_14px_35px_rgba(56,189,248,0.28)] transition hover:bg-sky-300 disabled:cursor-not-allowed disabled:opacity-45"
              >
                {busy === "save" ? "Сохраняю..." : "Сохранить"}
              </button>
            </div>
          </div>

          <div className="px-5 py-5">
            <input
              className="w-full border-none bg-transparent text-3xl font-semibold tracking-tight text-white outline-none placeholder-zinc-700"
              placeholder="Название документа"
              value={documentDraft.name}
              onChange={(event) => setDocumentDraft({ ...documentDraft, name: event.target.value })}
            />

            <div className="mt-4 flex flex-wrap gap-2">
              <ToolbarButton onClick={() => insertText("\n# Заголовок\n")}>H1</ToolbarButton>
              <ToolbarButton onClick={() => insertText("\n## Раздел\n")}>H2</ToolbarButton>
              <ToolbarButton onClick={() => insertText("\n- Пункт списка\n")}>Список</ToolbarButton>
              <ToolbarButton onClick={() => insertText("\n> Заметка\n")}>Заметка</ToolbarButton>
            </div>

            {documentError ? (
              <div className="mt-4 rounded-2xl border border-rose-400/20 bg-rose-400/10 p-3 text-sm leading-6 text-rose-100">
                {documentError}
              </div>
            ) : null}
            {documentMessage ? (
              <div className="mt-4 rounded-2xl border border-emerald-400/20 bg-emerald-400/10 p-3 text-sm leading-6 text-emerald-100">
                {documentMessage}
              </div>
            ) : null}

            <div className="mt-4 overflow-hidden rounded-[28px] border border-white/10 bg-black/20">
              {mode === "edit" ? (
                <textarea
                  className="min-h-[calc(100vh-390px)] w-full resize-y border-none bg-transparent p-8 font-mono text-[13px] leading-7 text-zinc-200 outline-none placeholder-zinc-700"
                  placeholder="Пиши здесь содержимое базы знаний"
                  value={documentDraft.text}
                  onChange={(event) => setDocumentDraft({ ...documentDraft, text: event.target.value })}
                />
              ) : (
                <div className="min-h-[calc(100vh-390px)]">
                  <MarkdownPreview text={documentDraft.text} />
                </div>
              )}
            </div>
          </div>
        </main>

        <aside className="hidden border-l border-white/10 bg-black/20 p-4 2xl:block">
          <div className="text-[11px] uppercase tracking-[0.22em] text-zinc-600">Свойства</div>
          <div className="mt-4 space-y-3">
            <Property label="ID" value={selectedDocument?.id || "новый документ"} />
            <Property label="Папка" value={selectedDocument ? documentFolder(selectedDocument) : "Корень"} />
            <Property label="Статус" value={docStatusLabel(selectedDocument?.indexing_status)} />
            <Property label="Сегменты" value={documentDetail?.segments?.length || selectedDocument?.segment_count || 0} />
            <Property label="Слова" value={selectedDocument?.word_count || 0} />
            <Property label="Обновлен" value={formatDate(selectedDocument?.updated_at)} />
          </div>

          <div className="mt-6 rounded-3xl border border-white/8 bg-white/[0.03] p-4">
            <div className="text-sm font-semibold text-white">Как теперь работать</div>
            <div className="mt-2 space-y-2 text-sm leading-6 text-zinc-400">
              <p>Название документа редактируется прямо сверху.</p>
              <p>Сохранение обновляет документ в Dify.</p>
              <p>Удаление удаляет документ из подключенной базы.</p>
            </div>
          </div>

          {documentDetail?.segments?.length ? (
            <details className="mt-4 rounded-3xl border border-white/8 bg-white/[0.03] p-4">
              <summary className="cursor-pointer text-sm font-semibold text-zinc-200">Сегменты Dify</summary>
              <div className="mt-3 max-h-[360px] space-y-3 overflow-auto">
                {documentDetail.segments.map((segment) => (
                  <div key={segment.id || segment.position} className="rounded-2xl border border-white/8 bg-black/25 p-3">
                    <div className="mb-2 text-xs text-zinc-600">Сегмент {segment.position || segment.id}</div>
                    <div className="line-clamp-4 text-xs leading-5 text-zinc-400">{segment.content}</div>
                  </div>
                ))}
              </div>
            </details>
          ) : null}
        </aside>
      </div>
    </div>
  );
}

function ConnectionBox({ difyStatus }) {
  const configured = Boolean(difyStatus?.configured);
  return (
    <div className={`mt-4 rounded-3xl border p-4 ${configured ? "border-emerald-400/15 bg-emerald-400/10" : "border-amber-400/15 bg-amber-400/10"}`}>
      <div className={`text-sm font-medium ${configured ? "text-emerald-100" : "text-amber-100"}`}>
        {configured ? "Dify подключен" : "Dify не подключен"}
      </div>
      <div className={`mt-2 text-xs leading-5 ${configured ? "text-emerald-100/65" : "text-amber-100/70"}`}>
        {configured ? "Документы читаются и сохраняются напрямую." : "Нужны переменные Dify на сервере."}
      </div>
      <div className="mt-3 space-y-2 text-[11px] text-zinc-500">
        <div className="truncate">API: {difyStatus?.api_base_url || "нет"}</div>
        <div className="truncate">База: {difyStatus?.dataset_id || "нет"}</div>
        <div>Ключ: {difyStatus?.has_api_key ? "задан" : "нет"}</div>
      </div>
    </div>
  );
}

function Property({ label, value }) {
  return (
    <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-3 py-2">
      <div className="text-[11px] uppercase tracking-[0.16em] text-zinc-600">{label}</div>
      <div className="mt-1 truncate text-sm text-zinc-200">{value}</div>
    </div>
  );
}
