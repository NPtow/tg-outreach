from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


EXPORT_VERSION = "2026-04-28-prod-replies-v1"


@dataclass(frozen=True)
class ScenarioDefinition:
    key: str
    title: str
    intent: str
    stage: str
    group: str
    triggers: tuple[str, ...]
    when_to_use: str
    recommended_reply: str
    avoid_reply: str
    priority: int = 50


@dataclass
class Message:
    id: int | str | None
    role: str
    text: str
    created_at: str | None = None


@dataclass
class NormalizedConversation:
    id: int
    account_name: str
    campaign_name: str
    status: str
    tg_first_name: str
    tg_last_name: str
    message_count: int
    assistant_count: int
    user_count: int
    first_user_message_at: str | None
    last_message_at: str | None
    last_message: str
    messages: list[Message] = field(default_factory=list)


SCENARIO_DEFINITIONS: list[ScenarioDefinition] = [
    ScenarioDefinition(
        key="why_value_for_me",
        title="Собеседник спрашивает, зачем это ему лично",
        intent="value_question",
        stage="qualification",
        group="faq",
        priority=10,
        triggers=("зачем", "что мне это даст", "какая мне ценность", "польза для меня"),
        when_to_use="Собеседник спрашивает, какая ему личная польза от участия в исследовании.",
        recommended_reply=(
            "Прямой продажи здесь нет. Для меня ценность в вашем практическом опыте, "
            "а для вас это возможность коротко отрефлексировать, где в найме реально возникают потери и сложности."
        ),
        avoid_reply="Не отправлять ссылку на встречу до снятия сомнения. Не отвечать только с позиции своей выгоды.",
    ),
    ScenarioDefinition(
        key="why_value_for_company",
        title="Собеседник спрашивает, зачем это компании",
        intent="company_value_question",
        stage="qualification",
        group="faq",
        priority=11,
        triggers=("компании это зачем", "компании зачем", "для компании", "ценность для компании"),
        when_to_use="Собеседник спрашивает, зачем участие может быть полезно компании, а не только исследователю.",
        recommended_reply=(
            "Для компании это может быть полезно как короткая внешняя рефлексия по найму: "
            "где теряются кандидаты, где возникает шум и какие сигналы реально помогают принимать решения. "
            "Но это не продажа и не обещание бизнес-результата после разговора."
        ),
        avoid_reply="Не обещать измеримый бизнес-результат, готовый продукт или коммерческую пользу.",
    ),
    ScenarioDefinition(
        key="bot_or_automation_question",
        title="Собеседник спрашивает, бот ли это или замечает автоматизацию",
        intent="bot_disclosure",
        stage="trust",
        group="trust",
        priority=5,
        triggers=("бот", "автомат", "автоматический", "автоответ", "нейросеть", "робот"),
        when_to_use="Собеседник прямо спрашивает, автоматизирована ли переписка, или замечает неестественность.",
        recommended_reply=(
            "Часть переписки у меня автоматизирована, чтобы быстрее обрабатывать ответы, "
            "но само исследование и интервью я веду лично."
        ),
        avoid_reply="Не отрицать автоматизацию, если вопрос задан прямо. Не уходить сразу в Calendly.",
    ),
    ScenarioDefinition(
        key="source_or_identity_question",
        title="Собеседник спрашивает, кто пишет и откуда контакт",
        intent="source_identity",
        stage="trust",
        group="trust",
        priority=12,
        triggers=("вы кто", "кто вы", "никита это кто", "откуда", "контакт", "нашли", "чат", "почему пишете"),
        when_to_use="Собеседник просит объяснить личность отправителя или источник контакта.",
        recommended_reply=(
            "Я сам веду это исследование как основатель проекта. Контакт увидел в одном из HR-чатов, "
            "где вы были в профессиональном контексте. Если неудобно, понимаю и не буду отвлекать."
        ),
        avoid_reply="Не придумывать конкретный чат, если он неизвестен. Не звучать уклончиво.",
    ),
    ScenarioDefinition(
        key="project_or_research_goal",
        title="Собеседник спрашивает, что за проект или цель исследования",
        intent="research_context",
        stage="qualification",
        group="faq",
        priority=20,
        triggers=("что за проект", "что делаете", "цель", "исследуете", "исследование", "гипотез", "что хотите обсудить"),
        when_to_use="Собеседник просит объяснить проект, цель исследования, гипотезы или темы интервью.",
        recommended_reply=(
            "Сейчас это раннее исследование и ручной пилот в hiring space. Я изучаю, как у компаний реально "
            "устроен найм product-ролей: где тормозится процесс, где теряются сильные кандидаты и какие сигналы "
            "помогают принимать решения."
        ),
        avoid_reply="Не обещать готовый продукт, интеграции, поток кандидатов или доказанную бизнес-модель.",
    ),
    ScenarioDefinition(
        key="sales_objection",
        title="Собеседник думает, что это продажа",
        intent="sales_objection",
        stage="qualification",
        group="faq",
        priority=15,
        triggers=("продажа", "продаете", "купить", "коммерческ", "питч"),
        when_to_use="Собеседник воспринимает сообщение как продажу или коммерческий питч.",
        recommended_reply="Нет, это не продажа. Сейчас задача именно исследовательская: понять реальную практику найма.",
        avoid_reply="Не спорить и не пытаться продавать ценность продукта.",
    ),
    ScenarioDefinition(
        key="job_application_objection",
        title="Собеседник думает, что это отклик на вакансию",
        intent="job_application_objection",
        stage="qualification",
        group="faq",
        priority=16,
        triggers=("отклик", "ваканси", "кандидат", "резюме", "работу ищете"),
        when_to_use="Собеседник думает, что отправитель откликается на вакансию или ищет работу.",
        recommended_reply="Нет, это не отклик на вакансию. Это исследовательский запрос про ваш практический опыт найма.",
        avoid_reply="Не смешивать исследование с наймом себя или продажей кандидатов.",
    ),
    ScenarioDefinition(
        key="company_size_fit",
        title="Собеседник уточняет, подходит ли его опыт или размер компании",
        intent="audience_fit",
        stage="qualification",
        group="faq",
        priority=30,
        triggers=("подойдет", "подходит", "размер компании", "штат", "1000", "150", "400", "средний бизнес", "небольшая компания", "опыт", "проработала", "проработал"),
        when_to_use="Собеседник сомневается, подходит ли его опыт, роль или размер компании для исследования.",
        recommended_reply=(
            "Да, такой опыт подходит. Мне важен не только размер компании, а практическое участие в найме "
            "и понимание того, как реально устроены поиск, отбор, интервью и принятие решений по кандидатам."
        ),
        avoid_reply="Не отвечать расплывчато «интересен любой опыт». Объяснить, почему опыт подходит.",
    ),
    ScenarioDefinition(
        key="not_target_recruiter_or_role",
        title="Собеседник не занимается нужным типом найма",
        intent="not_target_audience",
        stage="closing",
        group="closing",
        priority=25,
        triggers=("не для персонала", "не нанимаю", "не занимаюсь", "не моя зона", "кастдев"),
        when_to_use="Собеседник явно говорит, что не занимается нужным типом найма или не является релевантной ЦА.",
        recommended_reply="Понял, спасибо за уточнение. Тогда не буду отвлекать. Хорошего дня!",
        avoid_reply="Не пытаться дожимать нерелевантного человека на созвон.",
    ),
    ScenarioDefinition(
        key="not_large_company_but_relevant",
        title="Собеседник говорит, что компания не крупная",
        intent="audience_not_large_company",
        stage="qualification",
        group="faq",
        priority=31,
        triggers=("не крупная", "небольшая", "не работал", "не работала", "в крупных не"),
        when_to_use="Собеседник говорит, что компания небольшая или нет опыта именно в крупных компаниях.",
        recommended_reply=(
            "Понял. Если у вас был практический опыт найма или участия в принятии решений по кандидатам, "
            "это все равно может быть полезно для исследования."
        ),
        avoid_reply="Не закрывать диалог только из-за размера компании, если опыт найма релевантен.",
    ),
    ScenarioDefinition(
        key="ready_to_call_offer_slots",
        title="Собеседник готов к созвону и предлагает слоты",
        intent="manual_scheduling",
        stage="scheduling",
        group="scheduling",
        priority=40,
        triggers=("могу", "можем", "давайте", "пообщаться", "поговорить", "найдется 20 минут", "удобно", "завтра", "сегодня", "понедельник", "вторник", "сред", "четвер", "пятниц", "18:00", "11:00", "17.00", "15.00", "15:00", "10:00"),
        when_to_use="Собеседник согласился на разговор и предложил конкретное время или диапазон.",
        recommended_reply="Отлично, давайте тогда в [точная дата] в [точное время] по Москве. Я поставлю встречу и пришлю подтверждение.",
        avoid_reply="Не отправлять Calendly, если человек уже предложил ручные слоты. Не подтверждать слот без проверки календаря.",
    ),
    ScenarioDefinition(
        key="ask_for_link",
        title="Собеседник просит ссылку для выбора времени",
        intent="send_booking_link",
        stage="scheduling",
        group="scheduling",
        priority=41,
        triggers=("пришлите ссылку", "ссылка", "выбрать время", "calendly", "календар"),
        when_to_use="Собеседник просит ссылку или хочет сам выбрать время.",
        recommended_reply="Да, конечно. Вот ссылка, здесь можно выбрать удобное время для короткого созвона: [ссылка для записи]",
        avoid_reply="Не отправлять ссылку, если до этого человек уже пошел по ручному согласованию.",
    ),
    ScenarioDefinition(
        key="link_problem_or_link_objection",
        title="Ссылка не открывается или человек не хочет переходить по ссылкам",
        intent="link_objection",
        stage="scheduling",
        group="scheduling",
        priority=8,
        triggers=("не открывается", "не клика", "без vpn", "не перехожу", "по ссылкам", "ссылка не"),
        when_to_use="Ссылка не работает, некликабельна или человек не хочет переходить по ссылкам.",
        recommended_reply="Понимаю. Тогда можем без ссылки: напишите, пожалуйста, 2-3 удобных слота по Москве, и я подстроюсь.",
        avoid_reply="Не повторять ту же ссылку. Не спорить с опасением по ссылкам.",
    ),
    ScenarioDefinition(
        key="already_selected_slot",
        title="Собеседник уже выбрал слот или подтверждает встречу",
        intent="meeting_confirmed",
        stage="scheduling",
        group="scheduling",
        priority=42,
        triggers=("выбрала слот", "выбрал слот", "записалась", "записался", "до встречи", "подтверждаю", "договорились", "так точно", "выбрала", "уже выбрал"),
        when_to_use="Собеседник уже выбрал слот, подтвердил встречу или пишет финальное сообщение до созвона.",
        recommended_reply="Да, вижу, спасибо. Тогда встречаемся в выбранное время.",
        avoid_reply="Не отправлять ссылку повторно и не запускать новый виток согласования.",
    ),
    ScenarioDefinition(
        key="postpone_later",
        title="Собеседник не может сейчас, но допускает позже",
        intent="postpone",
        stage="scheduling",
        group="scheduling",
        priority=45,
        triggers=("позже", "вернусь", "после", "в отпуске", "как пойму", "пока не могу"),
        when_to_use="Собеседник не отказывается окончательно, но переносит разговор на потом.",
        recommended_reply="Понял, спасибо. Тогда вернемся к этому позже, когда вам будет удобно.",
        avoid_reply="Не закрывать как жесткий отказ и не давить на немедленный слот.",
    ),
    ScenarioDefinition(
        key="hard_no_time_refusal",
        title="Собеседник отказывает из-за отсутствия времени",
        intent="closing_no_time",
        stage="closing",
        group="closing",
        priority=6,
        triggers=("нет времени", "не готов", "не могу участвовать", "нет возможности", "занят", "занята"),
        when_to_use="Собеседник явно говорит, что времени нет и не предлагает вернуться позже.",
        recommended_reply="Понял, спасибо большое за ответ и фидбек. Хорошего дня!",
        avoid_reply="Не дожимать и не отправлять ссылку после отказа.",
    ),
    ScenarioDefinition(
        key="not_interested_refusal",
        title="Собеседнику неинтересно или неактуально",
        intent="closing_not_interested",
        stage="closing",
        group="closing",
        priority=7,
        triggers=("неинтерес", "не интересно", "не актуаль", "неактуаль", "не хочу", "не готова", "не готов", "незручно розмовляти"),
        when_to_use="Собеседник явно отказывается или пишет, что это неактуально.",
        recommended_reply="Понял, спасибо большое за ответ и фидбек. Хорошего дня!",
        avoid_reply="Не спорить, не переубеждать, не делать дополнительный дожим.",
    ),
    ScenarioDefinition(
        key="commercial_materials_request",
        title="Собеседник просит сайт или коммерческое предложение",
        intent="sales_materials_request",
        stage="qualification",
        group="faq",
        priority=18,
        triggers=("сайт", "кп", "коммерческое предложение", "материалы", "презентац"),
        when_to_use="Собеседник просит сайт, КП или материалы вместо созвона.",
        recommended_reply=(
            "Понимаю. Сейчас это не коммерческое предложение и не продажа, поэтому отдельного КП здесь нет. "
            "Я именно собираю практический взгляд на найм; если созвон неудобен, можно коротко ответить письменно на 2-3 вопроса."
        ),
        avoid_reply="Не отправлять несуществующие материалы и не делать вид, что продукт уже полностью готов.",
    ),
    ScenarioDefinition(
        key="paid_consultation_request",
        title="Собеседник предлагает платную консультацию",
        intent="paid_consultation",
        stage="closing",
        group="closing",
        priority=9,
        triggers=("стоимость", "платн", "консультац", "ставка", "руб", "₽"),
        when_to_use="Собеседник готов общаться только платно или называет стоимость консультации.",
        recommended_reply=(
            "Понял, спасибо за отклик. Сейчас я не планировал платные консультации в рамках этого исследования, "
            "поэтому не буду занимать ваше время. Хорошего дня!"
        ),
        avoid_reply="Не торговаться и не продолжать дожимать бесплатный созвон.",
    ),
    ScenarioDefinition(
        key="written_answers_instead_call",
        title="Собеседник предлагает ответить письменно вместо созвона",
        intent="written_answers",
        stage="qualification",
        group="faq",
        priority=35,
        triggers=("письменно", "письмово", "напишите вопросы", "напишите", "без созвона", "в чате", "текстом"),
        when_to_use="Собеседник не хочет созваниваться, но допускает письменный формат.",
        recommended_reply=(
            "Если вам удобнее, можно и коротко письменно. Но созвон обычно полезнее, потому что там проще быстро пройтись по реальной практике и деталям."
        ),
        avoid_reply="Не давить на созвон, если человек явно предпочитает письменный формат.",
    ),
    ScenarioDefinition(
        key="privacy_or_confidentiality",
        title="Собеседник спрашивает про конфиденциальность данных",
        intent="privacy_confidentiality",
        stage="trust",
        group="trust",
        priority=17,
        triggers=("конфиденциаль", "информация", "данные", "публич", "использовать", "поделитесь результатами", "результаты исследования"),
        when_to_use="Собеседник спрашивает, что будет с информацией или можно ли говорить конфиденциально.",
        recommended_reply="Да, разговор нужен именно для исследования практики, без публичного использования ваших слов как маркетингового кейса.",
        avoid_reply="Не обещать юридические условия, которых нет. Не раскрывать чужие данные.",
    ),
    ScenarioDefinition(
        key="short_courtesy_closing",
        title="Короткое вежливое завершение после спасибо или до встречи",
        intent="courtesy_closing",
        stage="closing",
        group="closing",
        priority=80,
        triggers=("спасибо", "взаимно", "до встречи", "хорошего дня", "удачи", "успехов", "без проблем"),
        when_to_use="Собеседник пишет короткое финальное сообщение, где не нужен новый смысловой виток.",
        recommended_reply="Спасибо!",
        avoid_reply="Не запускать новый диалог и не повторять длинный контекст исследования.",
    ),
    ScenarioDefinition(
        key="simple_greeting_or_interest_probe",
        title="Собеседник отвечает коротким приветствием без сути",
        intent="greeting_probe",
        stage="qualification",
        group="faq",
        priority=70,
        triggers=("привет", "здравствуйте", "добрый день", "добрый вечер", "доброе утро"),
        when_to_use="Собеседник ответил только приветствием или очень короткой репликой без вопроса и без отказа.",
        recommended_reply="Подскажите, вам было бы интересно коротко обсудить практику найма product-ролей?",
        avoid_reply="Не начинать длинный питч заново и не писать новое приветствие в ответе.",
    ),
    ScenarioDefinition(
        key="research_results_request",
        title="Собеседник просит поделиться итогами исследования",
        intent="research_results_request",
        stage="qualification",
        group="faq",
        priority=22,
        triggers=("поделитесь результатами", "результаты итогового", "итоговое исследование", "пришлите результаты"),
        when_to_use="Собеседник готов участвовать при условии, что потом получит результаты исследования.",
        recommended_reply="Да, без проблем. Когда соберу и структурирую выводы, смогу поделиться краткими итогами.",
        avoid_reply="Не обещать точный срок или полноценный публичный отчет, если он не запланирован.",
    ),
    ScenarioDefinition(
        key="calendar_email_invite_issue",
        title="Проблема с календарным приглашением или почтой",
        intent="calendar_email_issue",
        stage="scheduling",
        group="calendar_ops",
        priority=13,
        triggers=("почте", "почта", "email", "@", ".com", "адрес", "приглашение", "ничего нет", "куда отправляли", "не пришло"),
        when_to_use="После согласования встречи человек пишет, что не получил приглашение, спрашивает про почту или присылает email.",
        recommended_reply="Понял. Пришлите, пожалуйста, актуальную почту, и я продублирую приглашение.",
        avoid_reply="Не гадать адрес и не писать персональные email в базу знаний.",
    ),
    ScenarioDefinition(
        key="reschedule_meeting",
        title="Собеседник просит перенести уже согласованную встречу",
        intent="reschedule_meeting",
        stage="scheduling",
        group="calendar_ops",
        priority=14,
        triggers=("перенести", "перенес", "можем не", "вместо", "сдвинуть", "сдвинется", "запутался"),
        when_to_use="Встреча уже обсуждалась, но время нужно поменять или уточнить.",
        recommended_reply="Понял, давайте перенесем. Напишите, пожалуйста, какой слот сейчас удобнее, и я обновлю приглашение.",
        avoid_reply="Не подтверждать новое время без проверки календаря и без ясного финального слота.",
    ),
    ScenarioDefinition(
        key="agent_name_or_identity_mismatch",
        title="Собеседник заметил путаницу в имени агента",
        intent="agent_identity_mismatch",
        stage="trust",
        group="trust",
        priority=4,
        triggers=("никита или алексей", "никита это кто", "что тут верно", "почему никита", "почему алексей", "кто будет на созвоне", "вместо меня будет коллега", "странно"),
        when_to_use="Собеседник видит расхождение в имени отправителя, календаря или человека на встрече.",
        recommended_reply="Понимаю, выглядит странно. Уточню и вернусь с корректной информацией, чтобы не вводить вас в заблуждение.",
        avoid_reply="Не выдумывать объяснение и не продолжать назначение встречи, пока путаница не снята.",
    ),
    ScenarioDefinition(
        key="interested_next_step",
        title="Собеседник проявил интерес и спрашивает, что дальше",
        intent="interested_next_step",
        stage="qualification",
        group="scheduling",
        priority=39,
        triggers=("интересно продолжайте", "что дальше", "и что дальше", "и что?"),
        when_to_use="Собеседник проявил интерес, но еще не предложил слот и спрашивает следующий шаг.",
        recommended_reply="Следующий шаг — коротко созвониться на 20-30 минут и обсудить ваш практический опыт найма. Если вам ок, напишите удобные слоты по Москве.",
        avoid_reply="Не уходить в длинный питч и не повторять весь первый текст.",
    ),
]


