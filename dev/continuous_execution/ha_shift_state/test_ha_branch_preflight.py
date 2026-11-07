"""Isolated local synthetic tests: no repository, browser, model or network."""
import copy
import unittest
from ha_branch_preflight import classify, EXPECTED

MAIN = "a" * 40
HEADS = ["b" * 40, "c" * 40, "d" * 40, "e" * 40]

def sample():
    changes = [
        (82, 305, [{"filename": "_app/hivemind_assembly/automation/browser_actions.py", "status": "modified"}]),
        (0, 740, []),
        (1, 663, [{"filename": "experiments/chatmode-scheduled-github-20261104.md", "status": "added"}]),
        (16, 716, [{"filename": "tests/test_browser_setup_lifecycle.py", "status": "added"}]),
    ]
    return {"main_sha": MAIN, "branches": [
        {"name": name, "head_sha": sha, "compared_main_sha": MAIN,
         "ahead_by": a, "behind_by": b, "too_large": False, "files": f}
        for (name, sha, (a,b,f)) in zip(EXPECTED, HEADS, changes)]}

class TestPreflight(unittest.TestCase):
    def test_real_shape_four_branches_all_unmerged(self):
        result = classify(sample())
        self.assertEqual([r["disposition"] for r in result["branches"]], [
            "UNMERGED_UNREVIEWED_SOURCE_DO_NOT_MERGE",
            "NO_UNIQUE_COMMITS_DO_NOT_MERGE",
            "HISTORICAL_EVIDENCE_ONLY_NEEDS_OWNER_DISPOSITION",
            "UNMERGED_UNREVIEWED_SOURCE_DO_NOT_MERGE"])
        self.assertFalse(any(r["merge_authorized"] for r in result["branches"]))

    def test_stale_compare_is_rejected(self):
        s = sample(); s["branches"][0]["compared_main_sha"] = "f" * 40
        with self.assertRaisesRegex(ValueError, "stale"):
            classify(s)

    def test_incomplete_compare_is_rejected(self):
        s = sample(); s["branches"][0]["too_large"] = True
        with self.assertRaisesRegex(ValueError, "stale"):
            classify(s)

    def test_missing_or_duplicate_branch_is_rejected(self):
        s = sample(); s["branches"][1]["name"] = EXPECTED[0]
        with self.assertRaisesRegex(ValueError, "missing/duplicate"):
            classify(s)

    def test_path_traversal_and_duplicate_diff_is_rejected(self):
        for files in ([{"filename": "../../bad", "status": "added"}],
                      [{"filename": "tests/x.py", "status": "added"}]*2):
            s = sample(); s["branches"][0]["files"] = files
            with self.assertRaises(ValueError):
                classify(s)

    def test_forged_bool_count_rejected(self):
        s = sample(); s["branches"][1]["ahead_by"] = True
        with self.assertRaisesRegex(ValueError, "invalid ahead"):
            classify(s)

    def test_ahead_empty_diff_and_behind_changed_rejected(self):
        for i, f in [(0, []), (1, [{"filename": "X", "status": "added"}])]:
            s = sample(); s["branches"][i]["files"] = f
            with self.assertRaises(ValueError):
                classify(s)

if __name__ == "__main__":
    unittest.main()
