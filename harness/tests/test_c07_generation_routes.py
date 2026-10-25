"""Independent route/config and raw authority regressions; no target simulation."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from candidate import file_digest
from c07_execution import ExecutionError
from c07_generation import generation_configuration, validate_native_declarations


class GenerationRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_native_routes_need_no_rust_configuration(self):
        for route in ("c", "cpp"):
            args = SimpleNamespace(route=route)
            self.assertEqual(generation_configuration(args), ([], []))
            args.rust_configuration = self.root / "foreign-config"
            with self.assertRaisesRegex(ExecutionError, "only valid"):
                generation_configuration(args)

    def test_rust_configuration_requires_both_fields_and_exact_bytes(self):
        path = self.root / "rust.json"
        path.write_text('{"declared":"test-only"}')
        args = SimpleNamespace(route="rust", rust_configuration=path)
        with self.assertRaisesRegex(ExecutionError, "requires"):
            generation_configuration(args)
        args.rust_configuration_sha256 = file_digest(path.read_bytes())
        arguments, inputs = generation_configuration(args)
        self.assertEqual(arguments, ["--rust-configuration", str(path), "--rust-configuration-sha256", args.rust_configuration_sha256])
        self.assertEqual(inputs, [path])
        path.write_text('{"declared":"changed"}')
        with self.assertRaisesRegex(ExecutionError, "explicit pin"):
            generation_configuration(args)

    def declaration(self):
        # Synthetic protocol fixture. Actual proc macros are separate public CLI evidence.
        methods = [{"name": "method" + str(i), "params": [{"name": "value"}]} for i in range(16)]
        return {"c_seam": {"authority": "clang-c-declarations", "target": "aarch64-linux-ohos"},
                "gateway": {"authority": "declared-arkts-syntax", "methods": methods}}

    def rust_declaration(self):
        value = self.declaration()
        value["rust"] = {"authority": "actual napi-ohos proc macros; raw surface only",
            "test_support": False, "typed_api_inferred": False, "native_target_artifacts": [],
            "macro": {"descriptor": {"exports": [{"name": m["name"], "arity": 1,
                "parameters": [{"name": "value", "rawType": "unknown"}], "rawReturn": "unknown"}
                for m in value["gateway"]["methods"]]}},
            "resolved_packages": [{"name": name, "version": "1.2.0",
                "features": ["napi1", "napi2", "napi3"] if name == "napi-ohos" else []}
                for name in ("napi-ohos", "napi-derive-ohos", "napi-build-ohos", "napi-sys-ohos")]}
        return value

    def test_c_cpp_accept_real_authority_labels_but_reject_foreign_frontend(self):
        for route in ("c", "cpp"):
            self.assertEqual(validate_native_declarations(self.declaration(), route)["gateway_methods"], 16)
            with self.assertRaisesRegex(ExecutionError, "unexpected provider"):
                validate_native_declarations(self.rust_declaration(), route)

    def test_rust_raw_arity_and_order_match_gateway(self):
        value = self.rust_declaration()
        self.assertEqual(validate_native_declarations(value, "rust")["rust_macro_exports"], 16)
        for mode in ("arity", "order", "typed"):
            bad = deepcopy(value)
            exports = bad["rust"]["macro"]["descriptor"]["exports"]
            if mode == "arity": exports[0]["arity"] = 0
            if mode == "order": exports.reverse()
            if mode == "typed": exports[0]["rawReturn"] = "Snapshot"
            with self.subTest(mode=mode), self.assertRaises(ExecutionError):
                validate_native_declarations(bad, "rust")

    def test_metadata_cannot_hide_native_link_or_custom_gc(self):
        for mode in ("artifact", "napi4", "duplicate", "companion"):
            value = self.rust_declaration()
            if mode == "artifact": value["rust"]["native_target_artifacts"] = ["native.so"]
            if mode == "napi4": value["rust"]["resolved_packages"][0]["features"].append("napi4")
            if mode == "duplicate": value["rust"]["resolved_packages"].append(value["rust"]["resolved_packages"][0])
            if mode == "companion": value["rust"]["test_support"] = True
            with self.subTest(mode=mode), self.assertRaises(ExecutionError):
                validate_native_declarations(value, "rust")


if __name__ == "__main__":
    unittest.main()
