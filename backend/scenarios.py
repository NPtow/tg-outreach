from datetime import datetime
import re
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models import Conversation, Message, ScenarioCard
from backend.scenario_packs import FOUNDER_RESEARCH_PACK, FOUNDER_RESEARCH_PACK_KEY, FOUNDER_RESEARCH_PACK_TAG


def serialize_scenario(card: ScenarioCard) -> dict:
    return {
        "id": card.id,
        "project_id": card.project_id,
        "title": card.title,
        "intent": card.intent,
        "intent_label": _intent_label(card.intent),
        "trigger_summary": card.trigger_summary,
        "example_questions": _example_questions(card),
        "recommended_reply": card.recommended_reply,
        "avoid_reply": card.avoid_reply or "",
        "tags": card.tags or "",
        "status": card.status,
        "status_label": _status_label(card.status),
        "source_conversation_id": card.source_conversation_id,
        "dify_document_id": card.dify_document_id,
        "dify_sync_status": card.dify_sync_status,
        "dify_sync_error": card.dify_sync_error,
        "dify_synced_at": card.dify_synced_at,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
    }


GROUP_META = {
    "core": ("Базовые правила", "Голос, история переписки и определение стадии диалога."),
    "faq": ("Вопросы и ответы", "Готовые ответы на повторяющиеся вопросы и возражения."),
    "scheduling": ("Назначение встречи", "Переход от интереса к созвону и правила выбора слота."),
    "closing": ("Завершение диалога", "Отказы, завершение диалога и лимит повторных касаний."),
    "boundaries": ("Ограничения", "Что можно говорить про проект и что нельзя обещать."),
    "fallback": ("Нет ответа в базе", "Безопасный ответ, если в базе нет факта."),
    "quality": ("Проверка качества", "Финальная самопроверка перед отправкой."),
    "manual": ("Ручные сценарии", "Сценарии, созданные вручную или добытые из переписок."),
}

GROUP_ORDER = ["core", "faq", "scheduling", "closing", "boundaries", "fallback", "quality", "manual"]


def list_scenarios(db: Session, status: Optional[str] = None, project_id: Optional[int] = None) -> list[ScenarioCard]:
    query = db.query(ScenarioCard)
    if project_id is not None:
        query = query.filter(ScenarioCard.project_id == int(project_id))
    if status:
        query = query.filter(ScenarioCard.status == status)
    else:
        query = query.filter(ScenarioCard.status != "legacy")
    return query.order_by(ScenarioCard.updated_at.desc(), ScenarioCard.id.desc()).all()


def group_scenarios(cards: Iterable[ScenarioCard]) -> list[dict]:
    grouped: dict[str, list[ScenarioCard]] = {}
    for card in cards:
        group_key = _tag_value(card.tags or "", "group") or "manual"
        grouped.setdefault(group_key, []).append(card)

    def group_sort_key(key: str) -> tuple[int, str]:
        return (GROUP_ORDER.index(key) if key in GROUP_ORDER else len(GROUP_ORDER), key)

    result = []
    for key in sorted(grouped.keys(), key=group_sort_key):
        label, description = GROUP_META.get(key, (key.replace("_", " ").title(), ""))
        cards_for_group = sorted(grouped[key], key=lambda card: (card.title or "").lower())
        result.append(
            {
                "key": key,
                "label": label,
                "description": description,
                "count": len(cards_for_group),
                "cards": [serialize_scenario(card) for card in cards_for_group],
            }
        )
    return result


def seed_founder_research_pack(db: Session, activate: bool = True, project_id: Optional[int] = None) -> dict:
    existing_query = db.query(ScenarioCard).filter(ScenarioCard.tags.like(f"%{FOUNDER_RESEARCH_PACK_TAG}%"))
    if project_id is not None:
        existing_query = existing_query.filter(ScenarioCard.project_id == int(project_id))
    existing = existing_query.all()
    by_key = {_tag_value(card.tags or "", "key"): card for card in existing}
    created = 0
    updated = 0

    for spec in FOUNDER_RESEARCH_PACK:
        card = by_key.get(spec["key"])
        payload = {
            "title": spec["title"],
            "intent": spec["intent"],
            "trigger_summary": spec["trigger_summary"],
            "recommended_reply": spec["recommended_reply"],
            "avoid_reply": spec.get("avoid_reply", ""),
            "tags": spec["tags"],
            "status": "active" if activate else spec.get("status", "draft"),
        }
        if project_id is not None:
            payload["project_id"] = int(project_id)
        if card is None:
            db.add(ScenarioCard(**payload, updated_at=datetime.utcnow()))
            created += 1
            continue

        changed = False
        for field, value in payload.items():
            if getattr(card, field) != value:
                setattr(card, field, value)
                changed = True
        if changed:
            card.updated_at = datetime.utcnow()
            updated += 1

    db.commit()
    total_query = db.query(ScenarioCard).filter(ScenarioCard.tags.like(f"%{FOUNDER_RESEARCH_PACK_TAG}%"))
    if project_id is not None:
        total_query = total_query.filter(ScenarioCard.project_id == int(project_id))
    total = total_query.count()
    return {
        "pack": FOUNDER_RESEARCH_PACK_KEY,
        "created": created,
        "updated": updated,
        "total": total,
    }


