import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

/* ─────────────────────────────────────────────────────────────
   TG Outreach — маркетинговый лендинг (тёмная тема, RU).
   Самодостаточная страница: рендерится на /landing вне workspace.
   ───────────────────────────────────────────────────────────── */

const APP_URL = "/"; // operator workspace живёт на корне SPA

/* ── Иконки (stroke, currentColor) ─────────────────────────── */
function Icon({ name, className = "h-6 w-6" }) {
  const paths = {
    users: (
      <>
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
      </>
    ),
    rocket: (
      <>
        <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09Z" />
        <path d="M12 15 9 12a14 14 0 0 1 9-9c1.5 0 3 .5 3 .5s.5 1.5.5 3a14 14 0 0 1-9 9Z" />
        <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5" />
      </>
    ),
    brain: (
      <>
        <path d="M12 5a3 3 0 1 0-5.997.142 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z" />
        <path d="M12 5a3 3 0 1 1 5.997.142 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z" />
      </>
    ),
    inbox: (
      <>
        <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
        <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z" />
      </>
    ),
    upload: (
      <>
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="17 8 12 3 7 8" />
        <line x1="12" y1="3" x2="12" y2="15" />
      </>
    ),
    plug: (
      <>
        <path d="M12 22v-5M9 8V2M15 8V2M18 8v4a6 6 0 0 1-12 0V8Z" />
      </>
    ),
    shield: (
      <>
        <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1Z" />
        <path d="m9 12 2 2 4-4" />
      </>
    ),
    gauge: (
      <>
        <path d="m12 14 4-4M3.34 19a10 10 0 1 1 17.32 0" />
      </>
    ),
    pause: (
      <>
        <circle cx="12" cy="12" r="10" />
        <line x1="10" y1="15" x2="10" y2="9" />
        <line x1="14" y1="15" x2="14" y2="9" />
      </>
    ),
    network: (
      <>
        <rect x="9" y="2" width="6" height="6" rx="1" />
        <rect x="2" y="16" width="6" height="6" rx="1" />
        <rect x="16" y="16" width="6" height="6" rx="1" />
        <path d="M5 16v-2a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v2M12 12V8" />
      </>
    ),
    refresh: (
      <>
        <path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5" />
        <path d="M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5" />
      </>
    ),
    bolt: <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8Z" />,
    target: (
      <>
        <circle cx="12" cy="12" r="10" />
        <circle cx="12" cy="12" r="6" />
        <circle cx="12" cy="12" r="2" />
      </>
    ),
    flame: (
      <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5Z" />
    ),
    check: <polyline points="20 6 9 17 4 12" />,
    arrow: (
      <>
        <line x1="5" y1="12" x2="19" y2="12" />
        <polyline points="12 5 19 12 12 19" />
      </>
    ),
    chevron: <polyline points="6 9 12 15 18 9" />,
  };
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  );
}

/* ── Переиспользуемая «стеклянная» карточка ────────────────── */
function Glass({ className = "", children }) {
  return (
    <div
      className={`rounded-3xl border border-white/10 bg-white/[0.03] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] ${className}`}
    >
      {children}
    </div>
  );
}

function Eyebrow({ children }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-sky-400/20 bg-sky-400/10 px-3.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-200">
      <span className="h-1.5 w-1.5 rounded-full bg-sky-300 shadow-[0_0_12px_2px_rgba(56,189,248,0.7)]" />
      {children}
    </span>
  );
}

/* ── Навигация ─────────────────────────────────────────────── */
const NAV_LINKS = [
  { href: "#features", label: "Возможности" },
  { href: "#how", label: "Как работает" },
  { href: "#safety", label: "Безопасность" },
  { href: "#pricing", label: "Тарифы" },
  { href: "#faq", label: "FAQ" },
];

