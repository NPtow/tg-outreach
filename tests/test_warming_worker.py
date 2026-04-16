import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from backend.warming_worker import WarmingWorker


class WarmingWorkerPlannerTests(unittest.TestCase):
    def setUp(self):
        self.worker = WarmingWorker(1)
        self.client = object()

    @patch("backend.warming_worker._pick_channels", return_value=[])
    @patch("backend.warming_worker._get_peer_clients", return_value=[])
    @patch("backend.warming_worker._get_warming_state")
    def test_build_action_list_omits_mutual_messages_without_peers(
        self,
        mock_state,
        _mock_peer_clients,
        _mock_channels,
    ):
        mock_state.return_value = {
            "account_id": 1,
            "status": "warming",
            "phase": 1,
            "peer_account_ids": [],
            "subscribed_channels": [],
            "online_sessions_today": 0,
            "subscriptions_today": 0,
            "reactions_today": 0,
            "searches_today": 0,
            "dialog_reads_today": 0,
            "mutual_messages_today": 0,
            "blocked_actions": {},
        }

        actions, skipped = self.worker._build_action_list(
            self.client,
            {"mutual_messages_per_day": 2},
        )

        self.assertNotIn("msg_sent", [action.action_type for action in actions])
        self.assertFalse(any(item["action_type"] == "msg_sent" for item in skipped))

    @patch("backend.warming_worker._pick_channels", return_value=[])
    @patch("backend.warming_worker._get_peer_clients", return_value=[])
    @patch("backend.warming_worker._get_warming_state")
    def test_build_action_list_omits_search_when_temporarily_blocked(
        self,
        mock_state,
        _mock_peer_clients,
        _mock_channels,
    ):
        mock_state.return_value = {
            "account_id": 1,
            "status": "warming",
            "phase": 1,
            "peer_account_ids": [],
            "subscribed_channels": [],
            "online_sessions_today": 0,
            "subscriptions_today": 0,
            "reactions_today": 0,
            "searches_today": 0,
            "dialog_reads_today": 0,
            "mutual_messages_today": 0,
            "blocked_actions": {
                "search": {
                    "reason": "FROZEN_METHOD_INVALID",
                    "until": (datetime.utcnow() + timedelta(hours=12)).isoformat(),
                }
            },
        }

        actions, skipped = self.worker._build_action_list(
            self.client,
            {"searches_per_day": 1},
        )

        self.assertNotIn("search", [action.action_type for action in actions])
        self.assertFalse(any(item["action_type"] == "search" for item in skipped))

    @patch(
        "backend.warming_worker._pick_channels",
        return_value=[
            {
                "username": "verified_channel",
                "verification_status": "verified",
                "peer_id": "123",
                "access_hash": "456",
                "resolve_fail_count": 0,
            }
        ],
    )
    @patch("backend.warming_worker._get_peer_clients", return_value=[])
    @patch("backend.warming_worker._get_warming_state")
    def test_build_action_list_keeps_verified_subscribe_when_username_resolve_blocked(
        self,
        mock_state,
        _mock_peer_clients,
        _mock_channels,
    ):
        mock_state.return_value = {
            "account_id": 1,
            "status": "warming",
            "phase": 1,
            "peer_account_ids": [],
            "subscribed_channels": [],
            "online_sessions_today": 0,
            "subscriptions_today": 0,
            "reactions_today": 0,
            "searches_today": 0,
            "dialog_reads_today": 0,
            "mutual_messages_today": 0,
            "blocked_actions": {
                "subscribe_username_resolve": {
                    "reason": "username_resolve_failed",
                    "until": (datetime.utcnow() + timedelta(hours=12)).isoformat(),
                }
            },
        }

        actions, skipped = self.worker._build_action_list(
            self.client,
            {"subscriptions_per_day": 1},
        )

        self.assertIn("subscribe", [action.action_type for action in actions])
        self.assertFalse(any(item["action_type"] == "subscribe" for item in skipped))


if __name__ == "__main__":
    unittest.main()
