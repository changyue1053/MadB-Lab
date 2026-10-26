"""Independent C09 receipt window and selected unchanged C07 regression consumers."""
from copy import copy
import argparse
import json
from pathlib import Path
import platform
import sys

from candidate import CandidateError, file_digest, read_json
from c07_candidate import verify_candidate
from c07_contract import SOURCE
from c07_controlled_execution import ControlledSession, companion_contracts
from c07_execution import BUNDLE, ExecutionError, Session, ref, write_json
from c07_kotlin_execution import KotlinSession, kotlin_contracts, napi_inventory_command
from c07_profile_pair import verify_profile_pair
from c09_close_windows import CloseWindowSession, guarded_output
from c09_receipt_window_observations import SCENARIOS, parse_observation
from runners.first_route import lab_source_identity

ROOT = Path(__file__).resolve().parents[1]
SUPPLEMENT = ROOT / 'consumers/arkts/c09_receipt_window'
REVIEW_ID = 'c09-receipt-window'
NATIVE_REGRESSIONS = ('full-waiters', 'failed-close-before-guard', 'failed-close-after-accepted',
                      'settling-reentry', 'worker-env-exit')
KOTLIN_REGRESSIONS = ('kotlin-live-threads', 'kotlin-settling-reentry',
                      'kotlin-fault-before-guard', 'kotlin-fault-after-accepted')


def code_snapshot():
    paths = set()
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name and Path(name).resolve().is_relative_to(ROOT):
            paths.add(Path(name).resolve())
    for directory in (SOURCE, SUPPLEMENT, ROOT / 'expected/c09_receipt_window'):
        paths.update(p for p in directory.rglob('*') if p.is_file())
    return {str(p.relative_to(ROOT)): file_digest(p.read_bytes()) for p in sorted(paths)}


class ReceiptWindowSession(CloseWindowSession):
    def __init__(self, args, candidate, scenario, contracts, napi_binding=None, napi_identity=None):
        super().__init__(args, candidate, scenario, contracts)
        self.napi_binding, self.napi_identity = napi_binding, napi_identity

    def prepare(self):
        if self.scenario not in SCENARIOS:
            if self.args.route == 'kotlin':
                KotlinSession.prepare(self)
            else:
                ControlledSession.prepare(self)
            return
        Session.prepare(self)
        target = self.root / 'entry/src/main/ets'
        module = json.dumps(self.candidate['module'])
        names = {'ReceiptWindow.ets.in': 'ReceiptWindow.ets', 'Page.ets.in': 'pages/Index.ets',
                 'NegativeProbes.js': 'NegativeProbes.js', 'NegativeProbes.d.ts': 'NegativeProbes.d.ts',
                 ('KotlinObservations.ets.in' if self.args.route == 'kotlin' else 'NativeObservations.ets.in'):
                 'ReceiptObservations.ets'}
        for source, destination in names.items():
            (target / destination).write_text((SUPPLEMENT / source).read_text().replace('@MADB_PUBLIC_MODULE@', module))
        (target / 'ProbeCase.ets').write_text('export const PROBE_CASE: string = ' + json.dumps(self.scenario) + ';\n')

    def parse_observation(self, raw, pid):
        if self.scenario in SCENARIOS:
            return parse_observation(raw, nonce=self.nonce, pid=pid, route=self.args.route, scenario=self.scenario)
        if self.args.route == 'kotlin':
            return KotlinSession.parse_observation(self, raw, pid)
        return ControlledSession.parse_observation(self, raw, pid)

    def stop(self):
        if not self.start_dispatched:
            return
        stopped = self.hdc('stop-own-probe', 'shell', 'aa', 'force-stop', BUNDLE)
        if 'force stop process successfully.' not in stopped['stdout']:
            raise ExecutionError('target did not confirm stopping own probe')
        pid = self.hdc('own-pid-after', 'shell', 'pidof', BUNDLE, expected=None)['stdout'].strip()
        if pid:
            raise ExecutionError('own probe still running after recovery')
        uninstalled = self.hdc('uninstall-own-probe', 'uninstall', BUNDLE, timeout=60)
        if 'uninstall bundle successfully.' not in uninstalled['stdout']:
            raise ExecutionError('target did not confirm uninstalling own probe')
        write_json(self.args.output / 'device-after.json', {'bundle': BUNDLE, 'pid': pid, 'uninstalled': True,
                   'scope': 'test process recovery only; never native close/receipt evidence'})
        self.stopped = True