function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-all duration-300 ${
        scrolled ? "border-b border-white/8 bg-[#07080d]/80 backdrop-blur-xl" : "border-b border-transparent"
      }`}
    >
      <div className="mx-auto flex w-full max-w-[1180px] items-center justify-between gap-4 px-4 py-3.5 sm:px-6">
        <a href="#top" className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#3b82f6,#0ea5e9)] text-sm font-bold text-white shadow-[0_10px_28px_rgba(37,99,235,0.45)]">
            TG
          </span>
          <span className="text-[15px] font-bold tracking-tight text-white">Outreach</span>
        </a>

        <nav className="hidden items-center gap-1 lg:flex">
          {NAV_LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="rounded-xl px-3.5 py-2 text-sm font-medium text-zinc-400 transition-colors hover:bg-white/[0.04] hover:text-white"
            >
              {l.label}
            </a>
          ))}
        </nav>

        <div className="hidden items-center gap-2.5 lg:flex">
          <Link to={APP_URL} className="btn-ghost">
            Войти
          </Link>
          <Link to={APP_URL} className="btn-primary">
            Запустить аутрич
          </Link>
        </div>

        <button
          onClick={() => setOpen((v) => !v)}
          className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-zinc-200 lg:hidden"
          aria-label="Меню"
        >
          {open ? "×" : "☰"}
        </button>
      </div>

      {open ? (
        <div className="border-t border-white/8 bg-[#07080d]/95 px-4 py-4 backdrop-blur-xl lg:hidden">
          <nav className="flex flex-col gap-1">
            {NAV_LINKS.map((l) => (
              <a
                key={l.href}
                href={l.href}
                onClick={() => setOpen(false)}
                className="rounded-xl px-3 py-2.5 text-sm font-medium text-zinc-300 hover:bg-white/[0.04] hover:text-white"
              >
                {l.label}
              </a>
            ))}
            <div className="mt-2 flex flex-col gap-2">
              <Link to={APP_URL} className="btn-secondary w-full">
                Войти
              </Link>
              <Link to={APP_URL} className="btn-primary w-full">
                Запустить аутрич
              </Link>
            </div>
          </nav>
        </div>
      ) : null}
    </header>
  );
}

/* ── Мок инбокса в герое ───────────────────────────────────── */
function InboxMock() {
  const threads = [
    { name: "Алексей М.", msg: "Да, интересно — расскажите подробнее", hot: true, unread: true, color: "bg-sky-600" },
    { name: "Marina K.", msg: "А сколько это стоит для команды из 5?", hot: true, unread: true, color: "bg-violet-600" },
    { name: "Дмитрий", msg: "Спасибо, посмотрю на неделе", hot: false, unread: false, color: "bg-emerald-600" },
    { name: "Olga P.", msg: "Скиньте, пожалуйста, кейсы", hot: false, unread: true, color: "bg-pink-600" },
  ];
  return (
    <div className="overflow-hidden rounded-[26px] border border-white/12 bg-[#0b0d15]/90 shadow-[0_40px_120px_rgba(2,6,23,0.7)] backdrop-blur-xl">
      {/* window chrome */}
      <div className="flex items-center gap-2 border-b border-white/8 px-4 py-3">
        <span className="h-3 w-3 rounded-full bg-rose-400/70" />
        <span className="h-3 w-3 rounded-full bg-amber-400/70" />
        <span className="h-3 w-3 rounded-full bg-emerald-400/70" />
        <div className="ml-3 flex items-center gap-2 rounded-lg border border-white/8 bg-black/30 px-2.5 py-1 text-[11px] text-zinc-500">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
          tg-outreach · Inbox
        </div>
        <span className="ml-auto rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-200">
          Live sync online
        </span>
      </div>

      <div className="grid grid-cols-[1fr] sm:grid-cols-[200px_1fr]">
        {/* список диалогов */}
        <div className="hidden flex-col gap-1 border-r border-white/8 p-3 sm:flex">
          <div className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-600">Диалоги</div>
          {threads.map((t, i) => (
            <div
              key={t.name}
              className={`flex items-center gap-2.5 rounded-2xl px-2.5 py-2 ${
                i === 0 ? "border border-white/10 bg-white/[0.05]" : "border border-transparent"
              }`}
            >
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${t.color} text-[11px] font-semibold text-white`}>
                {t.name[0]}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-xs font-semibold text-zinc-100">{t.name}</span>
                  {t.hot ? <Icon name="flame" className="h-3 w-3 text-orange-400" /> : null}
                </div>
                <div className="truncate text-[11px] text-zinc-500">{t.msg}</div>
              </div>
              {t.unread ? <span className="h-2 w-2 shrink-0 rounded-full bg-sky-400" /> : null}
            </div>
          ))}
        </div>

        {/* чат */}
        <div className="flex flex-col">
          <div className="flex items-center gap-2 border-b border-white/8 px-4 py-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-sky-600 text-[11px] font-semibold text-white">А</span>
            <div className="min-w-0">
              <div className="text-xs font-semibold text-zinc-100">Алексей М.</div>
              <div className="text-[10px] text-zinc-500">@alex_m · Кампания «SaaS Q2»</div>
            </div>
            <span className="ml-auto inline-flex items-center gap-1 rounded-full border border-orange-400/25 bg-orange-400/10 px-2 py-0.5 text-[10px] font-semibold text-orange-200">
              <Icon name="flame" className="h-3 w-3" /> Горячий лид
            </span>
          </div>

          <div className="flex flex-1 flex-col gap-2.5 px-4 py-4">
            <div className="max-w-[78%] self-start rounded-2xl rounded-bl-md border border-white/8 bg-white/[0.04] px-3 py-2 text-[12px] text-zinc-200">
              Привет, Алексей! Видел, что вы развиваете отдел продаж — у нас есть способ давать +30% касаний без расширения команды. Интересно?
              <div className="mt-1 text-right text-[9px] text-zinc-600">агент · 12:04</div>
            </div>
            <div className="max-w-[78%] self-end rounded-2xl rounded-br-md bg-[linear-gradient(135deg,#2563eb,#0ea5e9)] px-3 py-2 text-[12px] text-white shadow-[0_12px_30px_rgba(37,99,235,0.35)]">
              Да, интересно — расскажите подробнее
              <div className="mt-1 text-right text-[9px] text-white/70">Алексей · 12:09</div>
            </div>
            <div className="flex items-center gap-2 self-start rounded-xl border border-violet-400/20 bg-violet-400/10 px-2.5 py-1.5 text-[10px] text-violet-200">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-300" />
              Агент готовит ответ · персонализация по имени
            </div>
          </div>

          <div className="flex items-center gap-2 border-t border-white/8 px-4 py-3">
            <div className="flex-1 rounded-xl border border-white/8 bg-black/30 px-3 py-2 text-[11px] text-zinc-500">
              Ответить вручную или оставить агенту…
            </div>
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[linear-gradient(135deg,#2563eb,#0ea5e9)] text-white">
              <Icon name="arrow" className="h-4 w-4" />
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Плавающие чипы вокруг героя ───────────────────────────── */
function FloatChip({ className, icon, title, sub, tone = "sky" }) {
  const tones = {
    sky: "text-sky-300",
    emerald: "text-emerald-300",
    orange: "text-orange-300",
  };
  return (
    <div
      className={`absolute z-20 hidden items-center gap-2.5 rounded-2xl border border-white/12 bg-[#0b0d15]/90 px-3.5 py-2.5 shadow-[0_20px_50px_rgba(2,6,23,0.6)] backdrop-blur-xl md:flex ${className}`}
    >
      <span className={`flex h-8 w-8 items-center justify-center rounded-xl bg-white/[0.06] ${tones[tone]}`}>
        <Icon name={icon} className="h-4 w-4" />
      </span>
      <div>
        <div className="text-[13px] font-semibold leading-none text-white">{title}</div>
        <div className="mt-1 text-[11px] leading-none text-zinc-500">{sub}</div>
      </div>
    </div>
  );
}

/* ── Hero ──────────────────────────────────────────────────── */
function Hero() {
  return (
    <section id="top" className="relative px-4 pt-28 pb-16 sm:px-6 sm:pt-36 lg:pb-24">
      <div className="mx-auto max-w-[1180px]">
        <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
          {/* left */}
          <div className="text-center lg:text-left">
            <Eyebrow>Платформа холодного аутрича в Telegram</Eyebrow>
            <h1 className="mt-6 text-4xl font-extrabold leading-[1.05] tracking-tight text-white sm:text-5xl lg:text-[56px]">
              Превращайте Telegram в{" "}
              <span className="bg-[linear-gradient(120deg,#60a5fa,#22d3ee,#a78bfa)] bg-clip-text text-transparent">
                предсказуемый канал лидов
              </span>
            </h1>
            <p className="mx-auto mt-6 max-w-xl text-base leading-7 text-zinc-400 lg:mx-0 lg:text-lg">
              Мульти-аккаунтный аутрич с человеческим темпом, AI-агентом для ответов и живым инбоксом
              горячих лидов. Запускайте волны касаний, не выжигая аккаунты и не теряя ни одного ответа.
            </p>

            <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row lg:justify-start">
              <Link to={APP_URL} className="btn-primary w-full px-6 text-sm sm:w-auto">
                Запустить аутрич
                <Icon name="arrow" className="h-4 w-4" />
              </Link>
              <a href="#how" className="btn-secondary w-full px-6 text-sm sm:w-auto">
                Как это работает
              </a>
            </div>

            <div className="mt-7 flex flex-col items-center gap-2 text-xs text-zinc-500 sm:flex-row sm:gap-5 lg:justify-start">
              <span className="inline-flex items-center gap-2">
                <Icon name="check" className="h-4 w-4 text-emerald-400" /> Безопасный пейсинг по умолчанию
              </span>
              <span className="inline-flex items-center gap-2">
                <Icon name="check" className="h-4 w-4 text-emerald-400" /> Стоп при ответе лида
              </span>
              <span className="inline-flex items-center gap-2">
                <Icon name="check" className="h-4 w-4 text-emerald-400" /> Свой прокси на аккаунт
              </span>
            </div>
          </div>

          {/* right — мок */}
          <div className="relative">
            <div className="pointer-events-none absolute -inset-10 -z-10">
              <div className="absolute left-1/2 top-1/2 h-[360px] w-[360px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-sky-500/20 blur-[120px]" />
              <div className="absolute right-0 top-0 h-[240px] w-[240px] rounded-full bg-fuchsia-500/15 blur-[110px]" />
            </div>
            <FloatChip className="-left-4 top-10 lg:-left-10" icon="flame" tone="orange" title="2 горячих лида" sub="за последний час" />
            <FloatChip className="-right-3 bottom-16 lg:-right-8" icon="users" tone="emerald" title="12 аккаунтов" sub="online · прогрев ок" />
            <InboxMock />
          </div>
        </div>

        {/* интеграции / стек */}
        <div className="mt-16 lg:mt-20">
          <p className="text-center text-[11px] font-semibold uppercase tracking-[0.22em] text-zinc-600">
            Работает на проверенном стеке
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-3 sm:gap-4">
            {["Telegram API", "OpenAI GPT", "Anthropic Claude", "SOCKS / HTTP прокси", "Мульти-сессии"].map((s) => (
              <span
                key={s}
                className="rounded-full border border-white/10 bg-white/[0.03] px-4 py-2 text-sm font-medium text-zinc-400"
              >
                {s}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Полоса метрик ─────────────────────────────────────────── */
function Stats() {
  const stats = [
    { v: "24/7", l: "Агент отвечает без оператора" },
    { v: "2", l: "AI-провайдера: OpenAI и Anthropic" },
    { v: "1:1", l: "Свой прокси на каждый аккаунт" },
    { v: "0", l: "Ручной рутины на первом касании" },
  ];
  return (
    <section className="px-4 sm:px-6">
      <div className="mx-auto max-w-[1180px]">
        <Glass className="grid grid-cols-2 gap-px overflow-hidden bg-white/[0.05] lg:grid-cols-4">
          {stats.map((s) => (
            <div key={s.l} className="bg-[#090b12] px-6 py-8 text-center">
              <div className="bg-[linear-gradient(120deg,#60a5fa,#22d3ee)] bg-clip-text text-4xl font-extrabold tracking-tight text-transparent sm:text-5xl">
                {s.v}
              </div>
              <div className="mx-auto mt-3 max-w-[180px] text-sm leading-5 text-zinc-400">{s.l}</div>
            </div>
          ))}
        </Glass>
      </div>
    </section>
  );
}

/* ── Грид возможностей ─────────────────────────────────────── */
const FEATURES = [
  { icon: "users", title: "Мульти-аккаунты с контролем здоровья", text: "Подключайте десятки Telegram-аккаунтов. Платформа следит за статусами Connected / Degraded / Needs reauth, восстанавливает сессии и держит аккаунты готовыми к кампаниям." },
  { icon: "rocket", title: "Кампании с безопасным темпом", text: "Запускайте волны касаний с консервативным пейсингом и человеческими задержками. Статусы Draft / Running / Paused / Done — всё под контролем." },
  { icon: "brain", title: "AI-агент для ответов", text: "Промпт-паки на уровне аккаунта и кампании, ответы на OpenAI или Anthropic с персонализацией по имени и роли контакта." },
  { icon: "inbox", title: "Живой инбокс горячих лидов", text: "Все ответы в одном месте, фильтры по аккаунту, кампании и непрочитанным, пометка горячих лидов и моментальное ручное вмешательство." },
  { icon: "upload", title: "Импорт контактов и сегменты", text: "Загружайте контакты CSV (username, имя, компания, роль, заметка, теги), разбивайте на батчи и собирайте аудитории под каждую кампанию." },
  { icon: "network", title: "Пул прокси", text: "Общий пул с проверкой здоровья и автоподбором: один прокси на аккаунт, изоляция и контроль статусов proxy ok / failed / timeout." },
  { icon: "brain", title: "Промпт-паки", text: "Храните переиспользуемые системные промпты («Холодный outreach» и др.) и подключайте их к агентам аккаунтов и кампаний." },
  { icon: "shield", title: "DNC и комплаенс", text: "Список не-беспокоить, стоп-правила по ответу и аккуратные лимиты, чтобы аутрич оставался управляемым и безопасным." },
];

function Features() {
  return (
    <section id="features" className="scroll-mt-24 px-4 py-20 sm:px-6 lg:py-28">
      <div className="mx-auto max-w-[1180px]">
        <div className="mx-auto max-w-2xl text-center">
          <Eyebrow>Возможности</Eyebrow>
          <h2 className="mt-5 text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
            Всё для аутрича — в одном рабочем пространстве
          </h2>
          <p className="mt-4 text-base leading-7 text-zinc-400">
            От подключения аккаунтов до закрытия лида в инбоксе. Без таблиц, скриптов и зоопарка вкладок.
          </p>
        </div>

        <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <Glass key={f.title} className="group p-6 transition-all hover:border-white/20 hover:bg-white/[0.05]">
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,rgba(37,99,235,0.25),rgba(14,165,233,0.18))] text-sky-300 ring-1 ring-inset ring-white/10 transition-colors group-hover:text-sky-200">
                <Icon name={f.icon} />
              </span>
              <h3 className="mt-5 text-[17px] font-semibold leading-snug text-white">{f.title}</h3>
              <p className="mt-2.5 text-sm leading-6 text-zinc-400">{f.text}</p>
            </Glass>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Как работает ──────────────────────────────────────────── */
const STEPS = [
  { icon: "plug", n: "01", title: "Подключите аккаунты", text: "Добавьте Telegram-аккаунты и привяжите прокси. Платформа проверит сессии и доведёт их до статуса «готов к кампаниям»." },
  { icon: "upload", n: "02", title: "Загрузите контакты", text: "Импортируйте CSV или добавляйте вручную, разложите по батчам и тегам — готовая аудитория под кампанию." },
  { icon: "brain", n: "03", title: "Настройте агента и кампанию", text: "Выберите промпт-пак, первое сообщение и темп. Включите безопасный пейсинг и стоп при ответе." },
  { icon: "flame", n: "04", title: "Снимайте горячих лидов", text: "Агент ведёт диалоги, помечает горячих лидов и поднимает их в инбокс. Вмешивайтесь вручную в один клик." },
];

function HowItWorks() {
  return (
    <section id="how" className="scroll-mt-24 px-4 py-20 sm:px-6 lg:py-28">
      <div className="mx-auto max-w-[1180px]">
        <div className="mx-auto max-w-2xl text-center">
          <Eyebrow>Как это работает</Eyebrow>
          <h2 className="mt-5 text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
            От нуля до горячих лидов — четыре шага
          </h2>
        </div>

        <div className="relative mt-14 grid gap-4 lg:grid-cols-4">
          <div className="pointer-events-none absolute left-0 right-0 top-[44px] hidden h-px bg-gradient-to-r from-transparent via-white/12 to-transparent lg:block" />
          {STEPS.map((s) => (
            <div key={s.n} className="relative">
              <Glass className="h-full p-6">
                <div className="flex items-center justify-between">
                  <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/[0.05] text-sky-300 ring-1 ring-inset ring-white/10">
                    <Icon name={s.icon} />
                  </span>
                  <span className="text-2xl font-extrabold tracking-tight text-white/15">{s.n}</span>
                </div>
                <h3 className="mt-5 text-[17px] font-semibold text-white">{s.title}</h3>
                <p className="mt-2.5 text-sm leading-6 text-zinc-400">{s.text}</p>
              </Glass>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Мок: здоровье аккаунтов ───────────────────────────────── */
function AccountsMock() {
  const rows = [
    { n: "+1 202 ···", st: "Connected", cls: "bg-emerald-500/10 text-emerald-400", proxy: "Proxy ok", px: "text-emerald-400" },
    { n: "+44 7··· ", st: "Degraded", cls: "bg-orange-500/10 text-orange-400", proxy: "Proxy timeout", px: "text-orange-400" },
    { n: "+7 9·· ···", st: "Connected", cls: "bg-emerald-500/10 text-emerald-400", proxy: "Proxy ok", px: "text-emerald-400" },
    { n: "+49 1·· ··", st: "Needs reauth", cls: "bg-amber-500/10 text-amber-400", proxy: "Session expired", px: "text-amber-400" },
  ];
  return (
    <Glass className="overflow-hidden p-1.5">
      <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
        <span className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">Accounts</span>
        <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2.5 py-1 text-[10px] font-semibold text-emerald-200">
          3 / 4 готовы к кампаниям
        </span>
      </div>
      <div className="divide-y divide-white/6">
        {rows.map((r) => (
          <div key={r.n} className="flex items-center gap-3 px-4 py-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/[0.05] text-sky-300">
              <Icon name="users" className="h-4 w-4" />
            </span>
            <span className="font-mono text-sm text-zinc-200">{r.n}</span>
            <span className={`ml-auto rounded-lg px-2 py-1 text-[11px] font-medium ${r.cls}`}>{r.st}</span>
            <span className={`hidden text-[11px] font-medium sm:inline ${r.px}`}>{r.proxy}</span>
          </div>
        ))}
      </div>
    </Glass>
  );
}

/* ── Мок: промпт агента ────────────────────────────────────── */
function PromptMock() {
  return (
    <Glass className="overflow-hidden">
      <div className="flex items-center gap-2 border-b border-white/8 px-4 py-3">
        <Icon name="brain" className="h-4 w-4 text-violet-300" />
        <span className="text-xs font-semibold text-zinc-200">Промпт-пак · «Холодный outreach»</span>
        <span className="ml-auto rounded-full border border-violet-400/20 bg-violet-400/10 px-2 py-0.5 text-[10px] font-medium text-violet-200">
          gpt-4o · claude
        </span>
      </div>
      <div className="space-y-3 p-4">
        <div className="rounded-2xl border border-white/8 bg-black/30 p-3 font-mono text-[11px] leading-relaxed text-zinc-400">
          <span className="text-zinc-600">system:</span> Ты — менеджер по развитию. Пиши коротко и по-человечески,
          обращайся по имени <span className="text-sky-300">{"{first_name}"}</span>, веди к звонку. Не дави.
        </div>
        <div className="flex flex-wrap gap-2 text-[11px]">
          <span className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-zinc-300">Персонализация по имени</span>
          <span className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-zinc-300">Имя агента</span>
          <span className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-zinc-300">Сохранение абзацев</span>
        </div>
        <div className="rounded-2xl rounded-bl-md border border-sky-400/15 bg-sky-400/[0.06] p-3 text-[12px] text-zinc-200">
          «Привет, Марина! Заметил, что вы растите команду продаж…»
        </div>
      </div>
    </Glass>
  );
}

/* ── Мок: фильтры инбокса ──────────────────────────────────── */
function FiltersMock() {
  return (
    <Glass className="overflow-hidden">
      <div className="flex items-center gap-2 border-b border-white/8 px-4 py-3">
        <Icon name="inbox" className="h-4 w-4 text-sky-300" />
        <span className="text-xs font-semibold text-zinc-200">Inbox · фильтры</span>
      </div>
      <div className="space-y-3 p-4">
        <div className="flex flex-wrap gap-2 text-[11px]">
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-orange-400/25 bg-orange-400/10 px-2.5 py-1.5 font-medium text-orange-200">
            <Icon name="flame" className="h-3 w-3" /> Только горячие
          </span>
          <span className="rounded-lg border border-sky-400/20 bg-sky-400/10 px-2.5 py-1.5 font-medium text-sky-200">Непрочитанные</span>
          <span className="rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-zinc-300">Кампания «SaaS Q2»</span>
          <span className="rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-zinc-300">Аккаунт #3</span>
        </div>
        {[
          { n: "Алексей М.", t: "Active", c: "text-emerald-300" },
          { n: "Marina K.", t: "Active", c: "text-emerald-300" },
          { n: "Дмитрий", t: "Paused", c: "text-amber-300" },
        ].map((r) => (
          <div key={r.n} className="flex items-center gap-2.5 rounded-xl border border-white/8 bg-white/[0.02] px-3 py-2">
            <Icon name="flame" className={`h-3.5 w-3.5 ${r.t === "Active" ? "text-orange-400" : "text-zinc-700"}`} />
            <span className="text-sm text-zinc-200">{r.n}</span>
            <span className={`ml-auto text-[11px] font-medium ${r.c}`}>{r.t}</span>
          </div>
        ))}
      </div>
    </Glass>
  );
}

/* ── Deep-фичи (чередование) ───────────────────────────────── */
const DEEP = [
  {
    eyebrow: "Runtime",
    title: "Аккаунты, которые не выгорают",
    text: "Платформа постоянно отслеживает здоровье каждого аккаунта: статусы подключения, валидность сессий, состояние прокси и готовность к кампаниям. Просевшие сессии восстанавливаются, проблемные прокси подсвечиваются, а в кампанию идут только «зелёные» аккаунты.",
    points: ["Статусы Connected / Degraded / Needs reauth", "Автовосстановление сессий", "Привязка прокси и контроль здоровья"],
    mock: <AccountsMock />,
  },
  {
    eyebrow: "AI Layer",
    title: "Агент, который пишет как человек",
    text: "Системные промпт-паки на уровне аккаунта и кампании, выбор между OpenAI и Anthropic, персонализация по имени контакта и имени агента, аккуратные человеческие задержки перед ответом. Диалог ведётся сам, пока вы не решите вмешаться.",
    points: ["Промпт-паки и пресеты моделей", "Персонализация {first_name} и роли", "Человеческие задержки ответов"],
    mock: <PromptMock />,
    reverse: true,
  },
  {
    eyebrow: "Conversation Ops",
    title: "Ни один ответ не потеряется",
    text: "Живой инбокс собирает все диалоги в одном месте: фильтры по аккаунту, кампании и непрочитанным, автоматическая пометка горячих лидов и мгновенный переход к ручному ответу. Live-синхронизация показывает новые ответы в реальном времени.",
    points: ["Горячие лиды и непрочитанные одним фильтром", "Статусы диалога Active / Paused / Done", "Ручное вмешательство в один клик"],
    mock: <FiltersMock />,
  },
];

function DeepFeatures() {
  return (
    <section className="px-4 sm:px-6">
      <div className="mx-auto max-w-[1180px] space-y-20 lg:space-y-28">
        {DEEP.map((d) => (
          <div key={d.title} className="grid items-center gap-10 lg:grid-cols-2 lg:gap-16">
            <div className={d.reverse ? "lg:order-2" : ""}>
              <span className="text-[11px] font-semibold uppercase tracking-[0.22em] text-sky-300">{d.eyebrow}</span>
              <h3 className="mt-3 text-2xl font-extrabold tracking-tight text-white sm:text-3xl">{d.title}</h3>
              <p className="mt-4 text-base leading-7 text-zinc-400">{d.text}</p>
              <ul className="mt-6 space-y-3">
                {d.points.map((p) => (
                  <li key={p} className="flex items-start gap-3 text-sm text-zinc-300">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-400/15 text-emerald-300">
                      <Icon name="check" className="h-3 w-3" />
                    </span>
                    {p}
                  </li>
                ))}
              </ul>
            </div>
            <div className={d.reverse ? "lg:order-1" : ""}>
              <div className="relative">
                <div className="pointer-events-none absolute -inset-6 -z-10 rounded-[40px] bg-sky-500/10 blur-[80px]" />
                {d.mock}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── Безопасность ──────────────────────────────────────────── */
const SAFE = [
  { icon: "gauge", title: "Консервативный пейсинг", text: "Человеческий темп касаний и задержки — аккаунты живут дольше." },
  { icon: "pause", title: "Стоп при ответе", text: "Кампания не пишет лиду, который уже ответил — никакого спама." },
  { icon: "network", title: "Изоляция прокси", text: "Один прокси на аккаунт с проверкой здоровья и автоподбором." },
  { icon: "refresh", title: "Восстановление сессий", text: "Просевшие сессии переподключаются, проблемные подсвечиваются." },
];

function Safety() {
  return (
    <section id="safety" className="scroll-mt-24 px-4 py-20 sm:px-6 lg:py-28">
      <div className="mx-auto max-w-[1180px]">
        <Glass className="relative overflow-hidden p-8 sm:p-12">
          <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-emerald-500/10 blur-[100px]" />
          <div className="grid gap-10 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:gap-16">
            <div>
              <Eyebrow>Безопасность аккаунтов</Eyebrow>
              <h2 className="mt-5 text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
                Рост без выжженных аккаунтов
              </h2>
              <p className="mt-4 text-base leading-7 text-zinc-400">
                Аутрич в Telegram ломается, когда аккаунты летят в баны. Поэтому безопасность здесь —
                не галочка, а поведение системы по умолчанию: темп, стоп-правила, изоляция и
                восстановление встроены в каждую кампанию.
              </p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {SAFE.map((s) => (
                <div key={s.title} className="rounded-2xl border border-white/8 bg-black/20 p-5">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-400/10 text-emerald-300 ring-1 ring-inset ring-emerald-400/15">
                    <Icon name={s.icon} className="h-5 w-5" />
                  </span>
                  <h3 className="mt-4 text-[15px] font-semibold text-white">{s.title}</h3>
                  <p className="mt-1.5 text-sm leading-6 text-zinc-400">{s.text}</p>
                </div>
              ))}
            </div>
          </div>
        </Glass>
      </div>
    </section>
  );
}

/* ── Для кого ──────────────────────────────────────────────── */
const USE_CASES = [
  { icon: "target", title: "Агентствам лидогена", text: "Десятки аккаунтов и кампаний под разных клиентов в одном пространстве с прозрачным контролем." },
  { icon: "bolt", title: "B2B SaaS-продажам", text: "Тёплый канал касаний в дополнение к email: персонализация и быстрый переход к звонку." },
  { icon: "users", title: "Рекрутингу и хантингу", text: "Аккуратные касания кандидатов по сегментам с человеческим тоном и стопом при ответе." },
  { icon: "rocket", title: "Фаундерам", text: "Запустить первые продажи без отдела: агент ведёт диалоги, вы подключаетесь на горячих." },
];

function UseCases() {
  return (
    <section className="px-4 py-4 sm:px-6">
      <div className="mx-auto max-w-[1180px]">
        <div className="mx-auto max-w-2xl text-center">
          <Eyebrow>Для кого</Eyebrow>
          <h2 className="mt-5 text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
            Кому это даёт результат
          </h2>
        </div>
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {USE_CASES.map((u) => (
            <Glass key={u.title} className="p-6 transition-all hover:border-white/20 hover:bg-white/[0.05]">
              <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/[0.05] text-sky-300 ring-1 ring-inset ring-white/10">
                <Icon name={u.icon} className="h-5 w-5" />
              </span>
              <h3 className="mt-4 text-[16px] font-semibold text-white">{u.title}</h3>
              <p className="mt-2 text-sm leading-6 text-zinc-400">{u.text}</p>
            </Glass>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Тарифы ────────────────────────────────────────────────── */
const PLANS = [
  {
    name: "Starter",
    price: "$49",
    tagline: "Первые кампании и проверка канала",
    features: ["До 3 аккаунтов", "1 000 контактов в месяц", "AI-автоответы (1 провайдер)", "Безопасный пейсинг", "Живой инбокс"],
    cta: "Начать",
  },
  {
    name: "Growth",
    price: "$149",
    tagline: "Постоянный поток лидов для команды",
    features: ["До 15 аккаунтов", "10 000 контактов в месяц", "OpenAI + Anthropic", "Промпт-паки и пул прокси", "Горячие лиды и фильтры", "Приоритетная поддержка"],
    cta: "Выбрать Growth",
    popular: true,
  },
  {
    name: "Scale",
    price: "$399",
    tagline: "Агентства и большие объёмы",
    features: ["Без лимита аккаунтов", "Безлимит контактов", "DNC и комплаенс", "Несколько рабочих пространств", "Выделенный менеджер"],
    cta: "Связаться",
  },
];

function Pricing() {
  return (
    <section id="pricing" className="scroll-mt-24 px-4 py-20 sm:px-6 lg:py-28">
      <div className="mx-auto max-w-[1180px]">
        <div className="mx-auto max-w-2xl text-center">
          <Eyebrow>Тарифы</Eyebrow>
          <h2 className="mt-5 text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
            Прозрачные планы под ваш объём
          </h2>
          <p className="mt-4 text-base leading-7 text-zinc-400">
            Начните с малого и масштабируйтесь по мере роста аутрича.
          </p>
        </div>

        <div className="mt-14 grid items-stretch gap-5 lg:grid-cols-3">
          {PLANS.map((p) => (
            <div
              key={p.name}
              className={`relative flex flex-col rounded-3xl border p-7 ${
                p.popular
                  ? "border-sky-400/30 bg-[linear-gradient(180deg,rgba(37,99,235,0.12),rgba(14,165,233,0.04))] shadow-[0_30px_80px_rgba(37,99,235,0.18)]"
                  : "border-white/10 bg-white/[0.03]"
              }`}
            >
              {p.popular ? (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-[linear-gradient(135deg,#2563eb,#0ea5e9)] px-3.5 py-1 text-[11px] font-bold uppercase tracking-[0.16em] text-white shadow-[0_10px_28px_rgba(37,99,235,0.45)]">
                  Популярный
                </span>
              ) : null}
              <h3 className="text-lg font-bold text-white">{p.name}</h3>
              <p className="mt-1 text-sm text-zinc-400">{p.tagline}</p>
              <div className="mt-5 flex items-baseline gap-1.5">
                <span className="text-4xl font-extrabold tracking-tight text-white">{p.price}</span>
                <span className="text-sm text-zinc-500">/ мес</span>
              </div>
              <Link to={APP_URL} className={`mt-6 ${p.popular ? "btn-primary" : "btn-secondary"} w-full`}>
                {p.cta}
              </Link>
              <ul className="mt-7 space-y-3 border-t border-white/8 pt-6">
                {p.features.map((f) => (
                  <li key={f} className="flex items-start gap-3 text-sm text-zinc-300">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-sky-400/15 text-sky-300">
                      <Icon name="check" className="h-3 w-3" />
                    </span>
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <p className="mt-6 text-center text-xs text-zinc-600">
          Цены приведены как ориентир тарифной сетки и настраиваются под объём и формат работы.
        </p>
      </div>
    </section>
  );
}

/* ── FAQ ───────────────────────────────────────────────────── */
const FAQ = [
  { q: "Это безопасно для моих аккаунтов?", a: "Безопасность встроена по умолчанию: консервативный пейсинг с человеческими задержками, стоп при ответе лида, изоляция через отдельный прокси на аккаунт и автоматическое восстановление сессий. Платформа отслеживает здоровье каждого аккаунта и пускает в кампании только готовые." },
  { q: "Какие AI-модели используются для ответов?", a: "Поддерживаются и OpenAI (GPT), и Anthropic (Claude). Вы выбираете провайдера и пресет модели, задаёте системный промпт-пак на уровне аккаунта или кампании, а ответы персонализируются по имени и роли контакта." },
  { q: "Нужны ли свои прокси?", a: "Да, для безопасной работы используется свой прокси на каждый аккаунт (SOCKS или HTTP). В платформе есть общий пул с проверкой здоровья и автоподбором, а статусы proxy ok / failed / timeout видны сразу." },
  { q: "Как загрузить контакты?", a: "Импортом CSV в формате username, имя, компания, роль, заметка, теги или добавлением вручную. Контакты раскладываются по батчам и тегам, из которых собираются аудитории под конкретные кампании." },
  { q: "Что с лимитами и банами Telegram?", a: "Кампании работают консервативно: ограниченный темп, человеческие задержки и стоп-правила. Это снижает риски и продлевает жизнь аккаунтов. Дополнительно есть DNC-список, чтобы не писать тем, кому не нужно." },
  { q: "Могу ли я вмешаться в диалог вручную?", a: "Да. Агент ведёт переписку сам, но в живом инбоксе вы в любой момент перехватываете диалог и отвечаете вручную. Горячие лиды подсвечиваются автоматически, чтобы вы подключались в нужный момент." },
];

function FaqItem({ item, open, onToggle }) {
  return (
    <div className="border-b border-white/8">
      <button onClick={onToggle} className="flex w-full items-center justify-between gap-4 py-5 text-left">
        <span className="text-[16px] font-semibold text-white">{item.q}</span>
        <Icon
          name="chevron"
          className={`h-5 w-5 shrink-0 text-zinc-400 transition-transform duration-300 ${open ? "rotate-180" : ""}`}
        />
      </button>
      <div className={`grid transition-all duration-300 ${open ? "grid-rows-[1fr] pb-5" : "grid-rows-[0fr]"}`}>
        <div className="overflow-hidden">
          <p className="text-sm leading-7 text-zinc-400">{item.a}</p>
        </div>
      </div>
    </div>
  );
}

function Faq() {
  const [open, setOpen] = useState(0);
  return (
    <section id="faq" className="scroll-mt-24 px-4 py-20 sm:px-6 lg:py-28">
      <div className="mx-auto max-w-[820px]">
        <div className="text-center">
          <Eyebrow>FAQ</Eyebrow>
          <h2 className="mt-5 text-3xl font-extrabold tracking-tight text-white sm:text-4xl">Частые вопросы</h2>
        </div>
        <div className="mt-10">
          {FAQ.map((item, i) => (
            <FaqItem key={item.q} item={item} open={open === i} onToggle={() => setOpen(open === i ? -1 : i)} />
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Финальный CTA ─────────────────────────────────────────── */
function FinalCta() {
  return (
    <section className="px-4 pb-24 sm:px-6">
      <div className="mx-auto max-w-[1180px]">
        <div className="relative overflow-hidden rounded-[36px] border border-white/12 bg-[linear-gradient(135deg,rgba(37,99,235,0.22),rgba(14,165,233,0.1),rgba(168,85,247,0.14))] px-6 py-16 text-center sm:px-12">
          <div className="pointer-events-none absolute -left-10 -top-10 h-64 w-64 rounded-full bg-sky-500/25 blur-[100px]" />
          <div className="pointer-events-none absolute -bottom-16 -right-10 h-72 w-72 rounded-full bg-fuchsia-500/20 blur-[120px]" />
          <div className="relative">
            <h2 className="mx-auto max-w-2xl text-3xl font-extrabold tracking-tight text-white sm:text-[42px] sm:leading-tight">
              Запустите первый аутрич сегодня
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-base leading-7 text-zinc-300">
              Подключите аккаунты, загрузите контакты и дайте агенту вести диалоги — горячие лиды
              окажутся в вашем инбоксе уже сегодня.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link to={APP_URL} className="btn-primary w-full px-7 text-sm sm:w-auto">
                Запустить аутрич
                <Icon name="arrow" className="h-4 w-4" />
              </Link>
              <a href="#pricing" className="btn-secondary w-full px-7 text-sm sm:w-auto">
                Посмотреть тарифы
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Футер ─────────────────────────────────────────────────── */
function Footer() {
  const cols = [
    { title: "Продукт", links: [["Возможности", "#features"], ["Как работает", "#how"], ["Безопасность", "#safety"], ["Тарифы", "#pricing"]] },
    { title: "Ресурсы", links: [["FAQ", "#faq"], ["Документация", "#"], ["Статус сервиса", "#"]] },
    { title: "Компания", links: [["О продукте", "#"], ["Контакты", "#"], ["Конфиденциальность", "#"]] },
  ];
  return (
    <footer className="border-t border-white/8 px-4 py-14 sm:px-6">
      <div className="mx-auto max-w-[1180px]">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))]">
          <div>
            <a href="#top" className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#3b82f6,#0ea5e9)] text-sm font-bold text-white">
                TG
              </span>
              <span className="text-[15px] font-bold tracking-tight text-white">Outreach</span>
            </a>
            <p className="mt-4 max-w-xs text-sm leading-6 text-zinc-500">
              Платформа безопасного холодного аутрича в Telegram: мульти-аккаунты, AI-агент и живой инбокс
              горячих лидов.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Link to={APP_URL} className="btn-primary text-sm">
                Открыть приложение
              </Link>
            </div>
          </div>
          {cols.map((c) => (
            <div key={c.title}>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-600">{c.title}</div>
              <ul className="mt-4 space-y-2.5">
                {c.links.map(([label, href]) => (
                  <li key={label}>
                    <a href={href} className="text-sm text-zinc-400 transition-colors hover:text-white">
                      {label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-12 flex flex-col items-center justify-between gap-3 border-t border-white/8 pt-6 text-xs text-zinc-600 sm:flex-row">
          <span>© 2026 TG Outreach. Сделано для безопасного Telegram-аутрича.</span>
          <span className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
            Все системы в норме
          </span>
        </div>
      </div>
    </footer>
  );
}

/* ── Корневой компонент ────────────────────────────────────── */
export default function Landing() {
  useEffect(() => {
    const root = document.documentElement;
    const prev = root.style.scrollBehavior;
    root.style.scrollBehavior = "smooth";
    return () => {
      root.style.scrollBehavior = prev;
    };
  }, []);

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#07080d] text-zinc-100">
      {/* фоновые свечения */}
      <div className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute -left-32 top-[-10%] h-[520px] w-[520px] rounded-full bg-sky-500/12 blur-[150px]" />
        <div className="absolute right-[-140px] top-[8%] h-[520px] w-[520px] rounded-full bg-fuchsia-500/10 blur-[160px]" />
        <div className="absolute bottom-[-10%] left-[30%] h-[480px] w-[620px] rounded-full bg-cyan-500/8 blur-[160px]" />
      </div>

      <Navbar />
      <main>
        <Hero />
        <Stats />
        <Features />
        <HowItWorks />
        <DeepFeatures />
        <Safety />
        <UseCases />
        <Pricing />
        <Faq />
        <FinalCta />
      </main>
      <Footer />
    </div>
  );
}
