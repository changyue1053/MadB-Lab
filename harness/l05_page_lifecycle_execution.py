"""L05 independent page destruction/new-instance consumer of the public ordinary C HAR."""
import json
import shutil
import tarfile
import time
import zipfile
from pathlib import Path

from candidate import CandidateError, file_digest, read_json
from c07_candidate import native_inventory
from c07_contract import SOURCE as C07_SOURCE
from c07_execution import ExecutionError, write_json, ref
from l05_execution import L05Session, source_delivery
from l05_page_lifecycle_observations import parse, find_node, click_center, UI_EXPECTED

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'consumers/arkts/l05_page_lifecycle'
BUNDLE = 'com.madb.l05lifecycle'


class LifecycleSession(L05Session):
    def __init__(self, args, candidate):
        super().__init__(args, candidate)
        self.nonce = self.nonce.replace('l05-', 'l05-life-', 1)
        self.runtime_close_confirmed = False
        self.native_started = False
        self.ui_started = False

    def prepare(self):
        # Reuse the Lab's fixed ordinary HAP shell and public HAR installer recipe.
        shutil.copytree(C07_SOURCE / 'hap-template', self.root, dirs_exist_ok=True)
        app = read_json(self.root / 'AppScope/app.json5')
        app['app']['bundleName'] = BUNDLE
        (self.root / 'AppScope/app.json5').write_text(json.dumps(app, indent=2) + '\n')
        for package in ('hvigor', 'hvigor-ohos-plugin'):
            path = self.root / 'tool-node-modules/@ohos' / package
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(self.toolkit / 'hvigor' / package, target_is_directory=True)
        (self.root / 'local.properties').write_text('sdk.dir=' + str(self.sdk) + '\n')
        target = self.root / 'entry/src/main/ets'
        module = self.candidate['module']
        for path in SOURCE.iterdir():
            if not (path.name.endswith('.ets') or path.name.endswith('.ets.in')):
                continue
            name = path.name.removesuffix('.in')
            destination = target / ('pages/' + name if name in ('Index.ets', 'Away.ets') else name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(path.read_text().replace('@MADB_PUBLIC_MODULE@', json.dumps(module)))
        for name in ('StateObservation.ets', 'ArkUIStateModel.ets'):
            shutil.copyfile(self.args.observation_source / name, target / name)
        (target / 'Boundary.ets').write_text('export { Engine, Snapshot, Subscription } from ' + json.dumps(module) + ';\n')
        (target / 'ProbeConfig.ets').write_text('export const PROBE_NONCE: string = ' + json.dumps(self.nonce) + ';\n')
        ability = (target / 'EntryAbility.ets').read_text().replace('MadBC07Probe', 'MadBL05Lifecycle').replace('PROBE_FAILED', 'L05_LIFECYCLE_FAILED')
        (target / 'EntryAbility.ets').write_text(ability)
        (self.root / 'entry/src/main/resources/base/profile/main_pages.json').write_text(json.dumps({'src': ['pages/Index', 'pages/Away']}))
        (self.root / 'vendor').mkdir()
        archive = self.root / 'vendor' / (module + '.har')
        shutil.copyfile(self.candidate['root'] / self.candidate['har'], archive)
        write_json(self.root / 'entry/oh-package.json5', {'name': 'entry', 'version': '1.0.0', 'dependencies': {module: 'file:../vendor/' + archive.name}})
        self.namecache = self.args.output / (self.nonce + '-namecache.json')
        rules = (C07_SOURCE / 'obfuscation-rules.txt.in').read_text().replace('@NAMECACHE@', str(self.namecache))
        (self.root / 'entry/obfuscation-rules.txt').write_text(rules + '\n-keep-file-name\nAway\n')
        if self.args.signing_config:
            self.environment['MADB_SIGN_CONFIG'] = str(self.args.signing_config.resolve(strict=True))
        else:
            self.run('community-debug-signing', ['/bin/bash', '-c', 'set -euo pipefail; source "$1"; ohos_sign_material "$2" "$3" ""',
                'l05-lifecycle-sign', C07_SOURCE / 'prepare_debug_signing.sh', self.root / '.signing', BUNDLE], 90, extra_env={
                    'SIGN_LIB': str(self.sdk / 'openharmony/toolchains/lib'), 'JAVA_BIN': str(self.jdk / 'bin'),
                    'NODE': str(self.node), 'MADB_LAB_PYTHON': __import__('sys').executable,
                    'DECIPHER': str(self.toolkit / 'hvigor/hvigor-ohos-plugin/src/utils/decipher-util.js')})
        self.run('dependencies', [self.ohpm, 'install', '--all', '--cache', self.root / 'ohpm-cache'], 120)
        installed = self.root / 'entry/oh_modules' / module
        for name, content in self.candidate['har_members'].items():
            if (installed / name.removeprefix('package/')).read_bytes() != content:
                raise CandidateError('ArtifactMismatch', 'installed HAR changed: ' + name)
        self.inspect_native()

    def build(self):
        sources = sorted({p for base in ('AppScope', 'hvigor', 'entry/src') for p in (self.root / base).rglob('*') if p.is_file()} |
            {self.root / name for name in ('build-profile.json5', 'oh-package.json5', 'hvigorfile.ts', 'entry/build-profile.json5',
             'entry/oh-package.json5', 'entry/oh-package-lock.json5', 'entry/hvigorfile.ts', 'entry/obfuscation-rules.txt')})
        source_tar = self.args.output / (self.nonce + '-sources.tar')
        with tarfile.open(source_tar, 'x') as archive:
            for path in sources:
                archive.add(path, arcname=path.relative_to(self.root), recursive=False)
        self.run('assemble-release-hap', [self.node, self.hvigor, 'assembleHap', '--mode', 'module', '-p', 'product=default', '-p', 'buildMode=release', '--no-daemon'], 180)
        self.hap = self.args.output / (self.nonce + '.hap')
        self.hap.write_bytes((self.root / 'entry/build/default/outputs/default/entry-default-signed.hap').read_bytes())
        with zipfile.ZipFile(self.hap) as archive:
            if len(archive.namelist()) != len(set(archive.namelist())):
                raise CandidateError('ArtifactMismatch', 'duplicate HAP member')
            members = {n: archive.read(n) for n in archive.namelist() if not n.endswith('/')}
        app = json.loads(members['module.json'])['app']
        expected = {'compileSdkVersion': '26.0.0.105', 'minAPIVersion': 60100023,
                    'targetAPIVersion': 260000026, 'apiReleaseType': 'Release', 'buildMode': 'release', 'bundleName': BUNDLE}
        if any(app.get(k) != v for k, v in expected.items()):
            raise CandidateError('ProfileMismatch', 'HAP profile differs')
        if native_inventory(members) != {n.removeprefix('package/'): data for n, data in self.candidate['native_members'].items()}:
            raise CandidateError('ArtifactMismatch', 'HAP native closure differs from frozen HAR')
        if not self.namecache.is_file() or not self.namecache.stat().st_size:
            raise ExecutionError('missing obfuscation namecache')
        write_json(self.args.output / 'build.json', {'candidate_digest': self.candidate['manifest']['candidate_digest'],
            'hap': ref(self.hap, self.args.output), 'source_archive': ref(source_tar, self.args.output),
            'source_inputs': [ref(p, self.root) for p in sources], 'app': app, 'namecache': ref(self.namecache, self.args.output),
            'members': [{'path': n, 'size': len(data), 'sha256': file_digest(data)} for n, data in sorted(members.items())],
            'signing': 'explicit config' if self.args.signing_config else 'SDK public community debug; not production'})

    def observation(self, *, complete=False):
        pid = self.hdc('probe-pid', 'shell', 'pidof', BUNDLE, expected=None)['stdout'].strip()
        raw = self.hdc('probe-hilog', 'shell', 'hilog', '-x', '-T', 'MadBL05Lifecycle')['stdout']
        value = parse(raw, nonce=self.nonce, pid=pid, complete=complete)
        write_json(self.args.output / ('observation-' + str(time.time_ns()) + '.json'), value)
        if value['errors']:
            raise ExecutionError('L05 lifecycle assertions/log binding failed: ' + repr(value['errors']))
        return value

    def layout(self):
        number = len(self.ui_steps)
        remote = '/data/local/tmp/' + self.nonce + '-' + str(number) + '.json'
        self.hdc('ui-dump', 'shell', 'uitest', 'dumpLayout', '-b', BUNDLE, '-p', remote)
        try:
            raw = self.hdc('ui-read', 'shell', 'cat', remote)['stdout']
        finally:
            self.hdc('ui-remove', 'shell', 'rm', '-f', remote)
        layout = json.loads(raw)
        path = self.args.output / ('layout-' + str(number) + '.json')
        write_json(path, layout)
        self.ui_steps.append({'action': 'layout', 'file': path.name, 'sha256': file_digest(path.read_bytes())})
        return layout

    def assert_phase(self, phase):
        # Every independently specified visible field is checked on the target,
        # not inferred from log success or a previously captured screen.
        for identity, expected in UI_EXPECTED[phase].items():
            layout = self.wait_text(identity, expected)
        return layout

    def execute(self):
        before = self.hdc('own-pid-before', 'shell', 'pidof', BUNDLE, expected=None)['stdout'].strip()
        installed = self.hdc('own-package-before', 'shell', 'bm', 'dump', '-n', BUNDLE, expected=None)
        write_json(self.args.output / 'device-before.json', {'own_bundle': BUNDLE, 'pid': before, 'target': self.args.target,
                   'package_query': installed})
        if before:
            raise ExecutionError('refusing to replace an already running L05 lifecycle probe')
        self.device_started = True
        result = self.hdc('install', 'install', '-r', self.hap, timeout=90)
        if 'install bundle successfully.' not in result['stdout']:
            raise ExecutionError('device did not confirm installing the lifecycle bundle')
        result = self.hdc('start', 'shell', 'aa', 'start', '-a', 'EntryAbility', '-b', BUNDLE)
        if 'start ability successfully.' not in result['stdout']:
            raise ExecutionError('device did not confirm starting the lifecycle ability')
        self.native_started = True
        deadline = time.monotonic() + 15
        while not self.hdc('wait-own-pid', 'shell', 'pidof', BUNDLE, expected=None)['stdout'].strip():
            if time.monotonic() >= deadline:
                raise ExecutionError('lifecycle process did not start')
            time.sleep(0.2)
        self.ui_started = True
        for page_id in (1, 2, 3):
            layout = self.assert_phase('PAGE_READY_' + str(page_id))
            self.click(layout, 'l05-life-publish')
            layout = self.assert_phase('PAGE_PUBLISHED_' + str(page_id))
            self.click(layout, 'l05-life-destroy')
            layout = self.assert_phase('AWAY_READY_' + str(page_id))
            self.click(layout, 'l05-life-after-publish')
            layout = self.assert_phase('AWAY_PUBLISHED_' + str(page_id))
            self.click(layout, 'l05-life-new-page' if page_id < 3 else 'l05-life-finish')
        self.assert_phase('FINISHED')
        result = self.observation(complete=True)
        self.native_passed = True
        self.runtime_close_confirmed = True
        self.ui_passed = True
        write_json(self.args.output / 'ui-observations.json', {'steps': self.ui_steps, 'result': result})
        return result

    def stop(self):
        if not self.device_started:
            return
        stopped = self.hdc('stop-own-probe', 'shell', 'aa', 'force-stop', BUNDLE)
        if 'force stop process successfully.' not in stopped['stdout']:
            raise ExecutionError('device did not confirm stopping the lifecycle bundle')
        pid = self.hdc('own-pid-after', 'shell', 'pidof', BUNDLE, expected=None)['stdout'].strip()
        if pid:
            raise ExecutionError('lifecycle probe remains after cleanup')
        uninstalled = self.hdc('uninstall-own-probe', 'uninstall', BUNDLE, timeout=60)
        if 'uninstall bundle successfully.' not in uninstalled['stdout']:
            raise ExecutionError('device did not confirm uninstalling the lifecycle bundle')
        installed = self.hdc('own-package-after', 'shell', 'bm', 'dump', '-n', BUNDLE, expected=None)
        write_json(self.args.output / 'device-after.json', {'own_bundle': BUNDLE, 'pid': pid, 'uninstalled': True,
                   'package_query': installed, 'scope': 'only this lifecycle bundle stopped/uninstalled; other apps and hdc server untouched'})
        self.stopped = True