SCENARIO_BY_KEY = {definition.key: definition for definition in SCENARIO_DEFINITIONS}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def normalize_conversations(full_export: dict[str, Any]) -> list[NormalizedConversation]:
    conversations: list[NormalizedConversation] = []
    for item in full_export.get("conversations", []):
        meta = item.get("conversation") or item.get("detail_conversation") or {}
        stats = item.get("stats") or {}
        messages = [normalize_message(message) for message in item.get("messages", [])]
        conversation_id = int(meta.get("id") or item.get("id") or 0)
        if not conversation_id:
            raise ValueError(f"Conversation without id: {item!r}")
        conversations.append(
            NormalizedConversation(
                id=conversation_id,
                account_name=str(meta.get("account_name") or ""),
                campaign_name=str(meta.get("source_campaign_name") or meta.get("campaign_name") or ""),
                status=str(meta.get("status") or ""),
                tg_first_name=str(meta.get("tg_first_name") or ""),
                tg_last_name=str(meta.get("tg_last_name") or ""),
                message_count=int(stats.get("message_count") or len(messages)),
                assistant_count=int(stats.get("assistant_count") or sum(1 for message in messages if message.role == "assistant")),
                user_count=int(stats.get("user_count") or sum(1 for message in messages if message.role == "user")),
                first_user_message_at=stats.get("first_user_message_at"),
                last_message_at=meta.get("last_message_at"),
                last_message=str(meta.get("last_message") or ""),
                messages=messages,
            )
        )
    return conversations