def mark_founder_research_pack_legacy(db: Session, project_id: Optional[int] = None) -> dict:
    query = db.query(ScenarioCard).filter(ScenarioCard.tags.like(f"%{FOUNDER_RESEARCH_PACK_TAG}%"))
    if project_id is not None:
        query = query.filter(ScenarioCard.project_id == int(project_id))
    cards = query.all()
    updated = 0
    for card in cards:
        if card.status != "legacy":
            card.status = "legacy"
            card.updated_at = datetime.utcnow()
            updated += 1
    db.commit()
    return {
        "pack": FOUNDER_RESEARCH_PACK_KEY,
        "updated": updated,
        "total": len(cards),
        "status": "legacy",
    }


def analyze_conversations_for_suggestions(db: Session, limit: int = 50, project_id: Optional[int] = None) -> dict:
    query = db.query(Conversation)
    if project_id is not None:
        query = query.filter(Conversation.project_id == int(project_id))
    conversations = query.order_by(Conversation.last_message_at.desc(), Conversation.id.desc()).limit(limit).all()
    created = 0
    updated = 0
    skipped = 0
    created_cards: list[ScenarioCard] = []

    for conversation in conversations:
        messages = (
            db.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .all()
        )
        text = "\n".join(msg.text or "" for msg in messages).strip()
        if not text:
            skipped += 1
            continue

        proposal = _heuristic_scenario(text)
        exists = (
            db.query(ScenarioCard)
            .filter(
                ScenarioCard.source_conversation_id == conversation.id,
                ScenarioCard.intent == proposal["intent"],
                ScenarioCard.tags.like("%auto:conversation_analysis%"),
                ScenarioCard.project_id == conversation.project_id,
            )
            .first()
        )
        if exists:
            changed = False
            payload = {
                "title": proposal["title"],
                "trigger_summary": proposal["trigger_summary"],
                "recommended_reply": proposal["recommended_reply"],
                "avoid_reply": proposal["avoid_reply"],
                "tags": _suggestion_tags(proposal["intent"], proposal["tags"]),
            }
            for field, value in payload.items():
                if getattr(exists, field) != value:
                    setattr(exists, field, value)
                    changed = True
            if changed:
                exists.updated_at = datetime.utcnow()
                updated += 1
            skipped += 1
            continue

        card = ScenarioCard(
            title=proposal["title"],
            intent=proposal["intent"],
            trigger_summary=proposal["trigger_summary"],
            recommended_reply=proposal["recommended_reply"],
            avoid_reply=proposal["avoid_reply"],
            tags=_suggestion_tags(proposal["intent"], proposal["tags"]),
            status="suggested",
            project_id=conversation.project_id,
            source_conversation_id=conversation.id,
            updated_at=datetime.utcnow(),
        )
        db.add(card)
        created_cards.append(card)
        created += 1

    db.commit()
    for card in created_cards:
        db.refresh(card)

    suggestions = list_scenarios(db, status="suggested", project_id=project_id)
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total_suggested": len(suggestions),
        "suggestions": [serialize_scenario(card) for card in suggestions],
    }


def active_scenarios_for_text(db: Session, text: str, limit: int = 3, project_id: Optional[int] = None) -> list[ScenarioCard]:
    cards = list_scenarios(db, status="active", project_id=project_id)
    if not text:
        return cards[:limit]
    tokens = list(_tokens(text.lower()))

    def score(card: ScenarioCard) -> int:
        haystack = " ".join(
            [
                card.title or "",
                card.intent or "",
                card.trigger_summary or "",
                card.recommended_reply or "",
                card.avoid_reply or "",
                card.tags or "",
            ]
        ).lower()
        return sum(2 if token in (card.tags or "").lower() else 1 for token in tokens if token and token in haystack)

    return sorted(cards, key=score, reverse=True)[:limit]


