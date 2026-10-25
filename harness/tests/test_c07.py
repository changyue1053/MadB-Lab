from pathlib import Path
import io
import json
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))
from candidate import CandidateError, file_digest, read_json, verify_public_candidate
from c07_candidate import har_members, native_inventory, ordinary_public_entry, verify_candidate
from c07_contract import requirement, case_requirements
from c07_observations import EXPECTED, parse_ordinary
import test_candidate as format_fixture


class C07AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = format_fixture.PublicCandidateChecks()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def identity(self, schema):
        fixture = self.fixture
        value = {"schema": schema, "bootstrap_version": 1,
            "abi_digest": "sha256:" + "a" * 64,
            "profile_digest": fixture.manifest["selector"]["profile_digest"],
            "build_id": "sha256:" + "b" * 64}
        value["expected_identity"] = "madb-arkts/1:" + ":".join(value[key][7:] for key in ("abi_digest", "profile_digest", "build_id"))
        self.replace_identity(value)
        return value

    def replace_identity(self, value):
        fixture = self.fixture
        data = json.dumps(value).encode()
        (fixture.root / "identity.json").write_bytes(data)
        item = next(item for item in fixture.manifest["files"] if item["path"] == "identity.json")
        item.update(sha256=file_digest(data), size=len(data))
        fixture.save()

    def test_old_identity_default_still_passes(self):
        verify_public_candidate(self.fixture.root, allowed_routes={"RUST-C-ABI"})

    def test_explicit_distinct_arkts_identity(self):
        self.identity("madb.arkts-runtime-identity/1")
        verify_public_candidate(self.fixture.root, allowed_routes={"RUST-C-ABI"}, identity_format="arkts")
        with self.assertRaises(CandidateError):
            verify_public_candidate(self.fixture.root, allowed_routes={"RUST-C-ABI"})

    def test_incompatible_six_field_old_tag_rejected(self):
        self.identity("madb.native-identity/1")
        with self.assertRaisesRegex(CandidateError, "unsupported bootstrap identity schema"):
            verify_public_candidate(self.fixture.root, allowed_routes={"RUST-C-ABI"}, identity_format="arkts")

    def test_string_and_digest_disagreement_rejected(self):
        value = self.identity("madb.arkts-runtime-identity/1")
        value["expected_identity"] += "0"
        self.replace_identity(value)
        with self.assertRaisesRegex(CandidateError, "bootstrap string differs"):
            verify_public_candidate(self.fixture.root, allowed_routes={"RUST-C-ABI"}, identity_format="arkts")

    def test_route_mismatch_before_consumption(self):
        with self.assertRaisesRegex(CandidateError, "allowed direct consumer route"):
            verify_candidate(self.fixture.root, "c")

    def test_allocation_keeps_all_required_groups(self):
        for route in ("c", "cpp", "rust", "kotlin"):
            name = "c07-" + route + "-arkts-aarch64-ohos23"
            ordinary = set(requirement(name)["required_cases"])
            companion = set(requirement(name + "-test")["required_cases"])
            self.assertEqual((len(ordinary), len(companion)), (5, 25))
            self.assertFalse(ordinary & companion)
            self.assertEqual(len(case_requirements(name)) + len(case_requirements(name + "-test")), 30)


class C07ArchiveTests(unittest.TestCase):
    def archive(self, entries):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "fixture.har"
        with tarfile.open(path, "w:gz") as archive:
            for name, data, kind in entries:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def test_inspect_without_extracting(self):
        path = self.archive([("package/Index.d.ets", b"declaration", tarfile.REGTYPE)])
        self.assertEqual(har_members(path), {"package/Index.d.ets": b"declaration"})

    def test_traversal_and_links_and_duplicates_rejected(self):
        for entries in [ [("../outside", b"x", tarfile.REGTYPE)], [("package/link", b"", tarfile.SYMTYPE)],
                         [("package/a", b"x", tarfile.REGTYPE), ("package/a", b"y", tarfile.REGTYPE)]]:
            with self.subTest(entries=entries), self.assertRaises(CandidateError):
                har_members(self.archive(entries))