def normalize_message(raw: dict[str, Any]) -> Message:
    role = str(raw.get("role") or raw.get("direction") or "").strip().lower()
    if role in {"outbound", "agent", "me"}:
        role = "assistant"
    if role in {"inbound", "lead", "contact"}:
        role = "user"
    return Message(
        id=raw.get("id"),
        role=role or "unknown",
        text=clean_text(str(raw.get("text") or raw.get("content") or raw.get("body") or "")),
        created_at=raw.get("created_at"),
    )


def clean_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def compact_text(value: str, limit: int = 220) -> str:
    value = re.sub(r"\s+", " ", clean_text(value)).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def sanitize_text(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "[email]", value)
    value = re.sub(r"@[A-Za-z0-9_]{3,}", "[username]", value)
    value = re.sub(r"\b\d{7,}\b", "[numeric_id]", value)
    value = re.sub(r"https?://\S+", "[link]", value)
    return value


def user_text(messages: Iterable[Message | dict[str, Any]]) -> str:
    chunks: list[str] = []
    for message in messages:
        role = message.role if isinstance(message, Message) else str(message.get("role") or "")
        text = message.text if isinstance(message, Message) else str(message.get("text") or "")
        if role == "user":
            chunks.append(text)
    return "\n".join(chunks)


def assistant_text(messages: Iterable[Message | dict[str, Any]]) -> str:
    chunks: list[str] = []
    for message in messages:
        role = message.role if isinstance(message, Message) else str(message.get("role") or "")
        text = message.text if isinstance(message, Message) else str(message.get("text") or "")
        if role == "assistant":
            chunks.append(text)
    return "\n".join(chunks)


