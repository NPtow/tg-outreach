from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from scripts.dify_enrichment.common import (
    classify_scenario_key,
    compact_text,
    load_json,
    normalize_conversations,
    quality_label,
    sanitize_text,
    stage_for_scenario_key,
    write_jsonl,
)


def extract_episodes(full_export_path: Path, inventory_path: Path) -> list[dict]:
    full_export = load_json(full_export_path)
    inventory = load_json(inventory_path)
    excluded_ids = {item["conversation_id"] for item in inventory.get("excluded", [])}
    conversations = normalize_conversations(full_export)
    episodes: list[dict] = []

    for conversation in conversations:
        if conversation.id in excluded_ids:
            continue
        pending_user_indexes: list[int] = []
        local_index = 0
        for index, message in enumerate(conversation.messages):
            if message.role == "user":
                pending_user_indexes.append(index)
                continue
            if message.role != "assistant" or not pending_user_indexes:
                continue

            user_turn = "\n".join(conversation.messages[user_index].text for user_index in pending_user_indexes)
            if not user_turn.strip():
                pending_user_indexes = []
                continue
            scenario_key = classify_scenario_key(user_turn)
            if scenario_key == "unknown":
                context_start = max(0, pending_user_indexes[0] - 3)
                context_text = "\n".join(history_message.text for history_message in conversation.messages[context_start : index + 1])
                scenario_key = classify_scenario_key(context_text)
            label, reasons = quality_label(user_turn, message.text)
            history_start = max(0, pending_user_indexes[0] - 8)
            history_messages = conversation.messages[history_start : index + 1]
            local_index += 1
            episodes.append(
                {
                    "episode_id": f"{conversation.id}-{local_index}",
                    "conversation_id": conversation.id,
                    "account_name": conversation.account_name,
                    "campaign_name": conversation.campaign_name,
                    "conversation_status": conversation.status,
                    "stage": stage_for_scenario_key(scenario_key),
                    "scenario_key": scenario_key,
                    "last_user_message": sanitize_text(conversation.messages[pending_user_indexes[-1]].text),
                    "user_turn": sanitize_text(user_turn),
                    "assistant_reply": sanitize_text(message.text),
                    "assistant_message_id": message.id,
                    "assistant_created_at": message.created_at,
                    "history": [
                        {
                            "role": history_message.role,
                            "text": sanitize_text(history_message.text),
                            "created_at": history_message.created_at,
                        }
                        for history_message in history_messages[-10:]
                    ],
                    "quality_label": label,
                    "quality_reasons": reasons,
                }
            )
            pending_user_indexes = []

    return dedupe_episodes(episodes)


def dedupe_episodes(episodes: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict] = []
    for episode in episodes:
        fingerprint = (
            episode["scenario_key"],
            compact_text(episode["last_user_message"], 180).lower(),
            compact_text(episode["assistant_reply"], 220).lower(),
        )
        if fingerprint in seen:
            episode["dedupe_status"] = "duplicate"
            continue
        seen.add(fingerprint)
        episode["dedupe_status"] = "unique"
        deduped.append(episode)
    return deduped


def render_review(episodes: list[dict]) -> str:
    scenario_counts = Counter(episode["scenario_key"] for episode in episodes)
    quality_counts = Counter(episode["quality_label"] for episode in episodes)
    stage_counts = Counter(episode["stage"] for episode in episodes)
    risky = [episode for episode in episodes if episode["quality_label"] == "risky"]
    lines = [
        "# Episodes review",
        f"- Episodes: `{len(episodes)}`",
        f"- Scenario keys: `{len(scenario_counts)}`",
        f"- Quality: `{dict(quality_counts)}`",
        f"- Stages: `{dict(stage_counts)}`",
        "",
        "## Scenario counts",
    ]
    for key, count in scenario_counts.most_common():
        lines.append(f"- `{key}`: {count}")
    lines.extend(["", "## Risky episodes"])
    for episode in risky[:50]:
        lines.append(
            f"- `{episode['episode_id']}` `{episode['scenario_key']}` reasons={episode['quality_reasons']} "
            f"user={compact_text(episode['last_user_message'], 160)} reply={compact_text(episode['assistant_reply'], 180)}"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--review-out", type=Path)
    args = parser.parse_args()

    episodes = extract_episodes(args.full, args.inventory)
    write_jsonl(args.out, episodes)
    review_path = args.review_out or args.out.with_name("episodes_review.md")
    review_path.write_text(render_review(episodes), encoding="utf-8")
    print({"episodes": len(episodes), "out": str(args.out), "review": str(review_path)})


if __name__ == "__main__":
    main()
