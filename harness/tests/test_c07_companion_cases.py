"""Finite coverage and current-candidate binding tests; never target evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))
from c07_companion_cases import GROUPS, SCENARIO_TIMEOUT_MS, assess_group, scenario_plan
from c07_companion_observations import SCENARIOS

DIGEST = "sha256:" + "a" * 64
RUN = "new-controller-run"
READY_GROUPS = {"operations", "event-fifo-and-atomic","single-claim", "dropped-promise",
                "fanout-allocation", "event-outstanding", "shared-waiters", "settling-reentry",
                "runtime-close-full", "env-exit-full", "getters-and-reentry", "terminal-winner",
                "result-transfer-failures", "source-stop", "request-before-observer", "listener-throw-close", "state", "request-only-retirement", "generation-and-handles", "subscriptions", "state-staging-bytes", "retained-bytes-and-scratch"}


def observations():
    # Fake successful children exist only to test the aggregator boundary. Their
    # frames are not valid input to the independent scenario oracle.
    return {scenario: {"candidate_digest": DIGEST, "run_id": RUN,
        "observation": {"status": "passed", "route": "c", "case": scenario,
            "nonce": "fresh-" + scenario, "pid": 123, "frames": {"host-double": [1]},
            "failures": [], "problems": [], "certifies_c07": False}}
        for scenario in SCENARIOS}


class CompanionCoverageTests(unittest.TestCase):
    def assess(self, group="env-exit-full", records=None, **changes):
        arguments = dict(route="c", candidate_digest=DIGEST, run_id=RUN,
                         observations=observations() if records is None else records)
        arguments.update(changes)
        return assess_group(group, **arguments)

    def test_exact_existing_25_groups_and_44_unique_scenarios(self):
        requirements = json.loads((ROOT / "consumers/arkts/c07/requirements.json").read_text())
        for route in ("c", "cpp", "rust"):
            profile = next(item for item in requirements["profiles"] if item["profile_id"] == "c07-" + route + "-arkts-aarch64-ohos23-test")
            self.assertEqual(set(GROUPS), {name.rsplit(".", 1)[1] for name in profile["required_cases"]})
            plan = scenario_plan(route)
            self.assertEqual(len(plan), 44)
            self.assertEqual(set(plan), set(SCENARIOS))
        self.assertEqual(scenario_plan("kotlin"), ())

    def test_successful_scenarios_close_only_the_reviewed_groups(self):
        statuses = {group: self.assess(group)["status"] for group in GROUPS}
        self.assertEqual({name for name, status in statuses.items() if status == "passed"}, READY_GROUPS)
        self.assertEqual(sum(status == "blocked" for status in statuses.values()), 3)
        for group in set(GROUPS) - READY_GROUPS:
            self.assertTrue(self.assess(group)["gaps"], group)

    def test_missing_child_does_not_pass_even_if_every_other_scenario_passes(self):
        records = observations(); del records["worker-env-exit"]
        result = self.assess(records=records)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["missing_scenarios"], ["worker-env-exit"])

    def test_subscription_map_without_actual_listener_lifetime_is_blocked(self):
        records=observations();del records["listener-lifetime"]
        self.assertEqual(self.assess("subscriptions",records)["status"],"blocked")

    def test_companion_identity_alone_does_not_claim_ordinary_wrong_library(self):
        result=self.assess("identity")
        self.assertEqual(result["status"],"blocked")
        self.assertTrue(any("ordinary" in gap for gap in result["gaps"]))

    def test_retained_development_run_and_other_candidate_are_rejected(self):
        for field, value in (("run_id", "old-development-run"), ("candidate_digest", "sha256:" + "b" * 64)):
            records = observations(); records["worker-env-exit"][field] = value
            with self.subTest(field=field):
                self.assertEqual(self.assess(records=records)["status"], "error")

    def test_wrong_case_route_or_malformed_success_is_not_counted(self):
        for field, value in (("case", "full-waiters"), ("route", "rust"), ("pid", True),
                             ("nonce", ""), ("frames", {}), ("certifies_c07", True),
                             ("problems", ["real failure"]), ("failures", ["PROBE_FAILED"])):
            records = observations(); records["worker-env-exit"]["observation"][field] = value
            with self.subTest(field=field):
                self.assertEqual(self.assess(records=records)["status"], "error")

    def test_incomplete_or_timeout_never_becomes_a_legal_winner(self):
        for status in ("incomplete", "error", "timeout", "invented-status"):
            records = observations(); records["worker-env-exit"]["observation"]["status"] = status
            with self.subTest(status=status):
                self.assertEqual(self.assess(records=records)["status"], "error")

    def test_actual_failure_is_not_hidden_by_coverage_gap(self):
        records = observations(); records["terminal-success"]["observation"]["status"] = "failed"
        self.assertEqual(self.assess("terminal-winner", records)["status"], "failed")

    def test_unsupported_scenario_and_kotlin_remain_blocked(self):
        records = observations(); records["worker-env-exit"]["observation"]["status"] = "unsupported"
        self.assertEqual(self.assess(records=records)["status"], "blocked")
        self.assertEqual(self.assess(route="kotlin")["status"], "blocked")

    def test_ordinary_baseline_cannot_silently_close_companion_requirements(self):
        records = {"ordinary-baseline": next(iter(observations().values()))}
        for group in GROUPS:
            self.assertEqual(self.assess(group, records)["status"], "blocked")

    def test_both_source_and_build_binding_are_needed_with_current_target(self):
        receipt={"candidate_digest":DIGEST,"run_id":RUN,"observation":{
            "status":"bound","candidate_digest":DIGEST,"route":"c","producer_revision":"frozen",
            "source_review":{"status":"bound","route":"c","variant":"test", "producer_revision":"frozen", "inventory_sha256":DIGEST}}}
        for group in ("worker-and-domain","route-ownership"):
            self.assertEqual(self.assess(group,route_ownership=receipt)["status"],"passed")
            missing=deepcopy(receipt);missing["observation"]["source_review"]["status"]="blocked"
            self.assertEqual(self.assess(group,route_ownership=missing)["status"],"blocked")
            stale=deepcopy(receipt);stale["run_id"]="old-run"
            self.assertEqual(self.assess(group,route_ownership=stale)["status"],"blocked")
            records=observations();records["terminal-success"]["observation"]["status"]="failed"
            self.assertEqual(self.assess(group,records,route_ownership=receipt)["status"],"failed")

    def test_candidate_and_current_run_bindings_are_mandatory(self):
        self.assertEqual(self.assess(candidate_digest="") ["status"], "error")
        self.assertEqual(self.assess(run_id="") ["status"], "error")
        with self.assertRaises(ValueError):
            self.assess("new-unreviewed-group")

    def test_registry_preserves_required_expectations_and_fixture_bytes(self):
        requirements = json.loads((ROOT / "consumers/arkts/c07/requirements.json").read_text())
        wanted = {item["id"]: item for item in requirements["cases"]}
        fixture = ROOT / "harness/c07_companion_cases.py"
        data = fixture.read_bytes()
        for prefix in ("arkts-c", "arkts-cpp", "arkts-rust"):
            for group in GROUPS:
                case = json.loads((ROOT / "cases/c07" / prefix / (group + ".json")).read_text())
                requirement = wanted["c07." + prefix + "." + group]
                self.assertEqual(case["id"], requirement["id"])
                self.assertEqual(case["problem_ids"], requirement["problem_ids"])
                self.assertEqual(case["assertions"][0]["expected"], [{"kind": "string", "value": requirement["independent_expectation"]}])
                self.assertEqual(case["fixture"], {"path": "harness/c07_companion_cases.py",
                    "sha256": "sha256:" + hashlib.sha256(data).hexdigest(), "size": len(data), "schema": "madb.lab-source/1"})
                self.assertEqual(case["timeout_policy"]["on_timeout"], "error")
                self.assertEqual(case["timeout_policy"]["timeout_ms"], SCENARIO_TIMEOUT_MS * max(1, len(GROUPS[group]["scenarios"])))
                self.assertIsNone(case["selector"])


if __name__ == "__main__":
    unittest.main()