def text_has_any(text: str, needles: Iterable[str]) -> bool:
    lowered = text.lower()
    for needle in needles:
        normalized = needle.lower()
        if normalized == "бот":
            if re.search(r"(?<![а-яёa-z])бот(?![а-яёa-z])", lowered):
                return True
            continue
        if normalized in {"робот", "робот?"}:
            if re.search(r"(?<![а-яёa-z])робот(?![а-яёa-z])", lowered):
                return True
            continue
        if normalized in lowered:
            return True
    return False


def detect_flags(text: str) -> dict[str, bool]:
    lowered = text.lower()
    return {
        "value_question": text_has_any(lowered, ("зачем", "что мне это даст", "ценност", "польз")),
        "bot_question": text_has_any(lowered, ("бот", "автомат", "автоответ", "нейросеть", "робот")),
        "source_question": text_has_any(lowered, ("откуда", "кто вы", "вы кто", "контакт", "почему пишете")),
        "project_question": text_has_any(lowered, ("проект", "цель", "исслед", "гипотез", "что хотите")),
        "scheduling": text_has_any(lowered, ("созвон", "встреч", "слот", "удобно", "когда", "завтра", "сегодня", "calendly", "календар")),
        "link_problem": text_has_any(lowered, ("не открывается", "не клика", "без vpn", "не перехожу", "по ссылкам")),
        "refusal": text_has_any(lowered, ("нет времени", "неинтерес", "не актуаль", "неактуаль", "не хочу", "не готов", "нет возможности")),
        "fit_question": text_has_any(lowered, ("подойд", "опыт", "размер", "компани", "не крупн", "небольш")),
        "commercial_materials": text_has_any(lowered, ("сайт", "коммерческое", "кп", "материалы", "презентац")),
        "paid_consultation": text_has_any(lowered, ("стоимость", "платн", "консультац", "руб")),
        "written_answers": text_has_any(lowered, ("письменно", "без созвона", "в чате", "напишите вопросы")),
    }


