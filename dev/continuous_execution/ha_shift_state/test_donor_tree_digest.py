"""Source-only synthetic Git tree-object hashing tests; no donor binaries."""
import copy
import hashlib
import unittest
import sys
import types
from unittest.mock import patch

from donor_tree_digest import InvalidTreeDigest, reconstruct_tree_digest, verified_tree_cache_key


def _object(kind, content):
    return hashlib.sha1(kind.encode() + b" " + str(len(content)).encode() + b"\0" + content).hexdigest()


def _entry(path, sha, kind="blob", mode="100644"):
    return dict(path=path, sha=sha, kind=kind, mode=mode,
                size=None if kind == "tree" else 3, submodule=False, symlink=False)


def fixture():
    lic = _object("blob", b"synthetic license")
    a = _object("blob", b"hello")
    z = _object("blob", b"world")
    # Independently construct the Git wire representation of the child tree.
    inner = b"100644 a.c\0" + bytes.fromhex(a) + b"100755 z.c\0" + bytes.fromhex(z)
    subtree = _object("tree", inner)
    # Ordering: LICENSE comes before src/; tree payload includes canonical 40000.
    root = _object("tree", b"100644 LICENSE\0" + bytes.fromhex(lic) +
                   b"40000 src\0" + bytes.fromhex(subtree))
    entries = [_entry("src/z.c", z, mode="100755"),
               _entry("LICENSE", lic),
               _entry("src", subtree, "tree", "040000"),
               _entry("src/a.c", a)]
    return root, entries


class GitTreeDigestTests(unittest.TestCase):
    def test_matches_independent_git_wire_fixture_and_ignores_entry_order(self):
        expected, entries = fixture()
        self.assertEqual(reconstruct_tree_digest(entries), {
            "root_tree_sha": expected, "tree_objects_checked": 2})
        self.assertEqual(reconstruct_tree_digest(list(reversed(entries)))["root_tree_sha"], expected)

    def test_forged_nested_digest_fails(self):
        _, entries = fixture()
        altered = copy.deepcopy(entries)
        altered[0]["sha"] = "a" * 40
        with self.assertRaisesRegex(InvalidTreeDigest, "subtree SHA"):
            reconstruct_tree_digest(altered)

    def test_missing_parent_or_children_fails(self):
        _, entries = fixture()
        for omit in (2, 3):
            malformed = copy.deepcopy(entries)
            malformed.pop(omit)
            with self.subTest(omit=omit), self.assertRaises(InvalidTreeDigest):
                reconstruct_tree_digest(malformed)

    def test_bad_mode_duplicate_and_git_path_rejected(self):
        _, entries = fixture()
        for mutate in (
            lambda e: e[0].update(mode="160000"),
            lambda e: e.append(copy.deepcopy(e[0])),
            lambda e: e[0].update(path="src/../bad"),
            lambda e: e[0].update(path="src\\bad"),
            lambda e: e[0].update(sha="f" * 39),
            lambda e: e[0].update(kind="tree"),
        ):
            malformed = copy.deepcopy(entries)
            mutate(malformed)
            with self.subTest(change=mutate.__code__.co_firstlineno), self.assertRaises(InvalidTreeDigest):
                reconstruct_tree_digest(malformed)


    def test_opt_in_wrapper_binds_root_to_candidate_and_gate(self):
        root, entries = fixture()
        calls = []
        class StubInvalidIntake(ValueError):
            pass
        def gate(candidate, build, inventory):
            calls.append((candidate, build, inventory))
            return "synthetic-cache-key"
        stub = types.SimpleNamespace(cache_key_with_inventory=gate,
                                     InvalidIntake=StubInvalidIntake)
        with patch.dict(sys.modules, {"donor_cache_gate": stub}):
            candidate = {"root_tree_sha": root}
            inventory = {"entries": entries}
            key, digest = verified_tree_cache_key(candidate, {}, inventory)
            self.assertEqual(key, "synthetic-cache-key")
            self.assertEqual(digest["root_tree_sha"], root)
            self.assertEqual(len(calls), 1)
            with self.assertRaisesRegex(StubInvalidIntake, "root SHA mismatch"):
                verified_tree_cache_key({"root_tree_sha": "0" * 40}, {}, inventory)

    def test_reject_root_only_forgery_and_invalid_top_level_mode(self):
        _, entries = fixture()
        changed = copy.deepcopy(entries)
        changed[1]["sha"] = "a" * 40  # Top-level blob changes root digest.
        self.assertNotEqual(reconstruct_tree_digest(changed)["root_tree_sha"],
                            reconstruct_tree_digest(entries)["root_tree_sha"])
        changed = copy.deepcopy(entries)
        changed[1]["mode"] = "040000"
        with self.assertRaises(InvalidTreeDigest):
            reconstruct_tree_digest(changed)

if __name__ == "__main__":
    unittest.main()
