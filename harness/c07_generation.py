"""Independent generation oracles over public CLI inputs and Source outputs."""
from __future__ import annotations
from pathlib import Path
import re
import sys
import time
from candidate import CandidateError, file_digest, logical_path, read_json
from c07_execution import ExecutionError, ref, write_json

FIXTURES = ("rename-record", "reject-async", "reject-callback-result", "reject-async-listener")
REJECTIONS = {
    "reject-async": ("ARKTS_DECL_UNSUPPORTED_MODIFIERS", "unsupported export/member modifiers"),
    "reject-callback-result": ("ARKTS_DECL_CALLBACK_RESULT", "callback must return void"),
    "reject-async-listener": ("ARKTS_DECL_CALLBACK_RESULT", "callback must return void"),
}


def require(condition, message):
    if not condition:
        raise ExecutionError("generation oracle: " + message)


class GenerationDeadline:
    """One case budget shared by git and all public CLI children."""
    def __init__(self, expires):
        self.expires = expires

    def remaining(self):
        budget = self.expires - time.monotonic()
        require(budget > 0, "overall generation watchdog expired")
        return budget

    def run(self, session, label, command, timeout=30, **options):
        result = session.run(label, command, min(timeout, self.remaining()), **options)
        self.remaining()
        return result


def contained(root, logical):
    path = root / str(logical_path(logical))
    require(path.resolve().is_relative_to(root.resolve()) and not path.is_symlink(), "escaping output path")
    return path


def validate_rename(output, command):
    require(not command["timeout"] and command["exit_code"] == 0, "rename command did not succeed")
    result = read_json(output / "result.json")
    require(result.get("requested_stage") == "generate" and result.get("completed_requested_stage") is True,
            "rename did not commit requested Source generation")
    require(result.get("target_executed") is False and result.get("metadata") == "host-checked", "unexpected CLI stage")
    source = Path(result["source"]).resolve(strict=True)
    require(source.is_relative_to(output.resolve()), "Source is outside this fresh CLI output")
    outputs = read_json(source / "outputs.json")
    require(outputs["generation_id"] == result["generation_id"], "Source generation identity mismatch")
    seen = set()
    for item in outputs["files"]:
        require(item["path"] not in seen, "duplicate Source inventory member")
        seen.add(item["path"])
        path = contained(source, item["path"])
        require(ref(path, source) == {key: item[key] for key in ("path", "sha256", "size")}, "Source member bytes differ")
    require({p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()} == seen | {"outputs.json"},
            "Source inventory is not closed")
    declaration = read_json(source / "declarations.json")["public"]
    require(declaration["authority"] == "exported-arkts-declarations", "missing actual public declaration reader")
    records = declaration["records"]
    require([record["name"] for record in records] == ["Parcel"], "record rename did not reach declarations")
    require([(field["name"], field["type"]) for field in records[0]["fields"]] ==
            [("value", {"tag": "number"}), ("text", {"tag": "string"})], "renamed record shape changed")
    engine = next(item for item in declaration["resources"] if item["name"] == "Engine")
    methods = {item["name"]: item for item in engine["methods"]}
    require("roundtrip" not in methods and "copyRecord" in methods, "method rename did not reach declarations")
    method = methods["copyRecord"]
    require(method["returns"] == {"name": "Parcel", "tag": "reference"} and
            [(p["name"], p["type"]) for p in method["params"]] == [("value", {"name": "Parcel", "tag": "reference"})],
            "renamed method signature differs")
    contract = read_json(output / "workspace/contract.json")
    require(contract["schema"] == "madb.contract-ir/1", "missing public ContractIR")
    types = {item["id"]: item["definition"] for item in contract["types"]}
    require("Snapshot" not in types and types.get("Parcel") == {"kind": "record", "layout": "logical",
            "fields": [{"name": "value", "type_id": "i32"}, {"name": "text", "type_id": "utf8.1024"}]},
            "rename or record shape did not reach ContractIR")
    symbols = {item["source_key"]["qualified_name"]: item for item in contract["symbols"]}
    require("Engine.roundtrip" not in symbols and "Engine.copyRecord" in symbols, "method rename missing in ContractIR")
    symbol = symbols["Engine.copyRecord"]
    require(symbol["public_id"] == "madb.c07.Engine.roundtrip.v1" and symbol["public_id_origin"] == "explicit",
            "explicit capability identity was not preserved across the public rename")
    require(symbol["precision"] == "compiler-derived" and symbol["shape"]["result"] == "Parcel" and
            symbol["shape"]["parameters"] == [{"name": "self", "type_id": "Engine"}, {"name": "value", "type_id": "Parcel"}],
            "ContractIR method shape differs")
    facade = (source / "generated/facade/Boundary.ets").read_text()
    require("export interface Parcel" in facade and "copyRecord(value: Parcel): Parcel" in facade and
            "export interface Snapshot" not in facade, "rename missing in generated public facade")
    return {"fixture": "rename-record", "observation": "passed", "generation_id": result["generation_id"],
            "source_files": len(seen), "declaration_method": method["location"], "record": "Parcel", "method": "Engine.copyRecord"}