def classify_scenario_key(text: str) -> str:
    lowered = text.lower()
    for definition in sorted(SCENARIO_DEFINITIONS, key=lambda item: item.priority):
        if text_has_any(lowered, definition.triggers):
            if definition.key == "why_value_for_me" and text_has_any(lowered, ("компании", "компани")):
                return "why_value_for_company"
            if definition.key == "ask_for_link" and text_has_any(lowered, ("не открывается", "не перехожу", "не клика", "без vpn")):
                return "link_problem_or_link_objection"
            return definition.key
    return "unknown"


def stage_for_scenario_key(key: str) -> str:
    definition = SCENARIO_BY_KEY.get(key)
    return definition.stage if definition else "fallback"


def quality_label(user_turn: str, assistant_reply: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    lowered_user = user_turn.lower()
    lowered_reply = assistant_reply.lower()
    has_link = "calendly" in lowered_reply or "http" in lowered_reply or "[link]" in lowered_reply

    if not assistant_reply.strip():
        reasons.append("empty_assistant_reply")
    if starts_with_greeting(assistant_reply):
        reasons.append("reply_starts_with_greeting")
    if text_has_any(lowered_user, ("бот", "автомат", "автоответ", "робот")) and not text_has_any(lowered_reply, ("автомат", "бот", "робот", "лично")):
        reasons.append("bot_question_not_disclosed")
    if text_has_any(lowered_user, ("зачем", "ценность", "польз")) and has_link:
        reasons.append("link_sent_before_value_objection_resolved")
    if text_has_any(lowered_user, ("не открывается", "не перехожу", "без vpn", "не клика")) and has_link:
        reasons.append("repeated_link_after_link_problem")
    if text_has_any(lowered_user, ("нет времени", "неинтерес", "неактуаль", "не хочу", "не готов")) and has_link:
        reasons.append("continued_push_after_refusal")
    if text_has_any(lowered_reply, ("готовый продукт", "гарантир", "точно решим", "поток кандидатов")):
        reasons.append("overpromised_product_value")
    if text_has_any(lowered_user, ("давайте", "могу", "удобно", "завтра", "сегодня")) and "calendly" in lowered_reply:
        reasons.append("sent_link_after_manual_slot_offer")

    if reasons:
        return "risky", reasons
    if len(assistant_reply) > 700:
        return "review", ["long_reply"]
    return "good", []


def starts_with_greeting(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered.startswith(("здравствуйте", "привет", "добрый день", "доброе утро", "добрый вечер"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
        "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    normalized = "".join(translit.get(char, char) for char in value.lower())
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "item"


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    rendered = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        rendered.append("| " + " | ".join(str(cell).replace("\n", " ") for cell in row) + " |")
    return "\n".join(rendered)


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
