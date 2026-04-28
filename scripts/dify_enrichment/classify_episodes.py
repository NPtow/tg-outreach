from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from scripts.dify_enrichment.common import (
    SCENARIO_BY_KEY,
    compact_text,
    read_jsonl,
    write_json,
)


def build_candidates(episodes: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for episode in episodes:
        grouped[episode["scenario_key"]].append(episode)

    candidates = []
    review_items = []
    for key, group in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        if key == "unknown":
            review_items.extend(group)
            continue
        definition = SCENARIO_BY_KEY[key]
        quality_counts = Counter(episode["quality_label"] for episode in group)
        source_ids = sorted({episode["conversation_id"] for episode in group})
        trigger_phrases = unique_compact([episode["last_user_message"] for episode in group], limit=8)
        good_replies = unique_compact(
            [episode["assistant_reply"] for episode in group if episode["quality_label"] == "good"],
            limit=5,
            text_limit=300,
        )
        risky_reasons = Counter(reason for episode in group for reason in episode.get("quality_reasons", []))
        confidence = score_confidence(total=len(group), quality_counts=quality_counts, source_count=len(source_ids))
        review_required = needs_review(total=len(group), quality_counts=quality_counts)
        candidates.append(
            {
                "scenario_key": key,
                "title": definition.title,
                "intent": definition.intent,
                "stage": definition.stage,
                "group": definition.group,
                "trigger_phrases": trigger_phrases,
                "when_to_use": definition.when_to_use,
                "recommended_reply": good_replies[0] if good_replies else definition.recommended_reply,
                "fallback_recommended_reply": definition.recommended_reply,
                "good_reply_examples": good_replies,
                "avoid_reply": definition.avoid_reply,
                "source_conversation_ids": source_ids,
                "source_episode_ids": [episode["episode_id"] for episode in group],
                "episode_count": len(group),
                "quality_counts": dict(quality_counts),
                "risky_reasons": dict(risky_reasons),
                "confidence": confidence,
                "review_required": review_required,
                "status": "active",
                "version": "2026-04-28-prod-replies-v1",
            }
        )

    return {
        "version": "2026-04-28-prod-replies-v1",
        "total_episodes": len(episodes),
        "total_candidates": len(candidates),
        "status_counts": dict(Counter(candidate["status"] for candidate in candidates)),
        "quality_counts": dict(Counter(episode["quality_label"] for episode in episodes)),
        "candidates": candidates,
        "unknown_episodes": [
            {
                "episode_id": episode["episode_id"],
                "conversation_id": episode["conversation_id"],
                "last_user_message": episode["last_user_message"],
                "assistant_reply": compact_text(episode["assistant_reply"], 280),
            }
            for episode in review_items
        ],
    }


def unique_compact(values: list[str], *, limit: int, text_limit: int = 180) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        compacted = compact_text(value, text_limit)
        key = compacted.lower()
        if not compacted or key in seen:
            continue
        seen.add(key)
        result.append(compacted)
        if len(result) >= limit:
            break
    return result


def score_confidence(*, total: int, quality_counts: Counter, source_count: int) -> float:
    score = 0.42
    score += min(total, 6) * 0.055
    score += min(source_count, 5) * 0.035
    score += quality_counts["good"] * 0.025
    score -= quality_counts["risky"] * 0.08
    score -= quality_counts["review"] * 0.025
    return round(max(0.05, min(0.98, score)), 2)


def needs_review(*, total: int, quality_counts: Counter) -> bool:
    if total <= 1:
        return True
    if quality_counts["risky"] >= max(2, quality_counts["good"]):
        return True
    if quality_counts["review"] > 0 and total <= 2:
        return True
    return False


def render_review(candidates_data: dict) -> str:
    candidates = candidates_data["candidates"]
    lines = [
        "# Scenario candidates review",
        f"- Episodes: `{candidates_data['total_episodes']}`",
        f"- Candidates: `{candidates_data['total_candidates']}`",
        f"- Status counts: `{candidates_data['status_counts']}`",
        f"- Unknown episodes: `{len(candidates_data['unknown_episodes'])}`",
        "",
        "## Active candidates",
    ]
    for candidate in [item for item in candidates if item["status"] == "active"]:
        lines.append(
            f"- `{candidate['scenario_key']}` {candidate['title']} "
            f"episodes={candidate['episode_count']} confidence={candidate['confidence']} "
            f"review_required={candidate['review_required']} sources={candidate['source_conversation_ids']}"
        )
    lines.extend(["", "## Needs review"])
    for candidate in [item for item in candidates if item.get("review_required")]:
        lines.append(
            f"- `{candidate['scenario_key']}` {candidate['title']} "
            f"episodes={candidate['episode_count']} confidence={candidate['confidence']} "
            f"risk={candidate['risky_reasons']}"
        )
    lines.extend(["", "## Unknown episodes"])
    for episode in candidates_data["unknown_episodes"][:40]:
        lines.append(f"- `{episode['episode_id']}` user={compact_text(episode['last_user_message'], 180)}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", required=True, type=Path)
    parser.add_argument("--taxonomy", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--review-out", type=Path)
    args = parser.parse_args()

    episodes = read_jsonl(args.episodes)
    candidates = build_candidates(episodes)
    write_json(args.out, candidates)
    review_path = args.review_out or args.out.with_name("scenario_candidates_review.md")
    review_path.write_text(render_review(candidates), encoding="utf-8")
    print(
        {
            "episodes": candidates["total_episodes"],
            "candidates": candidates["total_candidates"],
            "status_counts": candidates["status_counts"],
            "unknown": len(candidates["unknown_episodes"]),
            "out": str(args.out),
        }
    )


if __name__ == "__main__":
    main()
