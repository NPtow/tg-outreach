import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.dify_enrichment.analyze_export import build_inventory
from scripts.dify_enrichment.classify_episodes import build_candidates
from scripts.dify_enrichment.common import classify_scenario_key, sanitize_text
from scripts.dify_enrichment.extract_episodes import extract_episodes


class DifyEnrichmentTests(unittest.TestCase):
    def test_bot_keyword_does_not_match_rabotala(self):
        self.assertNotEqual(classify_scenario_key("Здравствуйте, в крупных компаниях я не работала"), "bot_or_automation_question")
        self.assertEqual(classify_scenario_key("Это бот?"), "bot_or_automation_question")

    def test_email_is_sanitized(self):
        self.assertEqual(sanitize_text("Напишите на test.user@example.com"), "Напишите на [email]")

    def test_minimal_export_pipeline(self):
        full = {
            "conversations": [
                {
                    "conversation": {
                        "id": 1,
                        "account_name": "Аккаунт",
                        "source_campaign_name": "HRD",
                        "status": "active",
                    },
                    "stats": {"message_count": 3, "assistant_count": 2, "user_count": 1},
                    "messages": [
                        {"id": 1, "role": "assistant", "text": "Первое сообщение", "created_at": "2026-04-28T10:00:00"},
                        {"id": 2, "role": "user", "text": "Это бот?", "created_at": "2026-04-28T10:01:00"},
                        {
                            "id": 3,
                            "role": "assistant",
                            "text": "Часть переписки автоматизирована, но интервью веду лично.",
                            "created_at": "2026-04-28T10:02:00",
                        },
                    ],
                }
            ]
        }
        summary = {
            "items": [
                {
                    "id": 1,
                    "account_name": "Аккаунт",
                    "campaign_name": "HRD",
                    "status": "active",
                    "message_count": 3,
                    "assistant_count": 2,
                    "user_count": 1,
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir)
            full_path = base / "full.json"
            summary_path = base / "summary.json"
            inventory_path = base / "conversation_inventory.json"
            full_path.write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
            summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")

            inventory = build_inventory(full_path, summary_path)
            inventory_path.write_text(json.dumps(inventory, ensure_ascii=False), encoding="utf-8")
            episodes = extract_episodes(full_path, inventory_path)
            candidates = build_candidates(episodes)

        self.assertEqual(inventory["total_conversations"], 1)
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["scenario_key"], "bot_or_automation_question")
        self.assertEqual(candidates["status_counts"], {"active": 1})


if __name__ == "__main__":
    unittest.main()
