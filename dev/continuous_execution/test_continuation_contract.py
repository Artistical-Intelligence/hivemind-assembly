"""Static ChatGPT Chat Mode instruction checks, not agent behavior or live acceptance.

Run from a complete repository checkout:
    python dev/continuous_execution/test_continuation_contract.py

These checks examine document linkage, required distinctions and Chat Mode surface/provider scope.
They do not prove a model follows prose, launch workers, access networks, change
schedules, validate runtime provider routing, or replace independent review.
"""
from pathlib import Path
import hashlib
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROCESS_PATH = ROOT / "dev" / "continuous_execution" / "PROCESS.md"
CLAUDE_BASELINE_BLOB = "0c8be2da28e6be34ef7220792e4ff8eda778529c"


class InstructionContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.process = PROCESS_PATH.read_text(encoding="utf-8")
        cls.agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        cls.chatgpt = (ROOT / "CHATGPT.md").read_text(encoding="utf-8")
        cls.chat_mode_profile = (ROOT / "_app" / "hivemind_assembly" / "automation" / "chat_mode_profile.py").read_text(encoding="utf-8")
        cls.claude_bytes = (ROOT / "CLAUDE.md").read_bytes()
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

    def test_02_ten_steps_live_in_chatgpt_profile(self):
        core = self.chatgpt.split("## Core adaptive execution and incremental progress", 1)[1].split("## Harness routing", 1)[0]
        self.assertEqual(re.findall(r"^(\d+)\. ", core, re.M), [str(n) for n in range(1, 11)])
        self.assertNotIn("## Core adaptive execution and incremental progress", self.agents)

    def test_03_scoped_entrypoints_link_process(self):
        for text in (self.agents, self.queue, self.chatgpt):
            self.assertIn("dev/continuous_execution/PROCESS.md", text)
        for text in (self.agents, self.queue):
            self.assertIn("CHATGPT.md", text)
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
        self.assertIn("not a fixed backlog cap or a global barrier", " ".join(self.queue.split()))
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
        self.assertIn("AGENTS.md; CHATGPT.md; QUEUE.md", self.root_status)
        self.assertIn("test_continuation_contract.py", self.register)
        self.assertIn("dev/continuous_execution", self.register)

    def test_16_no_new_performance_ledger(self):
        self.assertIn("not a second general-purpose coordinator or ledger", self.section(9))
        self.assertIn("mandatory operational cost/performance dashboard", self.section(10))
        self.assertIn("unchanged closure count", self.section(10))

    def test_17_explicit_chat_mode_only_scope(self):
        self.assertIn("Provider/surface scope: **ChatGPT in Chat Mode only**", self.chatgpt)
        self.assertIn("## Provider/surface scope — ChatGPT Chat Mode only", self.process)
        self.assertIn("**ChatGPT Chat Mode only:**", self.agents)
        self.assertIn("For **ChatGPT Chat Mode sessions only**", self.queue)
        self.assertIn("not an instruction for ChatGPT Work, Codex, Claude", self.agents)

    def test_18_claude_policy_is_unchanged(self):
        data = self.claude_bytes
        actual = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        self.assertEqual(actual, CLAUDE_BASELINE_BLOB, "Reconcile any independently authorized Claude change; do not silently adopt the ChatGPT profile.")
        self.assertNotIn(b"CHATGPT.md", data)
        self.assertNotIn(b"continuous_execution", data)

    def test_19_no_cross_surface_prompt_default(self):
        self.assertIn("not a provider-neutral or all-OpenAI HA execution policy", self.process)
        self.assertIn("common, unknown-provider, unknown-surface, or generic OpenAI default", self.process)
        self.assertIn("Never append it to ChatGPT Work, Codex", self.process)
        self.assertIn("separate owner authorization and surface-specific validation", self.chatgpt)

    def test_20_no_universal_capability_inference(self):
        self.assertIn("does not mean every proposed capability is already verified even within Chat Mode", self.process)
        self.assertIn("Evidence from Chat Mode does not establish capabilities in Work, Codex, Claude", self.chatgpt)
        self.assertIn("provider-routing code, prompt injection or lifecycle behavior", self.process)

    def test_21_work_and_codex_are_explicitly_excluded(self):
        for text in (self.chatgpt, self.process, self.agents, self.queue):
            self.assertIn("ChatGPT Work", text)
            self.assertIn("Codex", text)
        self.assertIn("only when both ChatGPT and Chat Mode are explicitly selected", self.process)
        self.assertIn("Do not select it merely because the provider is OpenAI or the product is ChatGPT", self.chatgpt)


    def test_22_open_ended_evidence_driven_chain_not_preset_loop(self):
        self.assertIn("Adaptive task chains are not preset loops", self.chatgpt)
        self.assertIn("no arbitrary limit on the number of handoffs", self.chatgpt)
        self.assertIn("A chain is not a loop", self.chatgpt)
        self.assertIn("Evidence-driven task chains, not prescheduled loops", self.process)
        self.assertIn("no arbitrary total length", self.process)
        self.assertIn("new observation makes a concrete next task useful", self.process)
        self.assertIn("five-minute ad hoc deadlines", self.process.lower())
        self.assertIn("Never use a one-time chain to evade", self.process)
        self.assertIn("ADAPTIVE TASK CHAIN (not a fixed repeating loop)", self.chat_mode_profile)
        self.assertIn("total number of handoffs or on coherent chunk size", self.chat_mode_profile)
        self.assertIn("Do not automatically pre-create successor tasks", self.chat_mode_profile)
        self.assertIn("finite chain-length cap in a safety probe does not cap real large-task work", self.chat_mode_profile)
        self.assertIn("ChatGPT Work, Codex", self.chat_mode_profile)


if __name__ == "__main__":
    unittest.main(verbosity=2)
