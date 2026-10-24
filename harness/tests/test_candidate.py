from pathlib import Path
import importlib.util
import json
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("candidate", ROOT / "harness/candidate.py")
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class PublicCandidateChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="madb-lab-manifest-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        digest = "sha256:" + "1" * 64
        files = []
        def write(name, value):
            data = json.dumps(value).encode(); (self.root / name).write_bytes(data)
            reference = {"path": name, "size": len(data), "sha256": candidate.file_digest(data)}
            files.append(reference); return reference
        toolchain = write("toolchain.json", {"schema": "madb.native-toolchain/1", "test_only": "independent format fixture"})
        public_schema = write("public.schema.json", {"$schema": "https://json-schema.org/draft/2020-12/schema",
                                                     "$id": "urn:lab:format-fixture:1", "type": "object"})
        profile = {"schema": "madb.profile/1", "id": "test", "route": "RUST-C-ABI",
                   "provider": {"language": "rust", "runtime": "native"},
                   "consumer": {"language": "c", "runtime": "native"},
                   "target": "aarch64-apple-darwin", "direction": "consumer-to-provider",
                   "abi": "c11", "artifact_kind": "dynamic-library", "build_system": "rustc-clang",
                   "deployment_target": "14.0", "sdk": dict(toolchain, schema="madb.native-toolchain/1"),
                   "tools": [{"id": "test-tool", "version": "1", "sha256": digest, "host": "aarch64-apple-darwin",
                              "target": "aarch64-apple-darwin", "source": "fixture://independent-tool", "arguments": []}],
                   "macros": [], "restrictions": [], "required_features": [], "supported_features": [],
                   "defaults": {"values": {"ownership": "copy"}, "origin": {"authority": "profile-default",
                                "id": "test-default", "location": {"path": "profile.json", "line": 1, "column": 1}}},
                   "backend_config": None}
        profile_ref = dict(write("profile.json", profile), schema="madb.profile/1")
        profile_digest = candidate.profile_digest(profile)
        selector = {"route": "RUST-C-ABI", "profile_id": "test", "profile_digest": profile_digest,
                    "target": "aarch64-apple-darwin", "direction": "consumer-to-provider"}
        project = {"schema": "madb.project/1", "project": "independent-test", "sdk_namespace": "test",
                   "boundaries": [{"id": "test-boundary", "route": "RUST-C-ABI", "target": selector["target"],
                                   "direction": selector["direction"], "profile": profile_ref,
                                   "source": {"kind": "rust-c-declaration", "path": "fixture.rs"}, "output": "generated"}],
                   "policies": [], "policy_families": [], "artifacts": {"package": "test", "manifest": "candidate.json"}}
        write("project.json", project)
        lock = {"schema": "madb.lock/1", "project_digest": candidate.project_digest(project),
                "profiles": [{"id": "test", "semantic_digest": profile_digest, "file": profile_ref}],
                "tools": profile["tools"], "inputs": [toolchain], "schemas": [public_schema],
                "components": [{"id": "test-component", "version": "1", "sha256": digest}]}
        lock_digest = write("madb.lock", lock)["sha256"]
        source_digest = candidate.semantic_digest("madb.source/1", sorted(lock["inputs"], key=lambda item: item["path"]))
        documents = {
            "identity.json": {"schema": "madb.native-identity/1", "bootstrap_version": 1,
                              "interface_digest": digest, "profile_digest": profile_digest},
            "provenance.json": {"schema": "madb.native-provenance/1", "producer_revision": "2" * 40,
                                "input_digest": source_digest, "tool_digest": digest},
            "evidence.json": {"test": "fixture, not a claimed native result"},
            "contract.json": {"schema": "madb.contract-ir/1", "structure_digest": digest,
                              "boundary_id": "test-boundary", "sdk_namespace": "test",
                              "policy_digest": digest, "source_digest": source_digest,
                              "selector": selector,
                              "types": [{"id": "unit", "definition": {"kind": "unit"}},
                                        {"id": "u32", "definition": {"kind": "integer", "signed": False, "width": 32}},
                                        {"id": "record", "definition": {"kind": "record", "layout": "c",
                                          "fields": [{"name": "value", "type_id": "u32"}]}}],
                              "observations": [{"kind": "layout", "subject": "record", "precision": "compiler-derived",
                                                "selector": selector, "input_digest": source_digest,
                                                "producer": {"id": "test-tool", "version": "1", "sha256": digest},
                                                "result": {"size": 4, "alignment": 4, "fields": [{"name": "value", "offset": 0, "size": 4}]}}],
                              "required_features": [],
                              "symbols": [{"public_id": "test.call", "public_id_origin": "explicit", "precision": "artifact-derived",
                                           "source_key": {"reader": "org.madb.rust-c-abi@1", "package": "test",
                                                          "module": "fixture.rs", "kind": "function",
                                                          "qualified_name": "test_call", "overload": "none"},
                                           "shape": {"link_name": "test_call", "kind": "sync", "calling_convention": "c",
                                                     "parameters": [{"name": "argument", "type_id": "u32"}],
                                                     "result": "unit", "constants": []}}],
                              "policies": [{"symbol_id": "test.call", "slot": {"kind": "call"},
                                            "values": {"threading": "caller"}, "provenance": []}]},
        }
        contract = documents["contract.json"]
        for symbol in contract["symbols"]:
            symbol["source_id"] = candidate.source_id(symbol["source_key"])
            symbol["shape_digest"] = candidate.shape_digest(contract, symbol)
        contract["structure_digest"] = candidate.structure_digest(contract)
        contract["policy_digest"] = candidate.policy_digest(contract)
        for name, value in documents.items():
            write(name, value)
        self.manifest = {"schema": "madb.candidate/1", "candidate_digest": digest,
                         "selector": selector,
                         "generation_id": digest, "contract_digest": contract["structure_digest"], "policy_digest": contract["policy_digest"],
                         "lock_digest": lock_digest, "manifest_path": "candidate.json", "files": files,
                         "dependencies": [], "public_symbols": ["test.call"], "required_cases": ["test.case"],
                         "build_evidence": [dict(next(item for item in files if item["path"] == "evidence.json"), schema="madb.build-evidence/1")]}
        self.save()

    def save(self):
        self.manifest["candidate_digest"] = candidate.candidate_digest(self.manifest)
        (self.root / "candidate.json").write_text(json.dumps(self.manifest))

    def rewrite_outer_file(self, name, value, reanchor_lock=False):
        data = json.dumps(value).encode(); (self.root / name).write_bytes(data)
        reference = next(item for item in self.manifest["files"] if item["path"] == name)
        reference.update(size=len(data), sha256=candidate.file_digest(data))
        if reanchor_lock:
            self.manifest["lock_digest"] = reference["sha256"]
        self.save()

    def assert_rejected(self, code):
        with self.assertRaises(candidate.CandidateError) as caught:
            candidate.verify_candidate(self.root)
        self.assertEqual(caught.exception.code, code)

    def test_complete_candidate_is_accepted(self):
        self.assertEqual(candidate.verify_candidate(self.root)["manifest"], self.manifest)

    def test_corrupt_file_is_rejected(self):
        (self.root / "evidence.json").write_bytes(b"corrupt")
        self.assert_rejected("ArtifactMismatch")

    def test_missing_file_is_rejected(self):
        (self.root / "evidence.json").unlink()
        self.assert_rejected("ArtifactMismatch")

    def test_extra_file_is_rejected(self):
        (self.root / "unlisted").write_text("unlisted")
        self.assert_rejected("ArtifactMismatch")

    def test_symlink_is_rejected(self):
        (self.root / "linked").symlink_to(self.root / "evidence.json")
        self.assert_rejected("ArtifactMismatch")

    def test_parent_traversal_is_rejected(self):
        self.manifest["files"][0]["path"] = "../outside"
        self.save(); self.assert_rejected("ArtifactMismatch")

    def test_self_reference_is_rejected(self):
        self.manifest["files"][0]["path"] = "candidate.json"
        self.save(); self.assert_rejected("ArtifactMismatch")

    def test_digest_mismatch_is_rejected(self):
        self.manifest["candidate_digest"] = "sha256:" + "f" * 64
        (self.root / "candidate.json").write_text(json.dumps(self.manifest))
        self.assert_rejected("ArtifactMismatch")

    def test_missing_cases_is_rejected(self):
        self.manifest["required_cases"] = []
        self.save(); self.assert_rejected("FormatInvalid")

    def test_unknown_field_is_rejected(self):
        self.manifest["future_required_semantic"] = "unknown"
        self.save(); self.assert_rejected("FormatInvalid")

    def test_duplicate_json_key_is_rejected(self):
        (self.root / "candidate.json").write_text('{"schema":1,"schema":2}')
        self.assert_rejected("FormatInvalid")

    def test_noncanonical_numbers_are_rejected(self):
        for number in ("1.0", "1e0", "-0", "NaN", "9007199254740992"):
            with self.subTest(number=number):
                path = self.root / "number.json"; path.write_text('{"number":' + number + '}')
                with self.assertRaises(candidate.CandidateError): candidate.read_json(path)

    def test_candidate_sets_are_order_independent(self):
        digest = candidate.candidate_digest(self.manifest)
        self.manifest["files"].reverse()
        self.assertEqual(candidate.candidate_digest(self.manifest), digest)

    def test_file_cannot_add_file_reference_schema(self):
        self.manifest["files"][0]["schema"] = "madb.identity/1"
        self.save(); self.assert_rejected("FormatInvalid")

    def test_file_reference_requires_schema(self):
        del self.manifest["build_evidence"][0]["schema"]
        self.save(); self.assert_rejected("FormatInvalid")

    def test_boolean_bootstrap_version_is_not_integer_one(self):
        path = self.root / "identity.json"
        identity = json.loads(path.read_text()); identity["bootstrap_version"] = True
        data = json.dumps(identity).encode(); path.write_bytes(data)
        reference = next(item for item in self.manifest["files"] if item["path"] == "identity.json")
        reference.update(size=len(data), sha256=candidate.file_digest(data))
        self.save(); self.assert_rejected("AbiMismatch")

    def test_rehashed_outer_candidate_cannot_hide_changed_lock(self):
        lock = candidate.read_json(self.root / "madb.lock"); lock["tools"][0]["version"] = "different"
        self.rewrite_outer_file("madb.lock", lock)
        self.assert_rejected("ArtifactMismatch")

    def test_rehashed_toolchain_cannot_keep_old_profile_identity(self):
        self.rewrite_outer_file("toolchain.json", {"schema": "madb.native-toolchain/1", "runtime_protocol": "wrong"})
        self.assert_rejected("ArtifactMismatch")

    def test_profile_semantic_change_cannot_reuse_bootstrap_identity(self):
        profile = candidate.read_json(self.root / "profile.json"); profile["deployment_target"] = "15.0"
        self.rewrite_outer_file("profile.json", profile)
        self.assert_rejected("ProfileMismatch")

    def test_lock_profile_reference_is_checked_after_reanchoring_lock(self):
        lock = candidate.read_json(self.root / "madb.lock"); lock["profiles"][0]["file"]["sha256"] = "sha256:" + "f" * 64
        self.rewrite_outer_file("madb.lock", lock, reanchor_lock=True)
        self.assert_rejected("ArtifactMismatch")

    def test_project_semantic_change_is_checked(self):
        project = candidate.read_json(self.root / "project.json"); project["project"] = "different"
        self.rewrite_outer_file("project.json", project)
        self.assert_rejected("ArtifactMismatch")

    def test_project_profile_reference_is_checked_after_semantic_rehash(self):
        project = candidate.read_json(self.root / "project.json")
        project["boundaries"][0]["profile"]["sha256"] = "sha256:" + "f" * 64
        self.rewrite_outer_file("project.json", project)
        lock = candidate.read_json(self.root / "madb.lock"); lock["project_digest"] = candidate.project_digest(project)
        self.rewrite_outer_file("madb.lock", lock, reanchor_lock=True)
        self.assert_rejected("ArtifactMismatch")

    def test_locked_tool_must_match_profile_after_lock_rehash(self):
        lock = candidate.read_json(self.root / "madb.lock"); lock["tools"][0]["version"] = "different"
        self.rewrite_outer_file("madb.lock", lock, reanchor_lock=True)
        self.assert_rejected("ProfileMismatch")

    def test_available_lock_input_cannot_disagree_after_outer_rehash(self):
        lock = candidate.read_json(self.root / "madb.lock")
        lock["inputs"][0]["sha256"] = "sha256:" + "f" * 64
        self.rewrite_outer_file("madb.lock", lock, reanchor_lock=True)
        self.assert_rejected("ArtifactMismatch")

    def test_changed_signature_cannot_keep_old_shape_and_bootstrap_identity(self):
        contract = candidate.read_json(self.root / "contract.json")
        contract["symbols"][0]["shape"]["parameters"][0]["type_id"] = "unit"
        self.rewrite_outer_file("contract.json", contract)
        self.assert_rejected("AbiMismatch")

    def test_changed_effective_policy_cannot_keep_old_policy_digest(self):
        contract = candidate.read_json(self.root / "contract.json")
        contract["policies"][0]["values"]["threading"] = "any"
        self.rewrite_outer_file("contract.json", contract)
        self.assert_rejected("ArtifactMismatch")

    def test_changed_source_key_cannot_keep_old_source_identity(self):
        contract = candidate.read_json(self.root / "contract.json")
        contract["symbols"][0]["source_key"]["qualified_name"] = "other_call"
        self.rewrite_outer_file("contract.json", contract)
        self.assert_rejected("ArtifactMismatch")

    def test_recomputed_shape_cannot_keep_old_structure_digest(self):
        contract = candidate.read_json(self.root / "contract.json")
        symbol = contract["symbols"][0]
        symbol["shape"]["parameters"][0]["type_id"] = "unit"
        symbol["shape_digest"] = candidate.shape_digest(contract, symbol)
        self.rewrite_outer_file("contract.json", contract)
        self.assert_rejected("AbiMismatch")

    def test_reachable_type_change_cannot_keep_old_shape_digest(self):
        contract = candidate.read_json(self.root / "contract.json")
        contract["types"][1]["definition"]["width"] = 64
        self.rewrite_outer_file("contract.json", contract)
        self.assert_rejected("AbiMismatch")

    def test_duplicate_source_identity_is_rejected(self):
        contract = candidate.read_json(self.root / "contract.json")
        duplicate = dict(contract["symbols"][0], public_id="test.duplicate")
        contract["symbols"].append(duplicate)
        self.manifest["public_symbols"].append("test.duplicate")
        self.rewrite_outer_file("contract.json", contract)
        self.assert_rejected("ArtifactMismatch")

    def test_unavailable_author_input_change_cannot_keep_old_source_digest(self):
        lock = candidate.read_json(self.root / "madb.lock")
        lock["inputs"].append({"path": "author/fixture.rs", "sha256": "sha256:" + "1" * 64, "size": 100})
        self.rewrite_outer_file("madb.lock", lock, reanchor_lock=True)
        self.assert_rejected("ArtifactMismatch")

    def test_layout_metadata_must_match_compiler_inputs_and_target(self):
        for name, mutate in (
            ("target", lambda value: value["selector"].update(target="wrong-target")),
            ("compiler", lambda value: value["producer"].update(sha256="sha256:" + "f" * 64)),
            ("input", lambda value: value.update(input_digest="sha256:" + "f" * 64)),
            ("precision", lambda value: value.update(precision="heuristic")),
        ):
            with self.subTest(name=name):
                original = candidate.read_json(self.root / "contract.json")
                contract = json.loads(json.dumps(original))
                mutate(contract["observations"][0])
                self.rewrite_outer_file("contract.json", contract)
                self.assert_rejected("AbiMismatch")
                self.rewrite_outer_file("contract.json", original)

    def test_heuristic_symbol_cannot_claim_authoritative_first_route_identity(self):
        contract = candidate.read_json(self.root / "contract.json")
        contract["symbols"][0]["precision"] = "heuristic"
        self.rewrite_outer_file("contract.json", contract)
        self.assert_rejected("ArtifactMismatch")


if __name__ == "__main__":
    unittest.main()
