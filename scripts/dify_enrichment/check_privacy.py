from __future__ import annotations

import argparse
import re
from pathlib import Path

from scripts.dify_enrichment.common import write_json


PATTERNS = {
    "telegram_username": re.compile(r"@[A-Za-z0-9_]{3,}"),
    "long_numeric_id": re.compile(r"\b\d{7,}\b"),
    "secret_like": re.compile(r"\b(?:sk-|sbp_|GOCSPX-|dataset-)[A-Za-z0-9_\-]{8,}"),
}


def scan_docs(docs_dir: Path) -> dict:
    findings = []
    for path in sorted(docs_dir.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "path": str(path),
                        "type": name,
                        "match": match.group(0),
                        "position": match.start(),
                    }
                )
    return {
        "docs_dir": str(docs_dir),
        "critical_findings": len(findings),
        "findings": findings[:200],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    report = scan_docs(args.docs)
    if args.out:
        write_json(args.out, report)
    print({"critical_findings": report["critical_findings"], "docs": str(args.docs)})
    if report["critical_findings"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
