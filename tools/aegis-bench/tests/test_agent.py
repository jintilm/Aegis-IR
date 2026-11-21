"""Optional effective-options protocol without importing external adapters."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aegis_bench.agent import AdapterError, Agent, create_agent  # noqa: E402


class EffectiveAgent(Agent):
    def __init__(self, limit=None, api_key=None):
        self.limit = int(os.environ.get("AEGIS_TEST_LIMIT", "3")) if limit is None else limit

    def effective_options(self):
        return {"limit": self.limit}

    def solve(self, task, workspace):
        raise AssertionError("not used")


class InvalidOptionsAgent(EffectiveAgent):
    def effective_options(self):
        return {"limit": float("nan")}


class AgentOptionsTests(unittest.TestCase):
    def test_existing_adapters_keep_caller_options(self):
        self.assertEqual(create_agent("stub").adapter_options, {})
        self.assertEqual(create_agent("model-stub", model="offline").adapter_options,
                         {"model": "offline"})

    def test_opt_in_freezes_defaults_for_worker_replay_without_secrets(self):
        spec = f"{__name__}:EffectiveAgent"
        with patch.dict(os.environ, {"AEGIS_TEST_LIMIT": "7"}):
            agent = create_agent(spec, api_key="not-recorded")
        self.assertEqual(agent.adapter_options, {"limit": 7})
        with patch.dict(os.environ, {"AEGIS_TEST_LIMIT": "99"}):
            replayed = create_agent(spec, **agent.adapter_options)
        self.assertEqual(replayed.limit, 7)

    def test_non_json_options_fail_closed(self):
        with self.assertRaisesRegex(AdapterError, "finite JSON"):
            create_agent(f"{__name__}:InvalidOptionsAgent")


if __name__ == "__main__":
    unittest.main()
