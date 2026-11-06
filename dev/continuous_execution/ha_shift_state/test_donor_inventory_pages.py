"""Synthetic cursor-chain tests; no GitHub calls, donors or binary execution."""
import copy
import unittest

from donor_inventory_pages import InvalidPageSequence, stitch_complete_pages


def fixtures():
    candidate = {"repository": "boykopovar/AnyPS5", "commit_sha": "a" * 40, "root_tree_sha": "b" * 40}
    cursor = {"commit_sha": candidate["commit_sha"], "root_tree_sha": candidate["root_tree_sha"],
              "frames": [{"path": "", "sha": candidate["root_tree_sha"], "index": 1}]}
    def entry(path, sha="d" * 40, kind="blob", mode="100644"):
        return {"path": path, "sha": sha, "kind": kind, "mode": mode,
                "size": 3, "submodule": False, "symlink": False}
    def response(entries, next_cursor):
        return {**candidate, "entries": entries, "complete": next_cursor is None,
                "next_cursor": next_cursor, "requests": 1}
    pages = [{"request_cursor": None, "response": response([entry("LICENSE", "c" * 40)], cursor)},
             {"request_cursor": cursor, "response": response([entry("core/relinker/CMakeLists.txt")], None)}]
    return candidate, pages, entry


class PageChainTests(unittest.TestCase):
    def test_valid_stitch_preserves_source_pins_and_entries(self):
        candidate, pages, _ = fixtures()
        manifest = stitch_complete_pages(candidate, pages)
        self.assertEqual(manifest["requests"], 2)
        self.assertEqual([x["path"] for x in manifest["entries"]],
                         ["LICENSE", "core/relinker/CMakeLists.txt"])
        self.assertTrue(manifest["complete"])
        self.assertIsNone(manifest["next_cursor"])
        self.assertEqual(manifest["root_tree_sha"], candidate["root_tree_sha"])

    def test_missing_or_reordered_cursor_fails_closed(self):
        c, pages, _ = fixtures()
        for variant in ([pages[1]], [pages[1], pages[0]], [pages[0]], [pages[0], pages[0]]):
            with self.subTest(variant=len(variant), first=variant[0]["request_cursor"] is None):
                with self.assertRaises(InvalidPageSequence): stitch_complete_pages(c, variant)

    def test_drift_and_metadata_trickery_fail_closed(self):
        c, pages, _ = fixtures()
        changes = [
            lambda p: p[1]["response"].update(commit_sha="f" * 40),
            lambda p: p[1]["response"].update(repository="unrelated/Donor"),
            lambda p: p[0]["response"].update(complete=True),
            lambda p: p[1]["response"].update(complete=1),
            lambda p: p[1]["response"].update(requests=True),
            lambda p: p[0]["response"]["next_cursor"].update(root_tree_sha="f" * 40),
            lambda p: p[0]["response"]["next_cursor"]["frames"][0].update(index=True),
            lambda p: p[0]["response"]["next_cursor"]["frames"][0].update(path="wrong"),
            lambda p: p[1]["response"].update(next_cursor={"fake": "cursor"}),
            lambda p: p[1]["response"].update(extra="not-signed"),
        ]
        for n, change in enumerate(changes):
            malformed = copy.deepcopy(pages)
            change(malformed)
            with self.subTest(case=n), self.assertRaises(InvalidPageSequence):
                stitch_complete_pages(c, malformed)

    def test_negative_paths_duplicates_and_source_modes(self):
        c, pages, entry = fixtures()
        payloads = [entry("core/relinker/../CMakeLists.txt"), entry("CON\\evil"),
                    entry("/etc/x"), entry("src//x"), entry("LICENSE"),
                    entry("license"), entry("link", kind="blob", mode="120000"),
                    entry("external", kind="commit", mode="160000")]
        for n, bad in enumerate(payloads):
            malformed = copy.deepcopy(pages)
            malformed[1]["response"]["entries"].append(bad)
            with self.subTest(case=n), self.assertRaises(InvalidPageSequence):
                stitch_complete_pages(c, malformed)

    def test_page_bounds_and_trailing_unfinished_sequence(self):
        c, pages, entry = fixtures()
        with self.assertRaises(InvalidPageSequence): stitch_complete_pages(c, [])
        malformed = copy.deepcopy(pages)
        malformed[1]["response"]["entries"] = [entry("src/" + str(i)) for i in range(501)]
        with self.assertRaises(InvalidPageSequence): stitch_complete_pages(c, malformed)
        malformed = copy.deepcopy(pages)
        malformed[1]["response"].update(next_cursor=pages[0]["response"]["next_cursor"], complete=False)
        with self.assertRaises(InvalidPageSequence): stitch_complete_pages(c, malformed)
        malformed = copy.deepcopy(pages)
        malformed[0]["response"]["entries"] = []
        malformed[1]["response"]["entries"] = []
        with self.assertRaises(InvalidPageSequence): stitch_complete_pages(c, malformed)


if __name__ == "__main__":
    unittest.main()