class C07ObservationTests(unittest.TestCase):
    def raw(self):
        nonce, pid = "fixed-independent-nonce", "123"
        lines = [f"date time {pid} tag {name} {nonce}" for name in ("PROBE_STARTED", "PROBE_PAGE_READY", "PROBE_FINISHED")]
        lines += [f"date time {pid} tag ORDINARY_CASE {nonce} {name} {json.dumps(values)}" for name, values in EXPECTED.items()]
        lines.append(f"date time {pid} tag ORDINARY_COMPLETE {nonce}")
        return "\n".join(lines), nonce, pid

    def test_actual_complete_transport(self):
        raw, nonce, pid = self.raw()
        self.assertEqual(parse_ordinary(raw, nonce=nonce, pid=pid)["status"], "passed")

    def test_no_completion_is_not_pass(self):
        raw, nonce, pid = self.raw()
        self.assertEqual(parse_ordinary(raw.rsplit("\n", 1)[0], nonce=nonce, pid=pid)["status"], "incomplete")

    def test_duplicate_pid_and_changed_values_fail(self):
        raw, nonce, pid = self.raw()
        for changed, selected_pid in [(raw + "\n" + raw.splitlines()[-1], pid), (raw, "124"), (raw.replace("[16,", "[15,"), pid)]:
            with self.subTest(raw=changed, pid=selected_pid):
                self.assertEqual(parse_ordinary(changed, nonce=nonce, pid=selected_pid)["status"], "failed")


class C07ClosedInventoryTests(unittest.TestCase):
    def test_renamed_and_versioned_elf_are_never_ignored(self):
        entries = {"docs/renamed": b"\x7fELFpayload", "native/libx.so.1": b"\x7fELFother", "notes.txt": b"ordinary text"}
        self.assertEqual(set(native_inventory(entries)), {"docs/renamed", "native/libx.so.1"})

    def test_duplicate_native_basename_fails_before_mapping(self):
        with self.assertRaisesRegex(CandidateError, "duplicate native basename"):
            native_inventory({"native/libx.so": b"\x7fELFone", "other/libx.so": b"\x7fELFtwo"})

    def public(self, entry=None):
        return {"package/Index.d.ets": (entry or '// @keepTs\n// @ts-nocheck\nexport { openRuntime, BoundaryError, Snapshot, Runtime, Engine, Operation, Subscription } from "./src/main/ets/d";').encode(),
                "package/src/main/ets/d.d.ets": b"declarations"}

    def test_exact_compiler_entry(self):
        self.assertEqual(len(ordinary_public_entry(self.public(), {})), 7)

    def test_new_test_exports_are_rejected_without_prefix_guessing(self):
        for extra in ("testDeliveryGate", "testHandleAdmission", "unrelatedNewExport"):
            text = self.public()["package/Index.d.ets"].decode().replace("Subscription }", "Subscription, " + extra + " }")
            with self.subTest(extra=extra), self.assertRaises(CandidateError):
                ordinary_public_entry(self.public(text), {})

    def test_hidden_extra_statement_star_alias_or_subpath_rejected(self):
        base = self.public()["package/Index.d.ets"].decode()
        for text in (base + ' export { testDeliveryGate } from "./src/main/ets/d";', 'export * from "./src/main/ets/d";', base.replace('Subscription }', 'Subscription as Other }')):
            with self.subTest(text=text), self.assertRaises(CandidateError):
                ordinary_public_entry(self.public(text), {})
        with self.assertRaises(CandidateError):
            ordinary_public_entry(self.public(), {"exports": {"./test": "./private.d.ets"}})


class C07ToolTreeTests(unittest.TestCase):
    def test_two_public_inventory_definitions_are_distinct_and_exact(self):
        from c07_toolchain import inventory, inventory_digest
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sub").mkdir()
            (root / "sub/data").write_bytes(b"abc")
            (root / "sub/data").chmod(0o600)
            (root / "link").symlink_to("sub/data")
            cli = inventory(root, cli=True)
            jbr = inventory(root, cli=False)
            self.assertEqual(cli["count"], 4)
            self.assertEqual(jbr["count"], 2)
            self.assertEqual(cli["size"], 3)
            self.assertEqual(jbr["size"], 3)
            self.assertEqual([row for row in cli["entries"] if row["kind"] == "file"][0]["sha256"], file_digest(b"abc")[7:])
            self.assertEqual([row for row in jbr["entries"] if "sha256" in row][0]["sha256"], file_digest(b"abc"))
            before = cli["sha256"]
            (root / "sub/data").write_bytes(b"abd")
            self.assertNotEqual(inventory(root, cli=True)["sha256"], before)

    def test_tool_tree_rejects_external_symlink(self):
        from c07_toolchain import inventory
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "escape").symlink_to("/etc/passwd")
            for cli in (False, True):
                with self.subTest(cli=cli), self.assertRaises(CandidateError):
                    inventory(root, cli=cli)