def validate_rejection(output, command, fixture):
    require(not command["timeout"] and command["exit_code"] == 1, "negative was timeout or wrong exit status")
    code, message = REJECTIONS[fixture]
    pattern = r"derived/Boundary\.declarations\.ets:([1-9][0-9]*):([1-9][0-9]*): " + re.escape(code + ": " + message)
    matches = list(re.finditer(pattern, command["stderr"]))
    require(len(matches) == 1, "negative lacks its exact declaration diagnostic")
    line, column = map(int, matches[0].groups())
    declaration = output / "workspace/derived/Boundary.declarations.ets"
    lines = declaration.read_text().splitlines()
    require(line <= len(lines) and column <= len(lines[line - 1]) + 1, "diagnostic location is outside actual source")
    source_line = lines[line - 1]
    if fixture == "reject-async":
        require(column == 1 and re.match(r"export\s+async\s+function\s+openRuntime\b", source_line) is not None,
                "modifier diagnostic is not on actual exported async openRuntime")
    elif fixture == "reject-callback-result":
        require("observeState(listener:" in source_line and "=> number" in source_line and
                source_line[column - 1:].startswith("(value:"), "callback diagnostic is not on actual callback result type")
    else:
        require("observeState(listener:" in source_line and "=> Promise<void>" in source_line and
                source_line[column - 1:].startswith("Promise<void>"), "async listener diagnostic is not on actual Promise return type")
    result = read_json(output / "result.json")
    require(result.get("requested_stage") == "generate" and result.get("completed_requested_stage") is False and
            result.get("target_executed") is False and "source" not in result and "generation_id" not in result,
            "negative unexpectedly committed Source or ran target")
    require(code + ": " + message in result.get("error", ""), "result and stderr diagnostic disagree")
    require(not (output / "workspace/generate-execution.json").exists() and
            not list((output / "workspace/domain/batches").glob("*/files/outputs.json")), "negative committed generation")
    return {"fixture": fixture, "observation": "passed", "classification": code,
            "source": "derived/Boundary.declarations.ets", "line": line, "column": column, "source_text": source_line,
            "committed_source": False}


def public_inputs(cli, fixtures, inventory):
    paths = [cli, inventory, Path(sys.executable).resolve(strict=True)]
    paths.extend(fixtures / name / item for name in FIXTURES for item in ("Boundary.ets.in", "runtime-policy.json"))
    return [{"path": str(path), "sha256": file_digest(path.read_bytes()), "size": path.stat().st_size} for path in paths]


