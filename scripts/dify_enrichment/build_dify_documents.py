from __future__ import annotations

import argparse
from pathlib import Path

from scripts.dify_enrichment.common import (
    EXPORT_VERSION,
    compact_text,
    load_json,
    read_jsonl,
    sha256_text,
    slugify,
    write_json,
)


CORE_DOCS = {
    "core-context-hrd-research.md": """# Core context: HRD research

```metadata
type: core_policy
version: 2026-04-28-prod-replies-v1
status: active
```

Исследование ведется от первого лица как основатель проекта. Цель переписки — договориться на короткое исследовательское интервью на 20-30 минут про реальные процессы найма product-ролей со стороны компании.

Контекст проекта: раннее исследование и ручной пилот в hiring space. Нельзя делать вид, что уже есть полностью готовый автоматизированный продукт, доказанная бизнес-модель, готовые интеграции или гарантированный поток кандидатов.
""",
    "core-policy-answer-style.md": """# Core policy: answer style

```metadata
type: core_policy
version: 2026-04-28-prod-replies-v1
status: active
```

Ответ должен быть коротким, естественным и логичным продолжением текущей переписки. Обычно 1-3 предложения. Не использовать приветствия в ответных сообщениях. Сначала отвечать на прямой вопрос, потом при необходимости мягко вести к интервью.

Если ответа нет в базе знаний, отвечать: «Я спрошу и вернусь к вам.»
""",
    "core-policy-scheduling.md": """# Core policy: scheduling

```metadata
type: core_policy
version: 2026-04-28-prod-replies-v1
status: active
```

Если собеседник предложил конкретные слоты, не отправлять ссылку первым. Нужно выбрать или подтвердить слот после проверки календаря. Если собеседник просит ссылку или хочет сам выбрать время, можно отправить ссылку. Если ссылка не открывается или человек не хочет переходить по ссылкам, перейти на ручное согласование.
""",
    "core-policy-boundaries.md": """# Core policy: boundaries

```metadata
type: core_policy
version: 2026-04-28-prod-replies-v1
status: active
```

Нельзя обещать готовый продукт, готовые интеграции, поток сильных кандидатов, matching engine, гарантированную обратную связь, доказанную монетизацию или конкретный бизнес-результат. Нельзя переубеждать после отказа. Нельзя скрывать автоматизацию, если собеседник прямо спрашивает.
""",
}


def build_documents(candidates_path: Path, episodes_path: Path, out_dir: Path, manifest_path: Path) -> dict:
    candidates_data = load_json(candidates_path)
    episodes = read_jsonl(episodes_path)
    episodes_by_id = {episode["episode_id"]: episode for episode in episodes}
    manifest_items: list[dict] = []

    for relative_name, text in CORE_DOCS.items():
        write_doc(out_dir / "core" / relative_name, text, "core_policy", [], manifest_items)

    for candidate in candidates_data["candidates"]:
        text = render_scenario_doc(candidate)
        relative_path = Path("scenarios") / f"scenario-{candidate['scenario_key']}.md"
        write_doc(out_dir / relative_path, text, "scenario_card", candidate["source_conversation_ids"], manifest_items, status=candidate["status"])

    for candidate in candidates_data["candidates"]:
        examples = [episodes_by_id[episode_id] for episode_id in candidate["source_episode_ids"] if episode_id in episodes_by_id]
        selected = select_examples(examples)
        for episode in selected:
            text = render_example_doc(candidate, episode)
            relative_path = Path("examples") / f"example-{episode['episode_id']}-{candidate['scenario_key']}.md"
            write_doc(out_dir / relative_path, text, "conversation_example", [episode["conversation_id"]], manifest_items, status=candidate["status"])

    negative_patterns = build_negative_patterns(episodes)
    for pattern in negative_patterns:
        text = render_negative_pattern_doc(pattern)
        relative_path = Path("negative_patterns") / f"negative-{pattern['pattern_key']}.md"
        write_doc(out_dir / relative_path, text, "negative_pattern", pattern["source_conversation_ids"], manifest_items)

    eval_cases = build_eval_cases(candidates_data["candidates"], episodes_by_id)
    for case in eval_cases:
        text = render_eval_case_doc(case)
        relative_path = Path("evals") / f"eval-{case['case_id']}.md"
        write_doc(out_dir / relative_path, text, "eval_case", case["source_conversation_ids"], manifest_items, status=case["status"])

    manifest = {
        "version": EXPORT_VERSION,
        "source_candidates": str(candidates_path),
        "source_episodes": str(episodes_path),
        "document_count": len(manifest_items),
        "counts_by_type": count_by(manifest_items, "type"),
        "counts_by_status": count_by(manifest_items, "status"),
        "documents": manifest_items,
    }
    write_json(manifest_path, manifest)
    return manifest