class C07EmbeddedIdentityTests(unittest.TestCase):
    def setUp(self):
        from c07_candidate import verify_embedded_identity
        self.check = verify_embedded_identity
        self.identity = {"abi_digest": "sha256:" + "a" * 64, "profile_digest": "sha256:" + "b" * 64, "build_id": "sha256:" + "c" * 64}
        self.identity["expected_identity"] = "madb-arkts/1:" + ":".join(self.identity[name][7:] for name in ("abi_digest", "profile_digest", "build_id"))
        self.expected = self.identity["expected_identity"].encode()
        self.facade = b'const EXPECTED_IDENTITY: string = "' + self.expected + b'";'
        constants = {"GatewayAbi": "a" * 64, "GatewayProfile": "b" * 64, "GatewayBuild": "c" * 64,
                     "GatewayIdentity": self.expected.decode(), "GatewayRouteIdentity": "c/" + self.expected.decode(), "GatewayModuleName": "madbc07sdkc"}
        self.header = b"\n".join(('inline constexpr const char* ' + name + '="' + value + '";').encode() for name, value in constants.items())
        self.members = {"package/ets/modules.abc": b"bytecode\0" + self.expected + b"\0",
                        "package/libs/arm64-v8a/libmadbc07sdkc.so": b"\x7fELF\0" + self.expected + b"\0c/" + self.expected + b"\0madb-arkts/1:\0"}

    def run_check(self, **changes):
        values = dict(identity=self.identity, route="c", module="madbc07sdkc", facade=self.facade, header=self.header, members=self.members)
        values.update(changes)
        return self.check(**values)

    def test_same_declared_and_embedded_identity(self):
        self.run_check()

    def test_rehashed_metadata_alone_cannot_change_runtime_identity(self):
        identity = dict(self.identity, build_id="sha256:" + "d" * 64,
                        expected_identity=self.expected.decode().replace("c" * 64, "d" * 64))
        with self.assertRaises(CandidateError):
            self.run_check(identity=identity)

    def test_header_facade_abc_and_dso_mutation_fail(self):
        for source in ("facade", "header", *self.members):
            with self.subTest(source=source), self.assertRaises(CandidateError):
                if source in ("facade", "header"):
                    self.run_check(**{source: getattr(self, source).replace(b"c" * 64, b"d" * 64)})
                else:
                    self.run_check(members={key: data.replace(b"c" * 64, b"d" * 64) if key == source else data for key, data in self.members.items()})

    def test_additional_conflicting_or_malformed_value_fails(self):
        for extra in (self.expected.replace(b"c" * 64, b"d" * 64), b"madb-arkts/1:bad"):
            for source in self.members:
                with self.subTest(source=source, extra=extra), self.assertRaises(CandidateError):
                    self.run_check(members={key: data + extra + b"\0" if key == source else data for key, data in self.members.items()})

    def test_nonidentity_header_digest_and_route_must_match(self):
        with self.assertRaises(CandidateError):
            self.run_check(header=self.header.replace(b'GatewayBuild="' + b"c" * 64, b'GatewayBuild="' + b"d" * 64))
        with self.assertRaises(CandidateError):
            self.run_check(route="rust")


    def test_wrong_embedded_route_commented_constant_and_longer_identity_fail(self):
        with self.assertRaises(CandidateError):
            self.run_check(members={key: data.replace(b"c/madb-", b"rust/madb-") for key, data in self.members.items()})
        for source in ("header", "facade"):
            with self.subTest(source=source), self.assertRaises(CandidateError):
                self.run_check(**{source: b"/*" + getattr(self, source) + b"*/"})
        with self.assertRaises(CandidateError):
            self.run_check(members={key: data.replace(self.expected + b"\0", self.expected + b"suffix\0") for key, data in self.members.items()})