def check_candidate(path, route, companion, expected):
    candidate = verify_candidate(path, route, companion=companion)
    if candidate['manifest']['candidate_digest'] != expected:
        raise CandidateError('ArtifactMismatch', 'candidate differs from independently pinned digest')
    return candidate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--expected-candidate-digest', required=True)
    parser.add_argument('--ordinary-candidate', type=Path, required=True)
    parser.add_argument('--expected-ordinary-digest', required=True)
    parser.add_argument('--route', choices=('c', 'cpp', 'rust', 'kotlin'), required=True)
    parser.add_argument('--scenario', choices=(*SCENARIOS, 'regressions', 'suite'), default='suite')
    parser.add_argument('--command-line-tools', type=Path, required=True)
    parser.add_argument('--java-home', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--target')
    parser.add_argument('--target-kind', choices=('emulator', 'physical'))
    parser.add_argument('--allow-dirty', action='store_true')
    signing = parser.add_mutually_exclusive_group(required=True)
    signing.add_argument('--community-debug-signing', action='store_true')
    signing.add_argument('--signing-config', type=Path)
    args = parser.parse_args(argv)
    if not args.build_only and (not args.target or args.target.startswith('-') or
            any(char.isspace() or ord(char) < 32 for char in args.target) or not args.target_kind):
        parser.error('execution requires one explicit target and target-kind')
    protected = [ROOT, args.candidate, args.ordinary_candidate, args.command_line_tools, args.java_home]
    if args.signing_config:
        protected.append(args.signing_config)
    try:
        args.output = guarded_output(args.output, protected)
        args.output.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    report = {'task': 'C09', 'scope': 'new frozen companion: after physical ACK before receipt and named regressions',
              'route': args.route, 'build': 'not-run', 'execution': 'not-run', 'result': 'failed',
              'certifies_c07': False, 'certifies_c09': False, 'review_id': REVIEW_ID,
              'scenario_results': {}, 'errors': [], 'limitations': [
                  'selected target only; no platform-wide or whole-work-package certification',
                  'callback exceptions/nonvoid returns intentionally retain an unconsumed receipt and rejected close; recovery stop is not SDK cleanup',
                  'Kotlin is main-env-only; actual worker-env cleanup regression applies to C/C++/Rust only']}
    try:
        if platform.python_version() != (ROOT / '.python-version').read_text().strip():
            raise RuntimeError('use Lab pinned Python')
        revision, dirty, digest = lab_source_identity(ROOT, None, args.allow_dirty)
        report.update(lab_revision=revision, lab_source_digest=digest, provisional=dirty)
        candidate = check_candidate(args.candidate, args.route, True, args.expected_candidate_digest)
        ordinary = check_candidate(args.ordinary_candidate, args.route, False, args.expected_ordinary_digest)
        report.update(candidate_digest=args.expected_candidate_digest, ordinary_digest=args.expected_ordinary_digest,
                      producer=candidate['provenance'])
        if candidate['provenance'].get('provisional') or ordinary['provenance'].get('provisional'):
            raise CandidateError('ArtifactMismatch', 'receipt window requires newly frozen producer candidates')
        report['profile_pair'] = verify_profile_pair(ordinary, candidate, review_id=REVIEW_ID)
        if report['profile_pair'].get('status') != 'bound':
            raise CandidateError('ArtifactMismatch', 'independent ordinary/companion review binding incomplete')
        reader = kotlin_contracts if args.route == 'kotlin' else companion_contracts
        contracts, inputs = reader(candidate); report['contract_inputs'] = inputs
        parent = Session(args, candidate)
        parent.verify_tools(include_device=not args.build_only)
        if not args.build_only:
            report['target'] = parent.verify_target()
        regressions = KOTLIN_REGRESSIONS if args.route == 'kotlin' else NATIVE_REGRESSIONS
        scenarios = SCENARIOS + regressions if args.scenario == 'suite' else regressions if args.scenario == 'regressions' else (args.scenario,)
        binding, identity = None, None
        if args.route == 'kotlin' and any(case not in SCENARIOS for case in scenarios):
            native = candidate['root'] / 'native'
            contract = candidate['root'] / 'generated/contract/test/napi-observer-frame.json'
            bootstrap = native / ('lib' + candidate['module'] + '.so')
            provider = native / 'libmadb_kotlin_owned_runtime.so'
            identity = {name: file_digest(path.read_bytes())[7:] for name, path in
                        {'bootstrap': bootstrap, 'provider': provider, 'contract': contract}.items()}
            output = args.output / 'napi-inventory'
            parent.run('independent-napi-inventory', napi_inventory_command(sys.executable, contract, bootstrap,
                       provider, parent.sdk / 'openharmony/native/llvm/bin', output), timeout=120)
            binding = read_json(output / 'binding.json')
            report['napi_binding'] = {'identity': identity, 'binding': binding}
        report['lab_inputs'] = code_snapshot()
        for scenario in scenarios:
            output = args.output / 'scenarios' / scenario; output.mkdir(parents=True)
            child_args = copy(args); child_args.output = output
            child = ReceiptWindowSession(child_args, candidate, scenario, contracts, binding, identity)
            result = {'scenario': scenario, 'build': 'not-run', 'execution': 'not-run', 'sdk_cleanup': 'not-proved',
                      'device_recovery': 'not-needed', 'errors': []}
            try:
                child.prepare(); result['build'] = 'running'; child.build(); result['build'] = 'passed'
                if not args.build_only:
                    observed = child.execute(); result['observation'] = observed; result['execution'] = observed['status']
                    if observed['status'] != 'passed':
                        raise ExecutionError('independent target assertions failed')
                    if scenario in SCENARIOS and scenario != 'normal':
                        result['close_outcome'] = 'expected rejection observed'
                        result['sdk_cleanup'] = 'not-confirmed: receipt remains unconsumed, normal close rejected'
                    else:
                        result['sdk_cleanup'] = 'proved by scenario native/JS final frames'
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                if result['build'] == 'running':
                    result['build'] = 'failed'
                result['errors'].append(str(error))
            finally:
                if child.start_dispatched:
                    result['device_recovery'] = 'failed'
                    try:
                        child.stop(); result['device_recovery'] = 'passed; process recovery only'
                    except (OSError, RuntimeError) as error:
                        result['errors'].append('device recovery: ' + str(error))
                result['attachments'] = [ref(p, output) for p in sorted(output.iterdir()) if p.is_file()]
                write_json(output / 'result.json', result)
                report['scenario_results'][scenario] = result
            print(json.dumps({'scenario': scenario, 'build': result['build'], 'execution': result['execution'],
                              'errors': result['errors']}), flush=True)
            if result['errors']:
                raise ExecutionError('scenario failed; remaining scenarios were not run: ' + scenario)
        parent.verify_closure('after')
        check_candidate(args.candidate, args.route, True, args.expected_candidate_digest)
        check_candidate(args.ordinary_candidate, args.route, False, args.expected_ordinary_digest)
        if code_snapshot() != report['lab_inputs']:
            raise CandidateError('ArtifactMismatch', 'consumed Lab input changed during validation')
        report['build'] = 'passed'; report['execution'] = 'not-run' if args.build_only else 'passed'
        report['result'] = 'build-only' if args.build_only else 'passed'
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        report['errors'].append(str(error))
        builds = [result['build'] for result in report['scenario_results'].values()]
        report['build'] = 'failed' if 'failed' in builds else 'partial' if 'passed' in builds else 'not-run'
    write_json(args.output / 'report.json', report)
    print(json.dumps({k: report[k] for k in ('result', 'build', 'execution', 'errors')}))
    return int(bool(report['errors']) or report['build'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
