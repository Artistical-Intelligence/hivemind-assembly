"""Static instruction checks only; not agent behavior or live runtime acceptance.

Run from a complete repository checkout:
    python dev/continuous_execution/test_continuation_contract.py

These tests guard the presence, linkage and distinctions in the owner-adopted
process. They do not prove that a model follows prose, launch any workers, access
networks, change schedules, or replace independent review.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROCESS_PATH = ROOT / "dev" / "continuous_execution" / "PROCESS.md"


class InstructionContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.process = PROCESS_PATH.read_text(encoding="utf-8")
        cls.agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        cls.queue = (ROOT / "QUEUE.md").read_text(encoding="utf-8")
        cls.register = (ROOT / "CHECKS_STATUS.md").read_text(encoding="utf-8")
        cls.local_status = PROCESS_PATH.with_name("STATUS.md").read_text(encoding="utf-8")
        cls.root_status = (ROOT / "STATUS.md").read_text(encoding="utf-8")

    def section(self, number):
        match = re.search(rf"^## {number}\. .*?(?=^## |\Z)", self.process, re.M | re.S)
        self.assertIsNotNone(match, f"Missing process step {number}")
        return match.group(0)

    def test_01_exactly_ten_steps(self):
        self.assertEqual(re.findall(r"^## (\d+)\. ", self.process, re.M), [str(n) for n in range(1, 11)])

    def test_02_core_agent_steps(self):
        core = self.agents.split("## Core adaptive execution and incremental progress", 1)[1].split("## Setup UX preference", 1)[0]
        self.assertEqual(re.findall(r"^(\d+)\. ", core, re.M), [str(n) for n in range(1, 11)])

    def test_03_root_entrypoints_link_process(self):
        for text in (self.agents, self.queue):
            self.assertIn("dev/continuous_execution/PROCESS.md", text)
        self.assertTrue(PROCESS_PATH.is_file())

    def test_04_step_five_has_no_arbitrary_cap(self):
        text = self.section(5)
        self.assertIn("no fixed cap on pending work", text)
        self.assertIn("Continue useful independent or preparatory work", text)
        self.assertIn("Pause or defer only the affected path", text)

    def test_05_step_six_preserves_large_tasks(self):
        text = self.section(6)
        self.assertIn("A chunk may exceed one wave", text)
        self.assertIn("Maintain the same parent objective", text)
        self.assertIn("A smaller recovery slice does not shrink the total assignment", text)

    def test_06_checkpoints_are_not_stop_commands(self):
        self.assertIn("Checkpoints are recovery points, not stop commands", self.process)
        self.assertIn("Continue after a saved milestone", self.section(6))
        self.assertIn("one-unit-per-wave", self.section(6))

    def test_07_read_and_decide_is_not_forced_novelty(self):
        self.assertIn("An unchanged plan is valid", self.section(1))
        self.assertIn("current project revision", self.section(1))
        self.assertIn("do not manufacture a new decision", self.section(1))

    def test_08_partial_progress_not_false_acceptance(self):
        self.assertIn("Durable partial work is real progress", self.process)
        self.assertIn("incremental progress", self.section(2))
        self.assertIn("independent acceptance", self.section(2))

    def test_09_missing_checker_not_global_halt(self):
        self.assertIn("not every useful reading, writing", self.section(4))
        self.assertIn("not a global barrier", self.queue)
        self.assertIn("Do not idle solely because many drafts exist", self.section(5))

    def test_10_cross_chat_does_not_imply_independence(self):
        self.assertIn("different chat from the owner conversation", self.process)
        self.assertIn("A different chat or task identifier proves neither", self.process)
        self.assertIn("fresh context nor independence", self.process)

    def test_11_automation_and_review_validation_are_distinct(self):
        self.assertIn("without conflating source-validation results", self.section(8))
        self.assertIn("contract simulation", self.section(8))
        self.assertIn("does not prove scheduler-level duplicate prevention", self.section(8))

    def test_12_recovery_and_writer_safeguards(self):
        text = self.section(9)
        for phrase in ("one integration owner", "writer epochs and fencing", "inspect what reached the repository before retrying", "Preserve newer remote work"):
            self.assertIn(phrase, text)

    def test_13_no_human_relay_or_scope_expansion(self):
        self.assertIn("AI-only work remains AI-owned", self.process)
        self.assertIn("Mandatory authorization still applies", self.process)
        self.assertIn("no prompt refinement extends an expired schedule", self.process)
        self.assertIn("textbook access", self.process)

    def test_14_no_runtime_acceptance_claim(self):
        self.assertIn("does not implement a new scheduler", self.process)
        self.assertIn("Static instruction checks are not live runtime acceptance", self.process)
        self.assertIn("Hermes", self.process)

    def test_15_pending_records_present(self):
        self.assertIn("CHECKS PENDING", self.local_status)
        self.assertIn("PROCESS.md", self.local_status)
        self.assertIn("AGENTS.md; QUEUE.md", self.root_status)
        self.assertIn("test_continuation_contract.py", self.register)
        self.assertIn("dev/continuous_execution", self.register)

    def test_16_no_new_performance_ledger(self):
        self.assertIn("not a second general-purpose coordinator or ledger", self.section(9))
        self.assertIn("mandatory operational cost/performance dashboard", self.section(10))
        self.assertIn("unchanged closure count", self.section(10))


if __name__ == "__main__":
    unittest.main(verbosity=2)