def render_scenario_doc(candidate: dict) -> str:
    return "\n".join(
        [
            f"# {candidate['title']}",
            "",
            "```metadata",
            "type: scenario_card",
            f"version: {candidate['version']}",
            f"scenario_key: {candidate['scenario_key']}",
            f"intent: {candidate['intent']}",
            f"stage: {candidate['stage']}",
            f"group: {candidate['group']}",
            f"status: {candidate['status']}",
            f"review_required: {candidate.get('review_required', False)}",
            f"confidence: {candidate['confidence']}",
            f"source_conversation_ids: {candidate['source_conversation_ids']}",
            "```",
            "",
            "## Когда применять",
            candidate["when_to_use"],
            "",
            "## Вопросы и триггеры",
            "\n".join(f"- {phrase}" for phrase in candidate["trigger_phrases"]) or "- нет примеров",
            "",
            "## Как отвечать",
            candidate["recommended_reply"],
            "",
            "## Запасная формулировка",
            candidate["fallback_recommended_reply"],
            "",
            "## Чего избегать",
            candidate["avoid_reply"],
            "",
            "## Качество источников",
            f"- Эпизодов: {candidate['episode_count']}",
            f"- Quality counts: {candidate['quality_counts']}",
            f"- Risky reasons: {candidate['risky_reasons']}",
            f"- Требует ручного review: {candidate.get('review_required', False)}",
        ]
    ).strip() + "\n"


def render_example_doc(candidate: dict, episode: dict) -> str:
    history = "\n".join(f"- {message['role']}: {compact_text(message['text'], 320)}" for message in episode["history"])
    return "\n".join(
        [
            f"# Conversation example: {candidate['title']}",
            "",
            "```metadata",
            "type: conversation_example",
            f"version: {EXPORT_VERSION}",
            f"scenario_key: {candidate['scenario_key']}",
            f"episode_id: {episode['episode_id']}",
            f"source_conversation_ids: [{episode['conversation_id']}]",
            f"quality_label: {episode['quality_label']}",
            f"status: {candidate['status']}",
            "```",
            "",
            "## Ситуация",
            candidate["when_to_use"],
            "",
            "## Последнее сообщение собеседника",
            episode["last_user_message"],
            "",
            "## Короткая история",
            history,
            "",
            "## Хороший следующий ответ или реальный ответ",
            episode["assistant_reply"],
            "",
            "## Риски",
            ", ".join(episode.get("quality_reasons", [])) or "нет явных рисков",
        ]
    ).strip() + "\n"


def build_negative_patterns(episodes: list[dict]) -> list[dict]:
    patterns: dict[str, dict] = {}
    for episode in episodes:
        for reason in episode.get("quality_reasons", []):
            pattern = patterns.setdefault(
                reason,
                {
                    "pattern_key": reason,
                    "bad_behavior": reason.replace("_", " "),
                    "why_bad": why_bad(reason),
                    "better_behavior": better_behavior(reason),
                    "source_conversation_ids": set(),
                    "episode_ids": [],
                    "test_queries": [],
                },
            )
            pattern["source_conversation_ids"].add(episode["conversation_id"])
            pattern["episode_ids"].append(episode["episode_id"])
            if len(pattern["test_queries"]) < 5:
                pattern["test_queries"].append(episode["last_user_message"])
    result = []
    for pattern in patterns.values():
        pattern["source_conversation_ids"] = sorted(pattern["source_conversation_ids"])
        result.append(pattern)
    return sorted(result, key=lambda item: item["pattern_key"])


def why_bad(reason: str) -> str:
    return {
        "reply_starts_with_greeting": "В ответной переписке приветствие создает ощущение нового диалога и ломает контекст.",
        "bot_question_not_disclosed": "Если человек прямо спрашивает про автоматизацию, уклончивый ответ снижает доверие.",
        "link_sent_before_value_objection_resolved": "Ссылка до снятия сомнения выглядит как дожим и не отвечает на вопрос.",
        "repeated_link_after_link_problem": "Повтор той же ссылки не решает проблему и раздражает собеседника.",
        "continued_push_after_refusal": "После отказа нужно закрывать диалог, а не продолжать продавливание.",
        "overpromised_product_value": "Обещания готового продукта или результата противоречат стадии исследования.",
        "sent_link_after_manual_slot_offer": "Если человек уже предложил слоты, переключение на ссылку ухудшает UX.",
        "long_reply": "Слишком длинный ответ выглядит шаблонно и перегружает диалог.",
    }.get(reason, "Паттерн ухудшает естественность или надежность ответа.")