def run_generation(session, *, deadline):
    timer = GenerationDeadline(deadline)
    timer.remaining()
    args = session.args
    require(args.route == "c" and not args.companion, "this first public generation fixture is registered for ordinary C only")
    cli, fixtures = args.generator_cli.resolve(strict=True), args.generation_fixtures.resolve(strict=True)
    repository = cli.parent.parent
    require(cli == repository / "scripts/build_arkts_routes.py" and fixtures.is_relative_to(repository),
            "use the explicit public CLI and author fixtures in its checkout")
    require(not args.output.is_relative_to(repository), "generation output must be outside producer checkout")
    inventory = args.cli_inventory.resolve(strict=True)
    require(file_digest(inventory.read_bytes()) == "sha256:" + args.cli_inventory_sha256.removeprefix("sha256:"),
            "acquisition inventory hash differs from explicit pin")
    inputs_before = public_inputs(cli, fixtures, inventory)
    write_json(args.output / "generation-inputs-before.json", inputs_before)

    def git_state(phase):
        head = timer.run(session, "generation-head-" + phase, ["git", "-C", repository, "rev-parse", "HEAD"], inherit_env=True)["stdout"].strip()
        status = timer.run(session, "generation-status-" + phase, ["git", "-C", repository, "status", "--porcelain=v1", "--untracked-files=all"], inherit_env=True)["stdout"]
        return {"head": head, "status": status}

    before = git_state("before")
    expected_revision = session.candidate["provenance"]["producer_revision"]
    if not args.allow_dirty:
        require(before == {"head": expected_revision, "status": ""}, "generation requires candidate revision in a clean producer checkout")
    tracked = [cli.relative_to(repository).as_posix()] + [str((fixtures / name / item).relative_to(repository))
        for name in FIXTURES for item in ("Boundary.ets.in", "runtime-policy.json")]
    tracked_result = timer.run(session, "generation-tracked-inputs", ["git", "-C", repository, "ls-files", "--error-unmatch", "--", *tracked],
                                 inherit_env=True, expected=None)
    observations = []
    generation_root = args.output / "generation"
    generation_root.mkdir()
    for name in FIXTURES:
        output = generation_root / name
        command = [sys.executable, "-I", "-S", "-B", "-X", "pycache_prefix=/dev/null", cli, "--route", "c", "--stop-after", "generate",
            "--cli-root", session.toolkit, "--cli-inventory", inventory,
            "--cli-inventory-sha256", args.cli_inventory_sha256.removeprefix("sha256:"),
            "--python-image", Path(sys.executable).resolve(), "--java-home", session.jdk,
            "--author-fixture", fixtures / name, "--output", output]
        if args.allow_dirty:
            command.append("--allow-dirty")
        actual = timer.run(session, "generation-" + name, command, 180, expected=None, inherit_env=True,
                             extra_env={"PYTHONDONTWRITEBYTECODE": "1"})
        observations.append(validate_rename(output, actual) if name == "rename-record" else validate_rejection(output, actual, name))
    after = git_state("after")
    inputs_after = public_inputs(cli, fixtures, inventory)
    write_json(args.output / "generation-inputs-after.json", inputs_after)
    require(inputs_before == inputs_after, "public CLI, fixtures or input tool bytes changed during generation")
    bound = before == after == {"head": expected_revision, "status": ""} and tracked_result["exit_code"] == 0 and not session.candidate["provenance"].get("provisional", False)
    result = {"status": "passed" if bound else "blocked", "observations": observations,
        "candidate_binding": {"producer_revision": expected_revision, "before": before, "after": after, "clean_matching_checkout": bound},
        "reason": "public generation matched independent Source/diagnostic assertions" if bound else
            "four public generation observations matched, but producer checkout/candidate is provisional or differs; no transfer to candidate generation acceptance"}
    # Preserve every emitted byte as evidence references; never import emitted adapter code.
    files = [ref(path, args.output) for path in sorted(generation_root.rglob("*")) if path.is_file() and not path.is_symlink()]
    write_json(args.output / "generation-output-inventory.json", files)
    timer.remaining()
    write_json(args.output / "generation-observation.json", result)
    return result
