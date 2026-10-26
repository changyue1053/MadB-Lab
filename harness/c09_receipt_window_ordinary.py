"""Run the unchanged public ordinary consumer for a newly paired C09 identity."""
import argparse
from pathlib import Path
import json
import platform
import sys

from candidate import CandidateError
from c07_execution import Session, ref, write_json
from c07_observations import parse_ordinary
from c07_profile_pair import verify_profile_pair
from c09_close_windows import guarded_output
from c09_receipt_window import ROOT, REVIEW_ID, ReceiptWindowSession, check_candidate, code_snapshot
from runners.first_route import lab_source_identity


class OrdinarySession(ReceiptWindowSession):
    def prepare(self):
        Session.prepare(self)

    def parse_observation(self, raw, pid):
        return parse_ordinary(raw, nonce=self.nonce, pid=pid)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True, help='new test companion used only for source pairing')
    parser.add_argument('--expected-candidate-digest', required=True)
    parser.add_argument('--ordinary-candidate', type=Path, required=True)
    parser.add_argument('--expected-ordinary-digest', required=True)
    parser.add_argument('--route', choices=('c', 'cpp', 'rust', 'kotlin'), required=True)
    parser.add_argument('--command-line-tools', type=Path, required=True)
    parser.add_argument('--java-home', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--target-kind', choices=('emulator', 'physical'), required=True)
    parser.add_argument('--allow-dirty', action='store_true')
    signing = parser.add_mutually_exclusive_group(required=True)
    signing.add_argument('--community-debug-signing', action='store_true')
    signing.add_argument('--signing-config', type=Path)
    args = parser.parse_args(argv)
    if args.target.startswith('-') or any(c.isspace() or ord(c) < 32 for c in args.target):
        parser.error('exactly one explicit target is required')
    protected = [ROOT, args.candidate, args.ordinary_candidate, args.command_line_tools, args.java_home]
    if args.signing_config:
        protected.append(args.signing_config)
    try:
        args.output = guarded_output(args.output, protected); args.output.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    report = {'task': 'C09', 'scope': 'new ordinary candidate identity; existing independent ordinary public API baseline',
              'route': args.route, 'candidate_digest': args.expected_ordinary_digest,
              'build': 'not-run', 'execution': 'not-run', 'sdk_cleanup': 'not-proved', 'device_recovery': 'not-needed',
              'result': 'failed', 'review_id': REVIEW_ID, 'certifies_c07': False, 'certifies_c09': False, 'errors': []}
    session = None
    try:
        if platform.python_version() != (ROOT / '.python-version').read_text().strip():
            raise RuntimeError('use Lab pinned Python')
        revision, dirty, digest = lab_source_identity(ROOT, None, args.allow_dirty)
        report.update(lab_revision=revision, lab_source_digest=digest, provisional=dirty)
        companion = check_candidate(args.candidate, args.route, True, args.expected_candidate_digest)
        ordinary = check_candidate(args.ordinary_candidate, args.route, False, args.expected_ordinary_digest)
        if companion['provenance'].get('provisional') or ordinary['provenance'].get('provisional'):
            raise CandidateError('ArtifactMismatch', 'new ordinary baseline requires frozen producer candidates')
        report['profile_pair'] = verify_profile_pair(ordinary, companion, review_id=REVIEW_ID)
        if report['profile_pair'].get('status') != 'bound':
            raise CandidateError('ArtifactMismatch', 'fixed independent ordinary/test pairing is incomplete')
        report['producer'] = ordinary['provenance']; report['lab_inputs'] = code_snapshot()
        session = OrdinarySession(args, ordinary, 'ordinary-public-api', {})
        session.verify_tools(); report['target'] = session.verify_target()
        session.prepare(); report['build'] = 'running'; session.build(); report['build'] = 'passed'
        observation = session.execute(); report['observation'] = observation; report['execution'] = observation['status']
        if observation['status'] != 'passed':
            raise RuntimeError('unchanged independent ordinary oracle failed')
        report['sdk_cleanup'] = 'ordinary close API completed; no companion-only resource counter claim'
        session.verify_closure('after')
        check_candidate(args.candidate, args.route, True, args.expected_candidate_digest)
        check_candidate(args.ordinary_candidate, args.route, False, args.expected_ordinary_digest)
        if code_snapshot() != report['lab_inputs']:
            raise CandidateError('ArtifactMismatch', 'consumed Lab inputs changed during ordinary run')
        report['result'] = 'passed'
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        report['errors'].append(str(error))
        if report['build'] == 'running': report['build'] = 'failed'
    finally:
        if session is not None and session.start_dispatched:
            report['device_recovery'] = 'failed'
            try:
                session.stop(); report['device_recovery'] = 'passed; process recovery only'
            except (OSError, RuntimeError) as error:
                report['errors'].append('device recovery: ' + str(error)); report['result'] = 'failed'
        report['attachments'] = [ref(p, args.output) for p in sorted(args.output.iterdir()) if p.is_file()]
        write_json(args.output / 'report.json', report)
    print(json.dumps({k: report[k] for k in ('result', 'build', 'execution', 'device_recovery', 'errors')}))
    return int(report['result'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
