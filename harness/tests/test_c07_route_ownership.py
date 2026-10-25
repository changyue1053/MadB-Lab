"""Receipt-chain consistency tests over small synthetic admitted-candidate inputs."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from candidate import CandidateError, file_digest
from c07_route_ownership import verify_route_ownership


class RouteOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.refs = {}
        self.identity = "sha256:" + "a" * 64
        self.tool_digest = "sha256:" + "b" * 64
        self.source = {"path": "sdk/c/arkts-provider/src/provider.c", "sha256": "sha256:" + "c" * 64, "size": 10}
        self.put("madb.lock", {"inputs": [self.source]})
        self.put("generated/native/identity.generated.hpp", b"inline constexpr auto GatewayProviderCreate = ::mp_c_create;")
        self.put("native/libmodule.so", b"test-double-native")
        self.compile_rows = [self.command("clang", ["clang", "--target=aarch64-linux-ohos23.0.0", "-std=c17",
            "-c", "/frozen/inputs/" + self.source["path"], "-o", "/isolated/work/objects/provider.o"]),
            {"kind": "actual-compiler-dependencies", "unit": "provider", "dependencies": [dict(self.source, origin="frozen-input")]}]
        self.link_rows = [self.command("clangxx", ["clang++", "-shared", "/frozen/inputs/objects/provider.o", "-Wl,-soname,libmodule.so"])]
        self.put("logs/compile-commands.json", self.compile_rows)
        self.put("logs/link-commands.json", self.link_rows)
        self.compile = self.evidence("compile", [dict(path="objects/provider.o", sha256=self.identity, size=20)])
        self.link = self.evidence("link", [self.refs["native/libmodule.so"]])
        self.put("evidence/compile.json", self.compile)
        self.put("evidence/link.json", self.link)
        self.candidate = {"root": self.root, "route": "c", "module": "module", "identity": {"expected_identity": "same-runtime-identity"},
            "provenance": {"input_digest": self.identity, "producer_revision": "reviewed-revision"},
            "toolchain": {"tools": [{"id": "c07-" + name, "sha256": self.tool_digest} for name in ("clang", "clangxx")]},
            "native_members": {"package/libs/arm64-v8a/libmodule.so": b"test-double-native"},
            "manifest": {"candidate_digest": self.identity, "generation_id": self.identity,
                "selector": {"profile_digest": self.identity}, "files": list(self.refs.values()), "dependencies": [],
                "build_evidence": [self.refs["evidence/compile.json"], self.refs["evidence/link.json"]]}}

    def put(self, name, value):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        reference = {"path": name, "sha256": file_digest(data), "size": len(data)}
        # Preserve object identity so the mocked candidate manifest sees rehashed
        # changes. These tests exercise semantic checks, not just byte hashing.
        self.refs.setdefault(name, {}).update(reference)

    def command(self, tool, arguments):
        return {"arguments": arguments, "tool": tool, "tool_sha256": self.tool_digest, "exit_code": 0}

    def evidence(self, phase, outputs):
        return {"phase": phase, "schema": "madb.build-evidence/1", "status": "passed", "exit_code": 0,
                "generation_id": self.identity, "profile_digest": self.identity, "input_digest": self.identity,
                "logs": [self.refs["logs/" + phase + "-commands.json"]], "outputs": outputs}

    def test_public_receipts_bind_exact_native_and_har_bytes(self):
        result = verify_route_ownership(self.candidate)
        self.assertEqual(result["status"], "bound")
        self.assertEqual(result["provider_source"], self.source)
        self.assertEqual(result["native_artifact"], self.refs["native/libmodule.so"])
        self.assertTrue(result["limits"])

    def test_provider_source_standard_tool_or_failure_cannot_be_relabelled(self):
        for mutation in ("standard", "tool", "exit", "source"):
            with self.subTest(mutation=mutation):
                original = json.loads(json.dumps(self.compile_rows))
                if mutation == "standard": self.compile_rows[0]["arguments"][2] = "-std=c++17"
                elif mutation == "tool": self.compile_rows[0]["tool_sha256"] = "sha256:" + "d" * 64
                elif mutation == "exit": self.compile_rows[0]["exit_code"] = 1
                else: self.compile_rows[1]["dependencies"][0]["sha256"] = "sha256:" + "d" * 64
                self.put("logs/compile-commands.json", self.compile_rows); self.put("evidence/compile.json", self.compile)
                with self.assertRaises(CandidateError): verify_route_ownership(self.candidate)
                self.compile_rows = original
        self.put("logs/compile-commands.json", self.compile_rows)

    def test_link_must_consume_recorded_provider_and_exact_dso(self):
        self.link_rows[0]["arguments"].remove("/frozen/inputs/objects/provider.o")
        self.put("logs/link-commands.json", self.link_rows); self.put("evidence/link.json", self.link)
        with self.assertRaises(CandidateError): verify_route_ownership(self.candidate)

    def test_cpp_source_standard_and_factory_have_their_own_binding(self):
        old_source = self.source["path"]
        self.source["path"] = "sdk/cpp/arkts-provider/src/provider.cpp"
        self.put("madb.lock", {"inputs": [self.source]})
        self.put("generated/native/identity.generated.hpp", b"inline constexpr auto GatewayProviderCreate = ::mp_cpp_create;")
        self.compile_rows[0]["tool"] = "clangxx"
        self.compile_rows[0]["arguments"] = [arg.replace(old_source, self.source["path"]).replace("-std=c17", "-std=c++17")
                                                 for arg in self.compile_rows[0]["arguments"]]
        self.compile_rows[1]["dependencies"][0]["path"] = self.source["path"]
        self.put("logs/compile-commands.json", self.compile_rows); self.put("evidence/compile.json", self.compile)
        self.candidate["route"] = "cpp"
        self.assertEqual(verify_route_ownership(self.candidate)["details"]["language_standard"], "c++17")
        self.put("generated/native/identity.generated.hpp", b"inline constexpr auto GatewayProviderCreate = ::mp_c_create;")
        with self.assertRaises(CandidateError): verify_route_ownership(self.candidate)

    def test_rust_archive_and_frontend_have_explicit_separate_evidence(self):
        self.source["path"] = "sdk/rust/arkts-provider/src/lib.rs"
        self.put("madb.lock", {"inputs": [self.source]})
        self.put("generated/native/identity.generated.hpp", b"inline constexpr auto GatewayProviderCreate = ::mp_rust_create;")
        self.put("logs/compile-commands.json", [self.command("cargo", ["cargo", "check", "--offline", "--locked", "--release", "--target", "aarch64-unknown-linux-ohos"])])
        self.put("logs/link-commands.json", [self.command("ohrs", ["ohrs", "build", "--offline", "--locked", "--release", "libmodule.so"])])
        self.compile["outputs"] = [{"path": "objects/libmadb_arkts_gateway.a", "sha256": self.identity, "size": 20}]
        self.put("evidence/compile.json", self.compile); self.put("evidence/link.json", self.link)
        rust_link = {"source_archive_sha256": self.identity, "elf_soname": "libmodule.so",
                     "actual_macro": {"descriptor": {"exports": [{"name": "runtimeOpen"}]}}}
        self.put("rust-link.json", rust_link)
        self.put("rust-symbols.json", {"dynamic_defined": ["napi_register_module_v1"], "frontend": {"macro": {}}})
        self.candidate["manifest"]["files"] = list(self.refs.values())
        self.candidate["route"] = "rust"
        self.candidate["toolchain"]["tools"].extend({"id": name, "sha256": self.tool_digest} for name in ("c07-cargo", "ohrs"))
        self.assertEqual(verify_route_ownership(self.candidate)["details"]["macro_exports"], 1)
        rust_link["source_archive_sha256"] = "sha256:" + "d" * 64
        self.put("rust-link.json", rust_link)
        with self.assertRaises(CandidateError): verify_route_ownership(self.candidate)

    def test_wrong_route_factory_or_comment_only_factory_is_rejected(self):
        for data in (b"inline constexpr auto GatewayProviderCreate = ::mp_cpp_create;",
                     b"/* inline constexpr auto GatewayProviderCreate = ::mp_c_create; */"):
            self.put("generated/native/identity.generated.hpp", data)
            with self.assertRaises(CandidateError): verify_route_ownership(self.candidate)

    def test_other_generation_receipt_and_changed_har_are_rejected(self):
        self.link["generation_id"] = "sha256:" + "e" * 64; self.put("evidence/link.json", self.link)
        with self.assertRaises(CandidateError): verify_route_ownership(self.candidate)
        self.link["generation_id"] = self.identity; self.put("evidence/link.json", self.link)
        self.candidate["native_members"]["package/libs/arm64-v8a/libmodule.so"] = b"different-native"
        with self.assertRaises(CandidateError): verify_route_ownership(self.candidate)


if __name__ == "__main__":
    unittest.main()
