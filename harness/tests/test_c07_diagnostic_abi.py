"""Independent layout/descriptor/candidate mismatch controls; no producer imports."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from candidate import CandidateError, file_digest, semantic_digest
from c07_abi import abi_document, verify_abi
from c07_diagnostic_abi import C_LAYOUTS, KOTLIN_LAYOUTS, layout_semantics, reconstruct
from test_c07_abi import inputs


def fixture(root, route):
    table = KOTLIN_LAYOUTS if route == "kotlin" else C_LAYOUTS
    protocols, sources, inventory = {}, {}, []
    for key, (path, selectors) in table.items():
        doc = {"0": "Format", "comment": "not ABI"} if not selectors else {}
        for selector in selectors:
            owner = doc
            parts = selector.split(".")
            for part in parts[:-1]:
                owner = owner.setdefault(part, {})
            if parts[-1] in ("fields", "fixed_fields"):
                value = [
                    {"index": 0, "name": "Count", "unit": "events", "notes": "not ABI"}
                ]
            elif selector == "roles":
                value = [
                    {
                        "role": 1,
                        "count": 1,
                        "per_api_fields": [
                            {
                                "index": 0,
                                "name": "napi_call",
                                "return": "napi_status",
                                "arguments": ["napi_env"],
                                "function_type": "napi_status(napi_env)",
                            }
                        ],
                        "notes": "not ABI",
                    }
                ]
            else:
                value = 1
            owner[parts[-1]] = value
        out = root / path
        out.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(doc).encode()
        out.write_bytes(raw)
        pin = {"path": path, "sha256": file_digest(raw), "size": len(raw)}
        inventory.append(pin)
        sources[key] = dict(pin, path="authors/" + key + ".json")
        if key == "runtime":
            sources[key] = {
                "path": "authors/frame_generator.py",
                "sha256": "sha256:" + "a" * 64,
                "size": 91,
            }
        protocols[key] = layout_semantics(doc, selectors)
    (root / "madb.lock").write_text(json.dumps({"inputs": list(sources.values())}))
    return {"root": root, "manifest": {"files": inventory}}, {
        "protocols": protocols,
        "sources": sources,
    }


class DiagnosticAbiTests(unittest.TestCase):
    def test_fields_keep_order_index_unit_domain_and_signature_only(self):
        raw = {
            "fields": [
                {
                    "index": 8,
                    "name": "Count",
                    "unit": "bytes",
                    "domain": "safe_integer",
                    "range": [0, 4096],
                    "notes": "ignored",
                    "source": "ignored",
                },
                {"index": 9, "name": "Other"},
            ]
        }
        expected = {
            "fields": [
                {
                    "index": 8,
                    "name": "Count",
                    "unit": "bytes",
                    "domain": "safe_integer",
                    "range": [0, 4096],
                },
                {"index": 9, "name": "Other"},
            ]
        }
        self.assertEqual(layout_semantics(raw, ("fields",)), expected)
        for key, value in (("index", 7), ("unit", "items"), ("name", "Changed")):
            changed = deepcopy(raw)
            changed["fields"][0][key] = value
            self.assertNotEqual(layout_semantics(changed, ("fields",)), expected)
        raw["fields"].reverse()
        self.assertNotEqual(layout_semantics(raw, ("fields",)), expected)

    def test_roles_keep_real_signature_without_commentary(self):
        value = {
            "roles": [
                {
                    "role": "provider",
                    "count": 1,
                    "notes": "irrelevant",
                    "per_api_fields": [
                        {
                            "name": "napi_x",
                            "index": 4,
                            "category": 0,
                            "return": "status",
                            "arguments": ["env"],
                            "function_type": "status(env)",
                            "notes": "irrelevant",
                        }
                    ],
                }
            ]
        }
        projected = layout_semantics(value, ("roles",))
        self.assertNotIn("notes", projected["roles"][0])
        self.assertNotIn("notes", projected["roles"][0]["per_api_fields"][0])
        self.assertEqual(projected["roles"][0]["per_api_fields"][0]["arguments"], ["env"])
        value["roles"][0]["per_api_fields"][0]["arguments"] = ["value"]
        self.assertNotEqual(layout_semantics(value, ("roles",)), projected)

    def test_all_routes_reconstruct_from_inventory_and_locked_authorities(self):
        for route in ("c", "cpp", "rust", "kotlin"):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as tmp:
                candidate, declared = fixture(Path(tmp), route)
                self.assertEqual(
                    reconstruct(candidate, route, declared), declared["protocols"]
                )

    def test_descriptor_only_forgery_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate, declared = fixture(Path(tmp), "c")
            declared["protocols"]["memory"]["fields"][0]["unit"] = "objects"
            with self.assertRaisesRegex(CandidateError, "actual layout attachments"):
                reconstruct(candidate, "c", declared)

    def test_changed_attachment_cannot_hide_behind_old_file_or_source_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate, declared = fixture(Path(tmp), "c")
            path = C_LAYOUTS["memory"][0]
            out = Path(tmp) / path
            doc = json.loads(out.read_text())
            doc["length"] = 27
            out.write_text(json.dumps(doc))
            raw = out.read_bytes()
            with self.assertRaisesRegex(CandidateError, "attachment bytes"):
                reconstruct(candidate, "c", declared)
            item = next(x for x in candidate["manifest"]["files"] if x["path"] == path)
            item.update(sha256=file_digest(raw), size=len(raw))
            with self.assertRaisesRegex(CandidateError, "differs from its source"):
                reconstruct(candidate, "c", declared)

    def test_source_and_inventory_rehash_cannot_hide_protocol_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate, declared = fixture(Path(tmp), "c")
            path = C_LAYOUTS["memory"][0]
            out = Path(tmp) / path
            doc = json.loads(out.read_text())
            doc["fields"][0]["unit"] = "changed"
            out.write_text(json.dumps(doc))
            raw = out.read_bytes()
            next(x for x in candidate["manifest"]["files"] if x["path"] == path).update(
                sha256=file_digest(raw), size=len(raw)
            )
            declared["sources"]["memory"].update(sha256=file_digest(raw), size=len(raw))
            (Path(tmp) / "madb.lock").write_text(
                json.dumps({"inputs": list(declared["sources"].values())})
            )
            with self.assertRaisesRegex(CandidateError, "actual layout attachments"):
                reconstruct(candidate, "c", declared)

    def test_missing_unlisted_and_unlocked_attachments_are_rejected(self):
        for mutation in (
            "missing",
            "unlisted",
            "unlocked",
            "unknown_protocol",
            "malformed",
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                candidate, declared = fixture(Path(tmp), "c")
                path = C_LAYOUTS["memory"][0]
                if mutation == "missing":
                    (Path(tmp) / path).unlink()
                elif mutation == "unlisted":
                    candidate["manifest"]["files"] = [
                        x for x in candidate["manifest"]["files"] if x["path"] != path
                    ]
                elif mutation == "unlocked":
                    declared["sources"]["memory"]["sha256"] = "sha256:" + "b" * 64
                elif mutation == "unknown_protocol":
                    declared["protocols"]["foreign"] = {}
                else:
                    declared["protocols"] = None
                with self.assertRaises(CandidateError):
                    reconstruct(candidate, "c", declared)

    def test_generated_kotlin_runtime_is_read_from_attachment_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate, declared = fixture(Path(tmp), "kotlin")
            expected = reconstruct(candidate, "kotlin", declared)
            self.assertIn("runtime", expected)
            declared["protocols"]["runtime"]["length"] = 999
            with self.assertRaisesRegex(CandidateError, "actual layout attachments"):
                reconstruct(candidate, "kotlin", declared)

    def test_layout_paths_and_provenance_do_not_enter_abi_but_bounds_do(self):
        c, d, p = inputs()
        p["value_slots"] = {
            "test": {
                "layout": "old/path",
                "length_elements": 27,
                "type_id": "test.array.27",
            }
        }
        d["diagnostics"] = {
            "protocols": {"memory": {"length": 27}},
            "sources": {"path": "old", "sha256": "old"},
        }
        expected = abi_document(c, d, p)
        p["value_slots"]["test"]["layout"] = "new/path"
        d["diagnostics"]["sources"] = {"path": "new", "sha256": "new"}
        self.assertEqual(abi_document(c, d, p), expected)
        p["value_slots"]["test"]["length_elements"] = 28
        self.assertNotEqual(abi_document(c, d, p), expected)

    def test_settlement_tail_is_semantic_and_preserves_existing_prefix(self):
        names = [
            "Arms",
            "Hits",
            "ResolveAccepted",
            "RejectAccepted",
            "Exceptions",
            "CurrentSettling",
            "MaxObservedWaiterMap",
        ]
        old = {
            "length": 7,
            "wire": "number[]",
            "fields": [{"index": i, "name": name} for i, name in enumerate(names)],
        }
        changed = deepcopy(old)
        changed["length"] = 9
        changed["fields"] += [
            {"index": 7, "name": "TimerArmed"},
            {"index": 8, "name": "TickInFlight"},
        ]
        selectors = KOTLIN_LAYOUTS["settlement"][1]
        before = layout_semantics(old, selectors)
        after = layout_semantics(changed, selectors)
        self.assertEqual(after["fields"][:7], before["fields"])
        self.assertNotEqual(after, before)
        self.assertEqual(
            after["fields"][7:],
            [{"index": 7, "name": "TimerArmed"}, {"index": 8, "name": "TickInFlight"}],
        )

    def test_reopen_each_capability_bit_changes_abi(self):
        c, d, p = inputs()
        ordinary = abi_document(c, d, p)
        p["runtime_reopen"] = {
            "same_env": True,
            "requires_physical_ack": True,
            "requires_receipt_consumed": True,
            "epoch_reuse": False,
        }
        expected = abi_document(c, d, p)
        self.assertNotEqual(expected, ordinary)
        for key in p["runtime_reopen"]:
            q = deepcopy(p)
            q["runtime_reopen"][key] = not q["runtime_reopen"][key]
            self.assertNotEqual(abi_document(c, d, q), expected, key)

    def test_test_candidate_requires_diagnostics_and_ordinary_rejects_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, diagnostic = fixture(root, "kotlin")
            c, d, p = inputs()
            d["diagnostics"] = diagnostic
            (root / "declarations.json").write_text(json.dumps(d))
            (root / "generated/contract/runtime-policy.json").write_text(json.dumps(p))
            candidate.update(
                contract=c,
                identity={
                    "abi_digest": semantic_digest("madb.c07-abi/1", abi_document(c, d, p))
                },
            )
            verify_abi(candidate, "kotlin", companion=True)
            with self.assertRaisesRegex(CandidateError, "ordinary candidate"):
                verify_abi(candidate, "kotlin")
            del d["diagnostics"]
            (root / "declarations.json").write_text(json.dumps(d))
            with self.assertRaises(CandidateError):
                verify_abi(candidate, "kotlin", companion=True)


if __name__ == "__main__":
    unittest.main()
