"""Execute fresh public companion consumers; retained development logs are never inputs."""
from copy import copy
import json
from pathlib import Path
import time
import uuid
from candidate import CandidateError, read_json
from c07_companion_cases import scenario_plan
from c07_companion_observations import parse_controlled, validate_contracts
from c07_contract import SOURCE
from c07_execution import BUNDLE, ExecutionError, Session, ref, write_json


def companion_contracts(candidate):
    """Read only files already admitted by the common candidate verifier."""
    inventory = {item["path"] for section in ("files", "dependencies", "build_evidence")
                 for item in candidate["manifest"][section]}
    paths = {"runtime-frame-layout.json": "generated/contract/frame-layout.json",
             **{name: "generated/contract/test/" + name for name in
                ("test-frame-layout.json", "observer-layout.json", "facade-frame-layout.json",
                 "bootstrap-totals-layout.json", "ports-layout.json")}}
    if not set(paths.values()).issubset(inventory):
        raise CandidateError("ArtifactMismatch", "companion layout is not an explicit candidate file")
    contracts = {name: read_json(candidate["root"] / path) for name, path in paths.items()}
    errors = validate_contracts(contracts)
    if errors:
        raise CandidateError("ProfileMismatch", "; ".join(errors))
    return contracts, [ref(candidate["root"] / path, candidate["root"]) for path in paths.values()]


class ControlledSession(Session):
    def __init__(self, args, candidate, scenario, contracts):
        super().__init__(args, candidate)
        self.scenario, self.contracts = scenario, contracts

    def prepare(self):
        super().prepare()
        target = self.root / "entry/src/main/ets"
        for source in sorted((SOURCE / "controlled").rglob("*.ets.in")):
            destination = target / source.relative_to(SOURCE / "controlled").with_suffix("")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source.read_text().replace("@MADB_PUBLIC_MODULE@", json.dumps(self.candidate["module"])))
        (target / "pages/Index.ets").write_text((SOURCE / "ControlledPage.ets.in").read_text())
        page = target / "pages/Index.ets"
        page.write_text(page.read_text().replace("@MADB_PUBLIC_MODULE@", json.dumps(self.candidate["module"])))
        (target / "ProbeCase.ets").write_text("export const PROBE_CASE: string = " + json.dumps(self.scenario) + ";\n")
        with (target / "ProbeConfig.ets").open("a") as stream:
            stream.write("export const EXPECTED_OBSERVATION_PREFIX: string = " + json.dumps(
                "madb-observe/1/" + self.args.route + "/" + self.candidate["identity"]["expected_identity"]) + ";\n")

    def parse_observation(self, raw, pid):
        return parse_controlled(raw, nonce=self.nonce, pid=pid, case=self.scenario,
            route=self.args.route, contracts=self.contracts)

    def execute(self):
        started = time.monotonic()
        deadline = started + 50
        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise ExecutionError("controlled consumer watchdog expired; cleanup not proved")
            return min(20, value)
        self.hdc("install", "install", "-r", self.hap, timeout=remaining())
        self.hdc("stop-old-probe", "shell", "aa", "force-stop", BUNDLE, expected=None, timeout=remaining())
        self.hdc("start", "shell", "aa", "start", "-a", "EntryAbility", "-b", BUNDLE, timeout=remaining())
        while True:
            pid = self.hdc("probe-pid", "shell", "pidof", BUNDLE, expected=None, timeout=remaining())["stdout"].strip()
            raw = self.hdc("probe-hilog", "shell", "hilog", "-x", "-T", "MadBC07Probe", timeout=remaining())["stdout"]
            remaining()
            # Startup may have no process yet. Missing PID is never success and still consumes the same watchdog.
            if not pid and self.nonce not in raw:
                time.sleep(min(.1, remaining()))
                continue
            observation = self.parse_observation(raw, pid)
            write_json(self.args.output / f"{self.nonce}-observation-{time.time_ns()}.json", observation)
            if observation["status"] in ("passed", "failed", "unsupported"):
                observation["duration_ms"] = int((time.monotonic() - started) * 1000)
                return observation
            time.sleep(min(.4, remaining()))


def run_companion(args, candidate):
    """Serial device execution, unique source/HAP/nonce/PID per scenario."""
    plan = scenario_plan(args.route)
    result = {"run_id": "c07-controlled-" + uuid.uuid4().hex,
              "candidate_digest": candidate["manifest"]["candidate_digest"],
              "observations": {}, "target": {}, "scope": "current candidate controlled scenarios only",
              "certifies_c07": False}
    if not plan:
        result["reason"] = "route has no independent controlled executor"
        return result
    from c07_identity_execution import IdentitySession
    from c07_identity_observations import SCENARIOS as IDENTITY_SCENARIOS
    from c07_identity_fixtures import admit_identity_fixtures
    fixture_path = getattr(args, "identity_fixtures", None)
    fixture_pin = getattr(args, "identity_fixtures_sha256", None)
    if bool(fixture_path) != bool(fixture_pin):
        raise CandidateError("ArtifactMismatch", "identity fixtures require both explicit collection and SHA-256")
    fixtures = None
    if fixture_path:
        fixtures, fixture_refs = admit_identity_fixtures(fixture_path, fixture_pin, candidate)
        result["identity_fixture_inputs"] = fixture_refs
    contracts, inputs = companion_contracts(candidate)
    result["contract_inputs"] = inputs
    session = Session(args, candidate)
    session.verify_tools()
    result["target"] = session.verify_target()
    try:
        for scenario in plan:
            output = args.output / "scenarios" / scenario
            output.mkdir(parents=True)
            scenario_args = copy(args)
            scenario_args.output = output
            if scenario in IDENTITY_SCENARIOS and fixtures is None:
                observed = {"status":"unsupported","case":scenario,"route":args.route,"nonce":None,"pid":None,
                    "frames":{},"problems":["explicit matched identity-fixture collection not supplied"],"failures":[],"certifies_c07":False}
                envelope = {"candidate_digest":result["candidate_digest"],"run_id":result["run_id"],
                    "observation":observed,"cleanup":"not-run","attachments":[]}
                write_json(output/"result.json",envelope);result["observations"][scenario]=envelope
                continue
            child = (IdentitySession(scenario_args, candidate, scenario, contracts,
                fixtures.get(scenario.removeprefix("identity-"))) if scenario in IDENTITY_SCENARIOS
                else ControlledSession(scenario_args, candidate, scenario, contracts))
            observed = None
            try:
                child.prepare()
                child.build()
                observed = child.execute()
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                observed = {"status": "error", "case": scenario, "route": args.route,
                            "nonce": child.nonce, "pid": None, "frames": {},
                            "problems": [str(error)], "failures": [], "certifies_c07": False}
            finally:
                if hasattr(child, "hap"):
                    try:
                        child.stop()
                    except (OSError, RuntimeError) as error:
                        observed = dict(observed or {}, status="error", case=scenario, route=args.route,
                                        problems=["test recovery failed: " + str(error)])
                envelope = {"candidate_digest": result["candidate_digest"], "run_id": result["run_id"],
                            "observation": observed, "cleanup": "complete" if child.stopped else "not-run",
                            "attachments": [ref(path, args.output) for path in sorted(output.iterdir()) if path.is_file()]}
                write_json(output / "result.json", envelope)
                result["observations"][scenario] = envelope
            print("C07 controlled " + scenario + ": " + observed["status"], flush=True)
            if observed["status"] == "error":
                # Transport/build failure cannot support dependent later scenarios.
                break
    finally:
        session.verify_closure("after")
    return result