def better_behavior(reason: str) -> str:
    return {
        "reply_starts_with_greeting": "Продолжать диалог без приветствия, отвечая сразу по сути.",
        "bot_question_not_disclosed": "Коротко признать частичную автоматизацию и уточнить, что интервью ведется лично.",
        "link_sent_before_value_objection_resolved": "Сначала ответить на вопрос о ценности, затем мягко предложить следующий шаг.",
        "repeated_link_after_link_problem": "Перейти на ручное согласование слотов.",
        "continued_push_after_refusal": "Поблагодарить и завершить диалог.",
        "overpromised_product_value": "Говорить только про исследование и ручную проверку гипотез.",
        "sent_link_after_manual_slot_offer": "Выбрать один из предложенных слотов и подтвердить после проверки календаря.",
        "long_reply": "Сжать ответ до 1-3 предложений.",
    }.get(reason, "Выбрать более короткий, прямой и контекстный ответ.")


def render_negative_pattern_doc(pattern: dict) -> str:
    return "\n".join(
        [
            f"# Negative pattern: {pattern['bad_behavior']}",
            "",
            "```metadata",
            "type: negative_pattern",
            f"version: {EXPORT_VERSION}",
            f"pattern_key: {pattern['pattern_key']}",
            f"source_conversation_ids: {pattern['source_conversation_ids']}",
            "status: active",
            "```",
            "",
            "## Плохое поведение",
            pattern["bad_behavior"],
            "",
            "## Почему плохо",
            pattern["why_bad"],
            "",
            "## Как лучше",
            pattern["better_behavior"],
            "",
            "## Тестовые запросы",
            "\n".join(f"- {query}" for query in pattern["test_queries"]) or "- нет",
        ]
    ).strip() + "\n"


def build_eval_cases(candidates: list[dict], episodes_by_id: dict[str, dict]) -> list[dict]:
    cases = []
    for candidate in candidates:
        for episode_id in candidate["source_episode_ids"][:2]:
            episode = episodes_by_id.get(episode_id)
            if not episode:
                continue
            cases.append(
                {
                    "case_id": f"{episode_id}-{candidate['scenario_key']}",
                    "scenario_key": candidate["scenario_key"],
                    "source_conversation_ids": [episode["conversation_id"]],
                    "input_message": episode["last_user_message"],
                    "history": episode["history"][-6:],
                    "expected_retrieved": [f"scenario-{candidate['scenario_key']}.md"],
                    "expected_behavior": candidate["when_to_use"],
                    "forbidden_behavior": candidate["avoid_reply"],
                    "status": candidate["status"],
                }
            )
    return cases


def render_eval_case_doc(case: dict) -> str:
    history = "\n".join(f"- {message['role']}: {compact_text(message['text'], 260)}" for message in case["history"])
    return "\n".join(
        [
            f"# Eval case: {case['scenario_key']}",
            "",
            "```metadata",
            "type: eval_case",
            f"version: {EXPORT_VERSION}",
            f"case_id: {case['case_id']}",
            f"scenario_key: {case['scenario_key']}",
            f"source_conversation_ids: {case['source_conversation_ids']}",
            f"status: {case['status']}",
            "```",
            "",
            "## Input message",
            case["input_message"],
            "",
            "## History",
            history,
            "",
            "## Expected retrieved",
            "\n".join(f"- {item}" for item in case["expected_retrieved"]),
            "",
            "## Expected behavior",
            case["expected_behavior"],
            "",
            "## Forbidden behavior",
            case["forbidden_behavior"],
        ]
    ).strip() + "\n"


def select_examples(examples: list[dict]) -> list[dict]:
    good = [example for example in examples if example["quality_label"] == "good"]
    risky = [example for example in examples if example["quality_label"] == "risky"]
    review = [example for example in examples if example["quality_label"] == "review"]
    return (good[:3] + risky[:2] + review[:1])[:5]


def write_doc(path: Path, text: str, doc_type: str, source_ids: list[int], manifest_items: list[dict], *, status: str = "active") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    manifest_items.append(
        {
            "path": str(path),
            "name": path.name,
            "type": doc_type,
            "status": status,
            "source_conversation_ids": source_ids,
            "sha256": sha256_text(text),
            "bytes": len(text.encode("utf-8")),
        }
    )


def count_by(items: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--episodes", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    manifest = build_documents(args.candidates, args.episodes, args.out, args.manifest)
    print(
        {
            "document_count": manifest["document_count"],
            "counts_by_type": manifest["counts_by_type"],
            "counts_by_status": manifest["counts_by_status"],
            "out": str(args.out),
        }
    )


if __name__ == "__main__":
    main()
