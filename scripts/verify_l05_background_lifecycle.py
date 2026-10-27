"""Explicit L05 real background/resume composition against the frozen public C HAR."""
from pathlib import Path
import argparse
import hashlib
import json
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'harness'))
from candidate import file_digest
from c07_candidate import verify_candidate
from check_repository import snapshot_errors, dependency_errors, IGNORED
from l05_background_lifecycle_execution import BackgroundSession, source_delivery, SOURCE, write_json


def preflight_inputs(root):
    paths = {root / '.python-version', root / 'consumers/arkts/c07/requirements.json'}
    paths.update(p for p in (root / 'docs/reference').rglob('*') if p.is_file())
    paths.update(p for p in root.rglob('Cargo.toml') if p.is_file() and not (set(p.relative_to(root).parts) & IGNORED))
    return paths


def run_build(session, report):
    report['compile'] = 'started'
    try:
        session.build()
    except Exception:
        report['compile'] = 'failed'
        raise
    report['compile'] = 'passed'


def run_target(session, report):
    report['target_execution'] = 'started'
    try:
        result = session.execute()
        report['target_execution'] = 'passed'
        return result
    except Exception:
        report['target_execution'] = 'failed'
        raise
    finally:
        for phase in ('native', 'ui'):
            report[phase] = ('passed' if getattr(session, phase + '_passed', False)
                             else 'failed' if getattr(session, phase + '_started', False) else 'not_run')
        report['runtime_close'] = 'confirmed' if getattr(session, 'runtime_close_confirmed', False) else 'not_confirmed'


def code_snapshot():
    paths = {Path(__file__).resolve()}
    paths.update(preflight_inputs(ROOT))
    paths.update(p for p in SOURCE.rglob('*') if p.is_file())
    for module in tuple(sys.modules.values()):
        path = getattr(module, '__file__', None)
        if path and Path(path).resolve().is_relative_to(ROOT):
            paths.add(Path(path).resolve())
    # The shared HAP shell and signing script are also consumed Lab inputs.
    shell = ROOT / 'consumers/arkts/c07'
    paths.update(p for p in (shell / 'hap-template').rglob('*') if p.is_file())
    paths.update(shell / n for n in ('prepare_debug_signing.sh', 'obfuscation-rules.txt.in'))
    return {str(p.relative_to(ROOT)): file_digest(p.read_bytes()) for p in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--expected-candidate-digest', required=True)
    parser.add_argument('--observation-source', type=Path, required=True)
    parser.add_argument('--expected-state-sha256', required=True)
    parser.add_argument('--expected-ui-sha256', required=True)
    parser.add_argument('--command-line-tools', type=Path, required=True)
    parser.add_argument('--java-home', type=Path, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--target-kind', choices=('emulator', 'physical'), required=True)
    signing = parser.add_mutually_exclusive_group(required=True)
    signing.add_argument('--community-debug-signing', action='store_true')
    signing.add_argument('--signing-config', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--build-only', action='store_true', help='compile only; target execution remains not_run')
    args = parser.parse_args()
    args.output = args.output.resolve()
    protected = [ROOT, args.candidate.resolve(), args.observation_source.resolve(), args.command_line_tools.resolve(), args.java_home.resolve()]
    if any(args.output.is_relative_to(p) or p.is_relative_to(args.output) for p in protected):
        parser.error('output overlaps a protected input')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'L05 three actual UIAbility background/resume cycles and shared owner: exact public C HAR + public development observation sources',
              'candidate': args.expected_candidate_digest, 'certifies_c07': False, 'certifies_l05': False,
              'compile': 'not_run', 'target_execution': 'not_run', 'native': 'not_run', 'ui': 'not_run', 'runtime_close': 'not_confirmed', 'cleanup': 'not_needed',
              'result': 'failed', 'limitations': ['C ordinary route only', 'API23 Arm64 emulator when selected; not physical-device evidence',
              'community signing is not production signing', 'source extension delivery is not a C10 candidate or published package',
              'three bounded background/resume cycles on one target; not long-lived background service or process survival guarantee',
              'one retained page/model; destruction/rotation/concurrent pages and all platform matrices remain outside this slice',
              'background publication after confirmed drain does not force an already queued native late-callback/close interleaving',
              'native close failure/retry injection and strict resource counters are not provided by the ordinary candidate']}
    session = None
    try:
        report['lab_inputs'] = code_snapshot()
        if platform.python_version() != (ROOT / '.python-version').read_text().strip():
            raise RuntimeError('use Lab pinned Python')
        errors = snapshot_errors(ROOT) + dependency_errors(ROOT)
        if errors:
            raise RuntimeError('; '.join(errors))
        delivery = source_delivery(args.observation_source, args.expected_state_sha256, args.expected_ui_sha256)
        candidate = verify_candidate(args.candidate, 'c', companion=False)
        if candidate['manifest']['candidate_digest'] != args.expected_candidate_digest:
            raise ValueError('candidate differs from independently trusted identity')
        report['source_delivery'] = delivery
        report['candidate_manifest_sha256'] = file_digest((args.candidate / 'candidate.json').read_bytes())
        report['producer'] = candidate['provenance']
        report['lab_head'] = __import__('subprocess').check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        report['lab_status'] = __import__('subprocess').check_output(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=ROOT, text=True)
        if report['lab_status'] and not args.build_only:
            raise ValueError('target execution requires a clean frozen Lab revision')
        if code_snapshot() != report['lab_inputs']:
            raise ValueError('Lab inputs changed during admission')
        session = BackgroundSession(args, candidate)
        session.verify_tools()
        report['target'] = session.verify_target()
        session.prepare()
        run_build(session, report)
        if not args.build_only:
            report['target_observations'] = run_target(session, report)
        session.verify_closure('after')
        if verify_candidate(args.candidate, 'c', companion=False)['manifest']['candidate_digest'] != args.expected_candidate_digest:
            raise ValueError('candidate changed during execution')
        if source_delivery(args.observation_source, args.expected_state_sha256, args.expected_ui_sha256) != delivery:
            raise ValueError('extension sources changed during execution')
        if code_snapshot() != report['lab_inputs']:
            raise ValueError('consumed Lab sources changed during execution')
        report['result'] = 'build_only' if args.build_only else 'passed'
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
        print(report['error'], file=sys.stderr)
    finally:
        if session is not None and session.device_started:
            report['cleanup'] = 'failed'
            try:
                session.stop()
                report['cleanup'] = 'passed'
            except Exception as error:
                report['cleanup_error'] = str(error)
                report['result'] = 'failed'
        write_json(args.output / 'report.json', report)
    print(json.dumps({k: report[k] for k in ('result', 'compile', 'target_execution', 'native', 'ui', 'runtime_close', 'cleanup')}))
    return 0 if report['result'] in ('passed', 'build_only') else 1


if __name__ == '__main__':
    raise SystemExit(main())
