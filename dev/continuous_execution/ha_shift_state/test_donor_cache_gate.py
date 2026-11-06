"""Standard-library-only synthetic checks; never builds or runs donor code."""
import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from donor_cache_gate import InvalidIntake, cache_key, cache_key_with_inventory, checked_candidate, main, verify_artifact, verify_complete_inventory


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
        for bad in ("../secret", "src/../escape", "/etc/keys", "C:/Windows", "src\\a", "src//x", "src/./x", "bad\x00name",
                    "CON", "aux.txt", "src/NUL.bin", "COM1", "LPT9.dat", "COM¹.cfg", "lpt².txt", "dir/file.", "dir/file "):
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
            try:
                sym.symlink_to(file)
            except (OSError, NotImplementedError):
                pass  # Windows without symlink privilege; checksum negatives still executed.
            else:
                with self.assertRaises(InvalidIntake):
                    verify_artifact(c, b, receipt, sym)


    def test_complete_pinned_inventory_crosscheck(self):
        c, _ = fixture()
        def entry(path, sha, kind="blob", mode="100644", submodule=False, symlink=False):
            return {"path": path, "sha": sha, "kind": kind, "mode": mode,
                    "size": None if kind == "tree" else 3,
                    "submodule": submodule, "symlink": symlink}
        inventory = {"repository": c["repository"], "commit_sha": c["commit_sha"],
                     "root_tree_sha": c["root_tree_sha"], "complete": True,
                     "next_cursor": None, "requests": 1, "entries": [
                         entry("core", "e" * 40, "tree", "040000"),
                         entry("core/relinker", "f" * 40, "tree", "040000"),
                         entry("LICENSE", c["license"]["blob_sha"]),
                         entry(c["source_objects"][0]["path"], c["source_objects"][0]["blob_sha"]),
                     ]}
        self.assertEqual(verify_complete_inventory(c, inventory), {
            "source_paths_verified": 2, "complete_inventory": True,
            "license_approved": False, "runtime_tested": False,
        })
        changes = [
            lambda x: x.update(complete=False),
            lambda x: x.update(next_cursor={"frames": []}),
            lambda x: x.update(commit_sha="f" * 40),
            lambda x: x["entries"][0].update(sha="f" * 40),
            lambda x: x["entries"].pop(0),
            lambda x: x["entries"].pop(1),
            lambda x: x["entries"][0].update(kind="blob", mode="100644"),
            lambda x: x["entries"][0].update(size=3),
            lambda x: x["entries"].append(entry("badflag", "f" * 40, submodule=1)),
            lambda x: x["entries"].append(entry("badflag", "f" * 40, symlink="false")),
            lambda x: x["entries"].append(entry("link", "f" * 40, "blob", "120000", symlink=True)),
            lambda x: x["entries"].append(entry("external", "f" * 40, "commit", "160000", submodule=True)),
            lambda x: x["entries"].append(entry("license", "f" * 40)),
        ]
        for i, mutate in enumerate(changes):
            bad = copy.deepcopy(inventory)
            mutate(bad)
            with self.subTest(case=i), self.assertRaises(InvalidIntake):
                verify_complete_inventory(c, bad)

    def test_paged_inventory_and_cache_gate_interoperate(self):
        # The stitching step proves cursor order, while this gate requires
        # parent trees and pinned source/license blob identities.
        from donor_inventory_pages import stitch_complete_pages
        candidate, _ = fixture()
        def entry(path, sha, kind="blob", mode="100644"):
            return {"path": path, "sha": sha, "kind": kind, "mode": mode,
                    "size": None if kind == "tree" else 3,
                    "submodule": False, "symlink": False}
        cursor = {"commit_sha": candidate["commit_sha"],
                  "root_tree_sha": candidate["root_tree_sha"],
                  "frames": [{"path": "", "sha": candidate["root_tree_sha"], "index": 2}]}
        def response(entries, next_cursor):
            return {"repository": candidate["repository"],
                    "commit_sha": candidate["commit_sha"],
                    "root_tree_sha": candidate["root_tree_sha"],
                    "entries": entries, "complete": next_cursor is None,
                    "next_cursor": next_cursor, "requests": 1}
        first = [
            entry("LICENSE", candidate["license"]["blob_sha"]),
            entry("core", "e" * 40, "tree", "040000"),
        ]
        second = [
            entry("core/relinker", "f" * 40, "tree", "040000"),
            entry(candidate["source_objects"][0]["path"],
                  candidate["source_objects"][0]["blob_sha"]),
        ]
        pages = [{"request_cursor": None, "response": response(first, cursor)},
                 {"request_cursor": cursor, "response": response(second, None)}]
        assembled = stitch_complete_pages(candidate, pages)
        self.assertTrue(verify_complete_inventory(candidate, assembled)["complete_inventory"])
        altered = copy.deepcopy(pages)
        altered[0]["response"]["entries"].pop()  # Remove parent tree.
        # Cursor stitching alone cannot claim the resulting source is usable.
        incomplete_structure = stitch_complete_pages(candidate, altered)
        with self.assertRaises(InvalidIntake):
            verify_complete_inventory(candidate, incomplete_structure)

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


    def test_win32_forbidden_names_characters_and_utf16_units(self):
        # These are valid Git-like strings but unsafe as Windows output paths.
        bad = ('CONIN$', 'conout$.txt', '.git/config', 'src/.GIT/index',
               'obj/loader?variant.c', 'obj/a*b', 'obj/a|b', 'obj/a"b',
               'obj/a<b', 'obj/a>b', 'obj/' + 'x' * 256,
               'obj/' + '\U0001f600' * 128)
        for name in bad:
            candidate, build = fixture()
            candidate["source_objects"][0]["path"] = name
            with self.subTest(path=name[:40]), self.assertRaises(InvalidIntake):
                cache_key(candidate, build)
        allowed = ('core/console.cpp', 'inc/interface+v2.hpp',
                   'obj/' + '\U0001f600' * 127, 'src/conin_value.h')
        for name in allowed:
            candidate, build = fixture()
            candidate["source_objects"][0]["path"] = name
            with self.subTest(path=name[:40]):
                self.assertEqual(len(cache_key(candidate, build)), 64)

    def test_verified_cache_key_requires_structurally_complete_source(self):
        c, b = fixture()
        def entry(name, sha, kind='blob', mode='100644'):
            return {'path': name, 'sha': sha, 'kind': kind, 'mode': mode,
                    'size': None if kind == 'tree' else 3,
                    'submodule': False, 'symlink': False}
        inventory = {'repository': c['repository'], 'commit_sha': c['commit_sha'],
                     'root_tree_sha': c['root_tree_sha'], 'complete': True,
                     'next_cursor': None, 'requests': 1, 'entries': [
                         entry('LICENSE', c['license']['blob_sha']),
                         entry('core', 'e' * 40, 'tree', '040000'),
                         entry('core/relinker', 'f' * 40, 'tree', '040000'),
                         entry(c['source_objects'][0]['path'],
                               c['source_objects'][0]['blob_sha'])]}
        self.assertEqual(cache_key_with_inventory(c, b, inventory), cache_key(c, b))
        for mutation in (
                lambda x: x.update(complete=False),
                lambda x: x.update(root_tree_sha='1' * 40),
                lambda x: x['entries'].pop(1),
                lambda x: x['entries'][-1].update(sha='1' * 40),
                lambda x: x['entries'][1].update(mode='100644', kind='blob', size=3)):
            broken = copy.deepcopy(inventory)
            mutation(broken)
            with self.subTest(entries=len(broken['entries'])), self.assertRaises(InvalidIntake):
                cache_key_with_inventory(c, b, broken)
        # The old key remains metadata-only; never confuse it with this gate.
        self.assertEqual(cache_key(c, b), cache_key(c, b))
        with tempfile.TemporaryDirectory() as tmp:
            candidate_file = Path(tmp) / 'candidate.json'
            build_file = Path(tmp) / 'build.json'
            inventory_file = Path(tmp) / 'inventory.json'
            for p, obj in ((candidate_file, c), (build_file, b), (inventory_file, inventory)):
                p.write_text(json.dumps(obj), encoding='utf-8')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(['verified-key', str(candidate_file), str(build_file), str(inventory_file)])
            self.assertEqual(output.getvalue().strip(), cache_key(c, b))
            inventory['complete'] = False
            inventory_file.write_text(json.dumps(inventory), encoding='utf-8')
            with self.assertRaises(InvalidIntake):
                main(['verified-key', str(candidate_file), str(build_file), str(inventory_file)])



if __name__ == "__main__":
    unittest.main()