def mine_scenario_from_conversation(db: Session, conversation_id: int) -> ScenarioCard:
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )
    text = "\n".join(msg.text for msg in messages)
    proposal = _heuristic_scenario(text)
    card = ScenarioCard(
        title=proposal["title"],
        intent=proposal["intent"],
        trigger_summary=proposal["trigger_summary"],
        recommended_reply=proposal["recommended_reply"],
        avoid_reply=proposal["avoid_reply"],
        tags=proposal["tags"],
        status="draft",
        project_id=conversation.project_id,
        source_conversation_id=conversation_id,
        updated_at=datetime.utcnow(),
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


def _heuristic_scenario(text: str) -> dict:
    lower = text.lower()
    if any(word in lower for word in ["продаж", "куп", "sales", "sell"]):
        return {
            "title": "Собеседник думает, что это продажа",
            "intent": "sales_objection",
            "trigger_summary": "Собеседник подозревает продажу или покупку вместо исследовательского интервью.",
            "recommended_reply": "Коротко объяснить, что это исследовательское интервью, не продажа, и назвать длительность.",
            "avoid_reply": "Не спорить и не давить на встречу.",
            "tags": "objection,research,not_sales",
        }
    if any(word in lower for word in ["созвон", "встреч", "call", "meeting", "интервью"]):
        return {
            "title": "Собеседник готов к созвону",
            "intent": "book_meeting",
            "trigger_summary": "Собеседник согласился на созвон или просит договориться о времени.",
            "recommended_reply": "Подтвердить и забронировать ближайший свободный слот через календарь.",
            "avoid_reply": "Не обещать слот без фактического бронирования.",
            "tags": "booking,calendar,zoom",
        }
    return {
        "title": "Собеседник просит больше контекста",
        "intent": "context_question",
        "trigger_summary": "Собеседник спрашивает, что именно исследуется, зачем пишем или чего от него хотят.",
        "recommended_reply": "Кратко объяснить цель исследования и задать один простой следующий вопрос.",
        "avoid_reply": "Не перегружать деталями.",
        "tags": "question,context,research",
    }


def _suggestion_tags(intent: str, base_tags: str) -> str:
    group = {
        "sales_objection": "faq",
        "book_meeting": "scheduling",
        "context_question": "faq",
    }.get(intent, "manual")
    tags = ["auto:conversation_analysis", "source:conversation", f"group:{group}"]
    tags.extend(tag.strip() for tag in (base_tags or "").split(",") if tag.strip())
    return ",".join(dict.fromkeys(tags))


def _tokens(text: str) -> Iterable[str]:
    for raw in re.findall(r"[\wа-яА-ЯёЁ]+", text, flags=re.UNICODE):
        token = raw.strip().lower()
        if len(token) >= 4:
            yield token


def _tag_value(tags: str, key: str) -> Optional[str]:
    prefix = f"{key}:"
    for tag in (tags or "").split(","):
        tag = tag.strip()
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return None


def _intent_label(intent: str) -> str:
    return {
        "style_rule": "Правило голоса",
        "context_rule": "Учет истории",
        "stage_rule": "Определение стадии",
        "project_context": "Контекст проекта",
        "guardrail": "Ограничение",
        "fallback_unknown": "Нет ответа",
        "research_goal": "Цель исследования",
        "research_scope": "Что исследуем",
        "discussion_topics": "Темы разговора",
        "hypotheses_question": "Гипотезы",
        "sales_objection": "Возражение: продажа",
        "job_application_objection": "Возражение: вакансия",
        "project_question": "Вопрос про проект",
        "project_stage": "Стадия проекта",
        "employer_value": "Ценность для работодателя",
        "candidate_value": "Ценность для кандидата",
        "interview_request": "Что нужно от собеседника",
        "duration_question": "Длительность",
        "prep_question": "Подготовка",
        "why_me_question": "Почему написали",
        "fit_question": "Подходит ли опыт",
        "product_exists_question": "Есть ли продукт",
        "commercial_stage_question": "Клиенты и деньги",
        "agency_objection": "Не агентство",
        "confidentiality_question": "Конфиденциальность",
        "written_instead_call": "Письменно вместо созвона",
        "identity_question": "Кто пишет",
        "automation_question": "Автоматизация",
        "lead_value_question": "Польза для собеседника",
        "book_meeting": "Назначить встречу",
        "manual_slot_confirmation": "Подтвердить слот",
        "manual_scheduling": "Ручное согласование",
        "closing_not_interested": "Вежливо завершить",
        "follow_up_rule": "Лимит повторного касания",
        "quality_check": "Самопроверка",
        "context_question": "Уточнение контекста",
    }.get(intent or "", intent or "Без типа")


def _status_label(status: str) -> str:
    return {
        "active": "Активен",
        "suggested": "Предложен",
        "draft": "Черновик",
        "archived": "В архиве",
        "legacy": "Легаси",
    }.get(status or "", status or "Без статуса")


def _example_questions(card: ScenarioCard) -> list[str]:
    key = _tag_value(card.tags or "", "key")
    by_key = {
        "core_identity": ["Как должен звучать ответ?", "От чьего лица отвечать?"],
        "history_context": ["Что уже обсуждали выше?", "Мы это уже согласовали?"],
        "stage_pipeline": ["На какой стадии сейчас диалог?", "Это уточнение, согласование времени или отказ?"],
        "project_context": ["Что за проект?", "На какой вы стадии?", "Это уже готовый продукт?"],
        "do_not_promise": ["Какие функции уже есть?", "Какие интеграции вы обещаете?", "Какой результат гарантируете?"],
        "unknown_answer": ["Вопрос, на который нет ответа в базе", "Факт, которого нет в сценариях"],
        "goal_of_research": ["В чем цель исследования?", "Зачем вы это исследуете?"],
        "what_researching": ["Что именно вы исследуете?", "Какие процессы найма вас интересуют?"],
        "what_to_discuss": ["Что хотите обсудить?", "Какие темы будут на интервью?"],
        "hypotheses": ["Какие гипотезы проверяете?", "Что хотите понять по итогам?"],
        "sales_objection": ["Это продажа?", "Что вы продаете?", "Вы хотите что-то предложить?"],
        "not_job_application": ["Это отклик на вакансию?", "Вы ищете работу?"],
        "what_project": ["Что за проект?", "Чем вы занимаетесь?"],
        "stage_question": ["На каком вы этапе?", "У вас уже есть продукт?"],
        "employer_side": ["Что вы делаете для работодателя?", "В чем польза для компании?"],
        "candidate_side": ["Что вы делаете для кандидата?", "Как это помогает кандидату?"],
        "what_need_from_me": ["Что вам нужно от меня?", "Что от меня требуется?"],
        "duration": ["Сколько это займет?", "Сколько длится интервью?"],
        "no_preparation": ["Нужно ли готовиться?", "Что подготовить к созвону?"],
        "why_me": ["Почему пишете именно мне?", "Почему мой опыт подходит?"],
        "company_size_fit": ["Подходит ли наш размер компании?", "Подходит ли мой опыт?", "У нас другой формат, это ок?"],
        "has_product": ["У вас уже есть продукт?", "Это уже работает?"],
        "clients_or_revenue": ["У вас уже есть клиенты?", "Как вы зарабатываете?", "Какая монетизация?"],
        "not_agency": ["Это кадровое агентство?", "Вы рекрутеры?"],
        "confidentiality": ["Это конфиденциально?", "Что будет с этой информацией?"],
        "written_instead_call": ["Можно без созвона?", "Можно ответить письменно?"],
        "who_are_you": ["Кто вы?", "С кем будет созвон?", "Я буду общаться именно с вами?"],
        "automation_disclosure": ["Это автоматический аккаунт?", "Это бот отвечает?"],
        "value_for_lead": ["Что мне это даст?", "Какая польза для меня?"],
        "scheduling_agreed": ["Давайте созвонимся", "Когда вам удобно?", "Пришлите ссылку"],
        "scheduling_manual_slots": ["Мне удобно завтра в 18:00", "Могу во вторник после обеда"],
        "scheduling_no_link": ["Не хочу переходить по ссылке", "Давайте договоримся здесь"],
        "closing_not_interested": ["Неинтересно", "Неактуально", "Нет времени"],
        "follow_up_limit": ["Человек не ответил после одного напоминания"],
        "final_self_check": ["Ответ не противоречит истории?", "Ответ не звучит шаблонно?"],
    }
    if key in by_key:
        return by_key[key]
    by_intent = {
        "sales_objection": ["Это продажа?", "Что вы продаете?", "Я ничего покупать не хочу"],
        "book_meeting": ["Давайте созвонимся", "Когда удобно?", "Пришлите ссылку"],
        "context_question": ["Что вы исследуете?", "Зачем вы пишете?", "Что вам нужно?"],
        "closing_not_interested": ["Неинтересно", "Неактуально", "Нет времени"],
    }
    return by_intent.get(card.intent or "", [card.trigger_summary] if card.trigger_summary else [])
