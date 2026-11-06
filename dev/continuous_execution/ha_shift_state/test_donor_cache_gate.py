"""Standard-library-only synthetic checks; never builds or runs donor code."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from donor_cache_gate import InvalidIntake, cache_key, checked_candidate, verify_artifact


def fixture():
    candidate = {
        "schema": "ha-public-donor-cache/v1",
        "repository": "boykopovar/AnyPS5",
        "commit_sha": "a" * 40,
        "root_tree_sha": "b" * 40,
        "license": {"path": "LICENSE", "blob_sha": "c" * 40, "spdx": "GPL-2.0-only", "review": "PENDING"},
        "source_objects": [{"path": "core/relinker/CMakeLists.txt", "blob_sha": "d" * 40}],
        "runtime_seam": "relinker-only native conversion (never executed)",
        "integration_status": "SOURCE_ONLY_NOT_BUILT",
    }
    build = {
        "host": "windows-x86_64", "target": "windows-x86_64", "compiler": "mingw-g++",
        "compiler_version": "synthetic-1.0", "compiler_sha256": "e" * 64,
        "generator": "Ninja", "cmake_version": "synthetic-3.30",
        "options": {"ANYPS5_RELINKER_ONLY": "ON", "BUILD_TESTING": "ON"},
        "dependency_pins": [], "patchset_sha256": "0" * 64,
        "source_tree_complete": True,
    }
    return candidate, build


class CacheGateTests(unittest.TestCase):
    def test_stable_dict_and_collection_order(self):
        c, b = fixture()
        c["source_objects"].append({"path": "core/relinker/main.cpp", "blob_sha": "f" * 40})
        b["dependency_pins"] = [
            {"repository": "z/dep", "commit_sha": "1" * 40, "tree_sha": "2" * 40},
            {"repository": "a/dep", "commit_sha": "3" * 40, "tree_sha": "4" * 40},
        ]
        x = cache_key(c, b)
        c["source_objects"].reverse()
        b["dependency_pins"].reverse()
        c = dict(reversed(list(c.items())))
        self.assertEqual(x, cache_key(c, b))

    def test_each_material_input_changes_key(self):
        c, b = fixture()
        original = cache_key(c, b)
        mutations = [
            ("candidate", "commit_sha", "1" * 40),
            ("candidate", "root_tree_sha", "2" * 40),
            ("candidate", "repository", "other/AnyPS5"),
            ("build", "compiler_sha256", "1" * 64),
            ("build", "compiler_version", "synthetic-2.0"),
            ("build", "host", "linux-x86_64"),
            ("build", "target", "linux-x86_64"),
            ("build", "patchset_sha256", "1" * 64),
            ("build", "generator", "Unix Makefiles"),
        ]
        for side, field, new in mutations:
            cc, bb = copy.deepcopy((c, b))
            (cc if side == "candidate" else bb)[field] = new
            with self.subTest(side=side, field=field):
                self.assertNotEqual(original, cache_key(cc, bb))
        bb = copy.deepcopy(b)
        bb["options"]["BUILD_TESTING"] = "OFF"
        self.assertNotEqual(original, cache_key(c, bb))
        bb = copy.deepcopy(b)
        bb["dependency_pins"] = [{"repository": "z/dep", "commit_sha": "1" * 40, "tree_sha": "2" * 40}]
        self.assertNotEqual(original, cache_key(c, bb))
        cc = copy.deepcopy(c)
        cc["license"]["blob_sha"] = "9" * 40
        self.assertNotEqual(original, cache_key(cc, b))
        cc = copy.deepcopy(c)
        cc["source_objects"][0]["blob_sha"] = "1" * 40
        self.assertNotEqual(original, cache_key(cc, b))

    def test_reject_unsafe_source_path_and_windows_collision(self):
        for bad in ("../secret", "src/../escape", "/etc/keys", "C:/Windows", "src\\a", "src//x", "src/./x", "bad\x00name"):
            c, b = fixture()
            c["source_objects"][0]["path"] = bad
            with self.subTest(bad=bad), self.assertRaises(InvalidIntake):
                cache_key(c, b)
        c, b = fixture()
        c["source_objects"].append({"path": "CORE/RELINKER/cmakelists.txt", "blob_sha": "f" * 40})
        with self.assertRaises(InvalidIntake):
            cache_key(c, b)

    def test_reject_unpinned_and_unsafe_options(self):
        for mutation in ("source_tree_complete", "compiler_sha256", "options", "dependency_pins"):
            c, b = fixture()
            if mutation == "source_tree_complete": b[mutation] = False
            if mutation == "compiler_sha256": b[mutation] = "missing"
            if mutation == "options": b[mutation] = {"-DCMAKE_CXX_FLAGS": "x"}
            if mutation == "dependency_pins": b[mutation] = [{"repository": "z/dep", "commit_sha": "notpinned", "tree_sha": "1" * 40}]
            with self.subTest(mutation=mutation), self.assertRaises(InvalidIntake):
                cache_key(c, b)

    def test_never_treat_metadata_as_review_approval(self):
        c, b = fixture()
        c["license"]["review"] = "APPROVED"
        with self.assertRaises(InvalidIntake):
            checked_candidate(c)
        c, b = fixture()
        c["integration_status"] = "LIVE_RUNTIME_PASSED"
        with self.assertRaises(InvalidIntake):
            cache_key(c, b)

    def test_receipt_exact_bytes_and_identity(self):
        c, b = fixture()
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "synthetic.bin"
            body = b"synthetic-relocation-result\x00no-guest-data"
            file.write_bytes(body)
            receipt = {"cache_key": cache_key(c, b), "artifact_size": len(body),
                       "artifact_sha256": hashlib.sha256(body).hexdigest()}
            self.assertEqual(verify_artifact(c, b, receipt, file), {
                "artifact_identity_verified": True, "runtime_tested": False,
                "license_approved": False, "independently_accepted": False,
            })
            file.write_bytes(body + b"x")
            with self.assertRaises(InvalidIntake):
                verify_artifact(c, b, receipt, file)
            file.write_bytes(body)
            wrong = copy.deepcopy(receipt)
            wrong["cache_key"] = "a" * 64
            with self.assertRaises(InvalidIntake):
                verify_artifact(c, b, wrong, file)
            sym = Path(d) / "sym.bin"
            sym.symlink_to(file)
            with self.assertRaises(InvalidIntake):
                verify_artifact(c, b, receipt, sym)

    def test_strict_types_and_extra_fields(self):
        c, b = fixture()
        b["source_tree_complete"] = 1
        with self.assertRaises(InvalidIntake): cache_key(c, b)
        c, b = fixture()
        b["extra"] = "unreviewed"
        with self.assertRaises(InvalidIntake): cache_key(c, b)
        c, b = fixture()
        c["source_objects"].append({"path": "other", "blob_sha": "G" * 40})
        with self.assertRaises(InvalidIntake): cache_key(c, b)


if __name__ == "__main__":
    unittest.main()
