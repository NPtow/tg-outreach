from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from scripts.dify_enrichment.common import (
    assistant_text,
    compact_text,
    detect_flags,
    load_json,
    markdown_table,
    normalize_conversations,
    user_text,
    write_json,
)


def build_inventory(full_path: Path, summary_path: Path) -> dict:
    full_export = load_json(full_path)
    summary_export = load_json(summary_path)
    conversations = normalize_conversations(full_export)
    summary_by_id = {int(item["id"]): item for item in summary_export.get("items", [])}

    items = []
    excluded = []
    flag_counts = Counter()
    campaign_counts = Counter()
    account_counts = Counter()
    status_counts = Counter()

    for conversation in conversations:
        user_body = user_text(conversation.messages)
        assistant_body = assistant_text(conversation.messages)
        flags = detect_flags(user_body)
        for flag, enabled in flags.items():
            if enabled:
                flag_counts[flag] += 1
        campaign_counts[conversation.campaign_name or "unknown"] += 1
        account_counts[conversation.account_name or "unknown"] += 1
        status_counts[conversation.status or "unknown"] += 1

        exclude_reasons = []
        if not conversation.messages:
            exclude_reasons.append("no_messages")
        if conversation.user_count <= 0:
            exclude_reasons.append("no_user_messages")
        if conversation.assistant_count <= 0:
            exclude_reasons.append("no_assistant_messages")
        if exclude_reasons:
            excluded.append({"conversation_id": conversation.id, "reasons": exclude_reasons})

        summary_item = summary_by_id.get(conversation.id, {})
        user_messages = [message.text for message in conversation.messages if message.role == "user"]
        assistant_messages = [message.text for message in conversation.messages if message.role == "assistant"]
        items.append(
            {
                "conversation_id": conversation.id,
                "account_name": conversation.account_name or summary_item.get("account_name", ""),
                "campaign_name": conversation.campaign_name or summary_item.get("campaign_name", ""),
                "status": conversation.status or summary_item.get("status", ""),
                "message_count": conversation.message_count,
                "assistant_count": conversation.assistant_count,
                "user_count": conversation.user_count,
                "first_user_message_at": conversation.first_user_message_at,
                "last_message_at": conversation.last_message_at,
                "flags": flags,
                "last_user_message": compact_text(user_messages[-1] if user_messages else ""),
                "last_assistant_message": compact_text(assistant_messages[-1] if assistant_messages else ""),
                "exclude_reasons": exclude_reasons,
            }
        )

    return {
        "source_full": str(full_path),
        "source_summary": str(summary_path),
        "total_conversations": len(conversations),
        "summary_items": len(summary_export.get("items", [])),
        "excluded": excluded,
        "stats": {
            "campaign_counts": dict(campaign_counts),
            "account_counts": dict(account_counts),
            "status_counts": dict(status_counts),
            "flag_counts": dict(flag_counts),
        },
        "items": sorted(items, key=lambda item: item["conversation_id"]),
    }


def render_inventory_markdown(inventory: dict) -> str:
    stats = inventory["stats"]
    rows = []
    for item in inventory["items"]:
        active_flags = [key for key, enabled in item["flags"].items() if enabled]
        rows.append(
            [
                item["conversation_id"],
                item["campaign_name"],
                item["account_name"],
                item["status"],
                item["message_count"],
                item["user_count"],
                item["assistant_count"],
                ", ".join(active_flags) or "-",
                item["last_user_message"],
            ]
        )
    return "\n\n".join(
        [
            "# Conversation inventory",
            f"- Total conversations: `{inventory['total_conversations']}`",
            f"- Summary items: `{inventory['summary_items']}`",
            f"- Excluded: `{len(inventory['excluded'])}`",
            "",
            "## Campaign counts",
            markdown_table(["Campaign", "Count"], [[key, value] for key, value in stats["campaign_counts"].items()]),
            "",
            "## Account counts",
            markdown_table(["Account", "Count"], [[key, value] for key, value in stats["account_counts"].items()]),
            "",
            "## Flag counts",
            markdown_table(["Flag", "Count"], [[key, value] for key, value in sorted(stats["flag_counts"].items())]),
            "",
            "## Conversations",
            markdown_table(
                ["ID", "Campaign", "Account", "Status", "Messages", "User", "Assistant", "Flags", "Last user message"],
                rows,
            ),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    inventory = build_inventory(args.full, args.summary)
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / "conversation_inventory.json", inventory)
    (args.out / "conversation_inventory.md").write_text(render_inventory_markdown(inventory), encoding="utf-8")
    print(
        {
            "total_conversations": inventory["total_conversations"],
            "summary_items": inventory["summary_items"],
            "excluded": len(inventory["excluded"]),
            "out": str(args.out),
        }
    )


if __name__ == "__main__":
    main()
