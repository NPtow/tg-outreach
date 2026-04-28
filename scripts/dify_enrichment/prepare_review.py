from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from scripts.dify_enrichment.common import load_json, markdown_table, write_json


def build_review(manifest_path: Path, candidates_path: Path) -> dict:
    manifest = load_json(manifest_path)
    candidates = load_json(candidates_path)
    docs = manifest["documents"]
    return {
        "version": manifest["version"],
        "document_count": manifest["document_count"],
        "counts_by_type": manifest["counts_by_type"],
        "counts_by_status": manifest["counts_by_status"],
        "scenario_status_counts": candidates["status_counts"],
        "unknown_episodes": len(candidates["unknown_episodes"]),
        "active_scenarios": [item for item in candidates["candidates"] if item["status"] == "active"],
        "review_scenarios": [item for item in candidates["candidates"] if item["status"] == "review"],
        "review_required_scenarios": [item for item in candidates["candidates"] if item.get("review_required")],
        "dry_run_operations": [
            {
                "operation": "create_or_update_document",
                "name": doc["name"],
                "type": doc["type"],
                "status": doc["status"],
                "source_conversation_ids": doc["source_conversation_ids"],
                "sha256": doc["sha256"],
            }
            for doc in docs
        ],
    }


def render_review_markdown(review: dict) -> str:
    scenario_rows = [
        [
            item["scenario_key"],
            item["status"],
            item.get("review_required", False),
            item["stage"],
            item["episode_count"],
            item["confidence"],
            item["quality_counts"],
            item["title"],
        ]
        for item in review["active_scenarios"] + review["review_scenarios"]
    ]
    operation_counts = Counter(item["type"] for item in review["dry_run_operations"])
    return "\n\n".join(
        [
            "# Railway Dify enrichment review",
            f"- Version: `{review['version']}`",
            f"- Documents to create/update: `{review['document_count']}`",
            f"- Counts by type: `{review['counts_by_type']}`",
            f"- Counts by status: `{review['counts_by_status']}`",
            f"- Scenario status counts: `{review['scenario_status_counts']}`",
            f"- Scenarios requiring review: `{len(review['review_required_scenarios'])}`",
            f"- Unknown episodes: `{review['unknown_episodes']}`",
            "",
            "## Scenario candidates",
            markdown_table(["Key", "Status", "Review", "Stage", "Episodes", "Confidence", "Quality", "Title"], scenario_rows),
            "",
            "## Dry-run Dify operations",
            markdown_table(["Type", "Count"], [[key, value] for key, value in sorted(operation_counts.items())]),
            "",
            "## Review scenarios",
            "\n".join(
                f"- `{item['scenario_key']}` confidence={item['confidence']} risk={item['risky_reasons']} title={item['title']}"
                for item in review["review_required_scenarios"]
            )
            or "Нет сценариев, требующих review.",
            "",
            "## Next gate",
            "Перед upload в Railway Dify нужно просмотреть сценарии с review_required=true и решить: оставить active, поправить текст или merge.",
        ]
    ) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    review = build_review(args.manifest, args.candidates)
    args.out.write_text(render_review_markdown(review), encoding="utf-8")
    json_out = args.json_out or args.out.with_suffix(".json")
    write_json(json_out, review)
    print(
        {
            "document_count": review["document_count"],
            "active_scenarios": len(review["active_scenarios"]),
            "review_required_scenarios": len(review["review_required_scenarios"]),
            "out": str(args.out),
        }
    )


if __name__ == "__main__":
    main()