class C07ExecutionBoundaryTests(unittest.TestCase):
    def test_ambient_code_injection_is_not_inherited(self):
        from c07_execution import inherited_environment
        source = {"HOME": "/same/home", "PATH": "/usr/bin", "HDC_SERVER_PORT": "existing",
                  "NODE_OPTIONS": "--require external", "JAVA_TOOL_OPTIONS": "-agentpath:external",
                  "_JAVA_OPTIONS": "x", "JDK_JAVA_OPTIONS": "x", "DYLD_INSERT_LIBRARIES": "x",
                  "BASH_ENV": "x", "PYTHONPATH": "x", "PYTHONSTARTUP": "x", "LD_PRELOAD": "x"}
        self.assertEqual(inherited_environment(source), {key: source[key] for key in ("HOME", "PATH", "HDC_SERVER_PORT")})

    def test_completion_after_total_deadline_is_rejected(self):
        from c07_execution import Session, ExecutionError
        from types import SimpleNamespace
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            session = Session.__new__(Session)
            session.args = SimpleNamespace(output=Path(temporary))
            session.hap, session.nonce = Path(temporary) / "not-installed.hap", "deadline-test"
            clock, budgets = [0.0], []
            def hdc(label, *args, **kwargs):
                if label in ("probe-pid", "probe-hilog"):
                    budgets.append(kwargs["timeout"])
                    clock[0] += 30
                return {"stdout": "123" if label == "probe-pid" else "complete but late"}
            session.hdc = hdc
            with patch("c07_execution.time.monotonic", side_effect=lambda: clock[0]), patch("c07_observations.parse_ordinary", return_value={"status": "passed"}) as parser:
                with self.assertRaisesRegex(ExecutionError, "watchdog expired"):
                    session.execute()
                parser.assert_not_called()
            self.assertEqual(budgets, [20, 20])


class C07GenerationOracleTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "workspace/derived").mkdir(parents=True)
        (root / "workspace/derived/Boundary.declarations.ets").write_text("export async function openRuntime(): Promise<Runtime> {}\n")
        error = "derived/Boundary.declarations.ets:1:1: ARKTS_DECL_UNSUPPORTED_MODIFIERS: unsupported export/member modifiers"
        result = {"requested_stage": "generate", "completed_requested_stage": False, "target_executed": False, "error": error}
        (root / "result.json").write_text(json.dumps(result))
        return root, {"timeout": False, "exit_code": 1, "stderr": error}, result

    def test_exact_source_rejection(self):
        from c07_generation import validate_rejection
        root, command, _ = self.fixture()
        self.assertEqual(validate_rejection(root, command, "reject-async")["classification"], "ARKTS_DECL_UNSUPPORTED_MODIFIERS")

    def test_arbitrary_failure_timeout_and_wrong_node_do_not_pass(self):
        from c07_generation import validate_rejection
        from c07_execution import ExecutionError
        root, command, _ = self.fixture()
        for changed in (dict(command, stderr="missing SDK"), dict(command, timeout=True), dict(command, exit_code=2),
                        dict(command, stderr=command["stderr"].replace(":1:1:", ":2:1:"))):
            with self.subTest(command=changed), self.assertRaises(ExecutionError):
                validate_rejection(root, changed, "reject-async")

    def test_matching_message_does_not_allow_committed_source(self):
        from c07_generation import validate_rejection
        from c07_execution import ExecutionError
        root, command, result = self.fixture()
        result["source"] = "unexpected Source"
        (root / "result.json").write_text(json.dumps(result))
        with self.assertRaises(ExecutionError):
            validate_rejection(root, command, "reject-async")


class C07GenerationDeadlineTests(unittest.TestCase):
    def test_four_individually_bounded_commands_cannot_exceed_case_deadline(self):
        from c07_generation import GenerationDeadline
        from c07_execution import ExecutionError
        from unittest.mock import patch
        clock, limits = [0.0], []
        class SlowSession:
            def run(self, label, command, timeout, **options):
                limits.append(timeout)
                clock[0] += 179
                return {"exit_code": 0, "timeout": False}
        timer = GenerationDeadline(600)
        with patch("c07_generation.time.monotonic", side_effect=lambda: clock[0]):
            for index in range(3):
                timer.run(SlowSession(), str(index), ["not-executed"], 180)
            with self.assertRaisesRegex(ExecutionError, "overall generation watchdog expired"):
                timer.run(SlowSession(), "last", ["not-executed"], 180)
        self.assertEqual(limits, [180, 180, 180, 63])
