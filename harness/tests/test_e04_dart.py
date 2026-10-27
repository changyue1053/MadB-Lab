"""Model-only E04 admission/evidence rejection tests; no SDK certification."""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import signal
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'harness'))
sys.path.insert(0, str(ROOT / 'scripts'))
from candidate import CandidateError, candidate_digest, file_digest
from e04_dart_candidate import (verify_install, verify_envelope, verify_provenance,
                                profile_v2_digest, composition_digest, inventory, verify_build_evidence)
from e04_dart_execution import (Commands, ExecutionFact, bind_sdk, install_dependency,
                                verify_dependencies, cleanup_private_images)
from e04_dart_observations import (CASE_IDS, CASE_NAMES, expected_rows, inspect_output,
                                   required_probes)
from e04_dart_reports import Reports, case_steps, failure_status, read_command_log
from l02_reports import CommandFailure, ObservationFailure, file_reference
from verify_e04_dart import bind_package_configuration


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


class OracleTests(unittest.TestCase):
    def output(self, name):
        return {'case': name, 'pid': 101, 'observations': expected_rows(name)}

    def inspect(self, value, name):
        return inspect_output(json.dumps(value), name, expected_pid=101)

    def test_fixed_values_and_jit_aot_obligations(self):
        for name in CASE_NAMES[:-1]:
            self.inspect(self.output(name), name)
            self.assertEqual(required_probes(name), (('jit', 'ordinary'), ('aot', 'ordinary')))
        self.assertEqual(expected_rows('values')[3]['sum'], 511)
        self.assertEqual(expected_rows('values')[4]['sum'], 16711680)
        self.assertEqual(len(required_probes('package')), 8)

    def test_wrong_sum_or_preservation_is_failure(self):
        for key, value in [('sum', 510), ('input_preserved', False), ('state', 'closing')]:
            row = self.output('values'); row['observations'][3][key] = value
            with self.assertRaises(ObservationFailure): self.inspect(row, 'values')

    def test_boolean_cannot_impersonate_numeric_observation(self):
        value = self.output('values'); value['observations'][0]['sum'] = False
        with self.assertRaises(ValueError): self.inspect(value, 'values')
        value = self.output('isolate'); value['observations'][-1]['errors'] = False
        with self.assertRaises(ValueError): self.inspect(value, 'isolate')

    def test_exact_pid_case_shape_and_complete_response_required(self):
        for mutate in (lambda row: row.update(pid=102), lambda row: row.update(case='close'),
                       lambda row: row.update(passed=True), lambda row: row.update(observations=[])):
            value = self.output('values'); mutate(value)
            with self.assertRaises(ValueError): self.inspect(value, 'values')
        with self.assertRaises(CandidateError):
            inspect_output(json.dumps(self.output('values')) + '\n{}', 'values', expected_pid=101)

    def test_closing_is_not_closed_and_receiver_kill_is_not_normal_exit(self):
        value = self.output('close'); value['observations'][1]['state'] = 'closing'
        with self.assertRaises(ObservationFailure): self.inspect(value, 'close')
        value = self.output('isolate'); value['observations'][-1]['normal'] = False
        with self.assertRaises(ObservationFailure): self.inspect(value, 'isolate')
        value['observations'].pop()
        with self.assertRaises(ValueError): self.inspect(value, 'isolate')

    def test_load_kind_not_any_exception_or_graph_claim(self):
        value = {'case': 'load', 'pid': 101, 'observations': [{'id': 'load', 'kind': 'digestMismatch',
                 'path': '/model/native.dylib', 'expected_digest': '1'*64, 'actual_digest': '2'*64}]}
        facts={'path':'/model/native.dylib','expected_digest':'1'*64,'actual_digest':'2'*64}
        inspect_output(json.dumps(value), 'load', expected_pid=101, load_kind='digestMismatch',load_facts=facts)
        with self.assertRaises(ObservationFailure):
            inspect_output(json.dumps(value),'load',expected_pid=101,load_kind='digestMismatch',load_facts=dict(facts,path='/other/native.dylib'))
        with self.assertRaises(ObservationFailure):
            inspect_output(json.dumps(value),'load',expected_pid=101,load_kind='digestMismatch',load_facts=dict(facts,actual_digest='3'*64))
        with self.assertRaises(ObservationFailure):
            inspect_output(json.dumps(value), 'load', expected_pid=101, load_kind='missingAsset')
        with self.assertRaises(ValueError):
            inspect_output(json.dumps(value), 'load', expected_pid=101, load_kind='imageGraphMismatch')

    def test_arbitrary_process_crash_is_error(self):
        for code, timeout, stderr, expected in [(2,False,'E04 assertion: wrong','failed'),
                (-11,False,'E04 assertion: wrong','error'),(2,True,'E04 assertion: wrong','error'),
                (3,False,'E04 unexpected: crash','error')]:
            failure = CommandFailure(Path('model-log'), {'exit_code': code, 'timeout': timeout, 'stderr': stderr})
            self.assertEqual(failure_status(failure), expected)


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='madb-e04-model-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = self.root / 'native'; self.native.mkdir()
        (self.native / 'bridge.dylib').write_bytes(b'model bridge, not Mach-O')
        (self.native / 'native.dylib').write_bytes(b'model native, not Mach-O')
        (self.native / 'identity.json').write_bytes(encoded({'schema': 'madb.native-identity/1',
            'bootstrap_version': 1, 'interface_digest': 'sha256:'+'a'*64, 'profile_digest': 'sha256:'+'b'*64}))
        self.install = {'bridge': 'bridge.dylib', 'native': 'native.dylib', 'identity': 'identity.json',
                        'files': [dict(row, sha256=row['sha256'][7:]) for row in inventory(self.native).values()]}
        self.save()

    def save(self):
        (self.native / 'install.json').write_bytes(encoded(self.install))

    def test_original_native_identity_is_preserved(self):
        result = verify_install(self.native)
        self.assertEqual(result['identity']['profile_digest'], 'sha256:'+'b'*64)
        self.assertEqual(len(result['files']), 3)

    def test_unknown_installer_field_and_duplicate_role_rejected(self):
        for update in ({'version': 1}, {'bridge': 'native.dylib'}, {'native': '../native.dylib'}):
            original = copy.deepcopy(self.install)
            self.install.update(update); self.save()
            with self.assertRaises(CandidateError): verify_install(self.native)
            self.install = original

    def test_missing_changed_extra_symlink_rejected(self):
        target = self.native / 'native.dylib'; original = target.read_bytes()
        target.write_bytes(b'changed')
        with self.assertRaises(CandidateError): verify_install(self.native)
        target.unlink()
        with self.assertRaises(CandidateError): verify_install(self.native)
        target.symlink_to(self.native / 'bridge.dylib')
        with self.assertRaises(CandidateError): verify_install(self.native)
        target.unlink(); target.write_bytes(original)
        (self.native / 'extra.dylib').write_bytes(b'extra')
        with self.assertRaises(CandidateError): verify_install(self.native)

    def test_duplicate_case_alias_and_noninteger_size_rejected(self):
        (self.native / 'BRIDGE.dylib').write_bytes(b'alias')
        with self.assertRaises(CandidateError): verify_install(self.native)
        (self.native / 'BRIDGE.dylib').unlink()
        self.install['files'][0]['size'] = True; self.save()
        with self.assertRaises(CandidateError): verify_install(self.native)

    def test_installed_digest_must_be_bare_sha256(self):
        self.install['files'][0]['sha256'] = 'sha256:' + self.install['files'][0]['sha256']; self.save()
        with self.assertRaises(CandidateError): verify_install(self.native)

    def test_clean_producer_not_inherited_from_old_provider(self):
        row = {'schema':'madb.native-provenance/1','producer_revision':'1'*40,
               'input_digest':'sha256:'+'2'*64,'tool_digest':'sha256:'+'3'*64}
        verify_provenance(row, '1'*40)
        for update in ({'provisional':True},{'producer_revision':'4'*40},{'unknown':True}):
            with self.assertRaises(CandidateError): verify_provenance(dict(row, **update), '1'*40)

    def envelope(self):
        files = list(inventory(self.native).values())
        return {'schema':'madb.candidate/1','candidate_digest':'sha256:'+'0'*64,
          'selector':{'route':'org.madb.dart.c-ffi','profile_id':'dart-c-ffi-sync-aarch64-apple-darwin',
                      'profile_digest':'sha256:'+'9'*64,'target':'aarch64-apple-darwin','direction':'consumer-to-provider'},
          'generation_id':'sha256:'+'1'*64,'contract_digest':'sha256:'+'2'*64,'policy_digest':'sha256:'+'3'*64,
          'lock_digest':'sha256:'+'4'*64,'manifest_path':'candidate.json','files':files,'dependencies':[],
          'public_symbols':['model-only'],'required_cases':list(CASE_IDS),
          'build_evidence':[dict(files[0],schema='madb.build-evidence/1')]}

    def write_envelope(self, manifest):
        manifest['candidate_digest'] = candidate_digest(manifest)
        (self.native/'candidate.json').write_bytes(encoded(manifest))
        return manifest['candidate_digest']

    def test_envelope_alone_is_not_full_execution_admission(self):
        manifest=self.envelope();digest=self.write_envelope(manifest)
        self.assertEqual(verify_envelope(self.native,digest),manifest)
        self.assertNotIn('contract.json',inventory(self.native))

    def test_rehashed_candidate_cannot_drop_required_cases(self):
        manifest=self.envelope();manifest['required_cases'].pop();digest=self.write_envelope(manifest)
        with self.assertRaises(CandidateError):verify_envelope(self.native,digest)

    def test_rehashed_candidate_cannot_hide_extra_file(self):
        manifest=self.envelope();digest=self.write_envelope(manifest)
        (self.native/'unlisted').write_bytes(b'x')
        with self.assertRaises(CandidateError):verify_envelope(self.native,digest)

    def test_fileref_schema_null_number_unknown_identity_rejected(self):
        for schema in (None, 1, '', 'bad schema', 'madb.report/1'):
            manifest=self.envelope();manifest['build_evidence'][0]['schema']=schema
            digest=self.write_envelope(manifest)
            with self.subTest(schema=schema), self.assertRaises(CandidateError):verify_envelope(self.native,digest)
            (self.native/'candidate.json').unlink()
        for schema in (None, 1, '', 'bad schema', 'x'*513):
            manifest=self.envelope();manifest['dependencies']=[dict(manifest['files'][0],schema=schema)]
            digest=self.write_envelope(manifest)
            with self.subTest(dependency_schema=schema), self.assertRaises(CandidateError):verify_envelope(self.native,digest)
            (self.native/'candidate.json').unlink()


class BuildEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='madb-e04-evidence-model-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.rows={};self.evidence={}
        self.manifest={'selector':{'target':'aarch64-apple-darwin','profile_digest':'sha256:'+'2'*64},
                       'generation_id':'sha256:'+'3'*64,'files':[],'dependencies':[],'build_evidence':[]}
        self.contract={'source_digest':'sha256:'+'4'*64}
        self.tool={'id':'e04-python','version':'3.14.4','sha256':'sha256:'+'5'*64}
        self.profile={'tools':[self.tool]}
        def write(name,data):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            row={'path':name,'sha256':file_digest(data),'size':len(data)};self.rows[name]=row;return row
        outputs=[]
        for name in ('native/bridge.dylib','native/install.json','lib/src/package_pins.dart'):
            write(name,b'model-output');outputs.append(write('build/'+name,b'model-output'))
        for phase in ('compile','link','run'):
            log=write('logs/'+phase+'.json',b'[]');write('build/'+phase+'.commands.json',b'[]')
            value={'schema':'madb.build-evidence/1','task_id':phase,'task_digest':'sha256:'+'6'*64,
                   'input_digest':self.contract['source_digest'],'profile_digest':self.manifest['selector']['profile_digest'],
                   'generation_id':self.manifest['generation_id'],'tool':self.tool.copy(),'phase':phase,
                   'target':'aarch64-apple-darwin','status':'passed','exit_code':0,
                   'outputs':copy.deepcopy(outputs) if phase=='link' else [],'logs':[log]}
            self.evidence[phase]=value
            row=write('evidence/'+phase+'.json',encoded(value))
            self.manifest['build_evidence'].append(dict(row,schema='madb.build-evidence/1'))
        self.manifest['files']=list(self.rows.values())

    def check(self):return verify_build_evidence(self.root,self.manifest,self.contract,self.profile)

    def replace(self,phase):
        path='evidence/'+phase+'.json';data=encoded(self.evidence[phase]);(self.root/path).write_bytes(data)
        pin={'path':path,'sha256':file_digest(data),'size':len(data)}
        self.manifest['files']=[pin if row['path']==path else row for row in self.manifest['files']]
        self.manifest['build_evidence']=[dict(pin,schema='madb.build-evidence/1') if row['path']==path else row for row in self.manifest['build_evidence']]

    def test_three_outer_phases_bind_complete_lineage(self):
        self.assertEqual(set(self.check()),{'compile','link','run'})
        for key,value in [('generation_id','sha256:'+'7'*64),('input_digest','sha256:'+'7'*64),
                          ('profile_digest','sha256:'+'7'*64),('target','other'),('status','failed'),('exit_code',True)]:
            original=copy.deepcopy(self.evidence['run']);self.evidence['run'][key]=value;self.replace('run')
            with self.subTest(key=key),self.assertRaises(CandidateError):self.check()
            self.evidence['run']=original;self.replace('run')

    def test_missing_run_duplicate_phase_and_wrong_tool_rejected(self):
        original=copy.deepcopy(self.manifest);self.manifest['build_evidence'].pop()
        with self.assertRaises(CandidateError):self.check()
        self.manifest=original;self.evidence['run']['phase']='link';self.replace('run')
        with self.assertRaises(CandidateError):self.check()
        self.evidence['run']['phase']='run';self.evidence['run']['tool']['sha256']='sha256:'+'8'*64;self.replace('run')
        with self.assertRaises(CandidateError):self.check()

    def test_unbound_log_or_linked_image_rejected(self):
        (self.root/'logs/run.json').write_bytes(b'changed')
        with self.assertRaises(CandidateError):self.check()
        (self.root/'logs/run.json').write_bytes(b'[]')
        self.evidence['link']['outputs'][0]['sha256']='sha256:'+'8'*64;self.replace('link')
        with self.assertRaises(CandidateError):self.check()


class PackageUriTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='madb-e04-import-model-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.project=self.root/'consumer';self.package=self.root/'package';self.cache=self.root/'ffi'
        for p in (self.project,self.package,self.cache): (p/'lib').mkdir(parents=True)
        (self.project/'.dart_tool').mkdir();self.path=self.project/'.dart_tool/package_config.json'
        self.installed=[{'name':'ffi','directory':str(self.cache)}]
        self.value={'configVersion':2,'packages':[{'name':name,'rootUri':p.as_uri()+'/','packageUri':'lib/'}
                    for name,p in [('madb_lab_e04_sync',self.project),('madb_dart_ffi',self.package),('ffi',self.cache)]]}

    def check(self):
        self.path.write_bytes(encoded(self.value));return bind_package_configuration(self.project,self.package,self.installed)

    def test_exact_real_lib_import_roots(self):self.check()

    def test_root_identity_cannot_mask_escaped_package_uri(self):
        for uri in ('file:///tmp/other/','/tmp/other/','../other/','lib/../lib/','lib%2f','',None):
            self.value['packages'][1]['packageUri']=uri
            with self.subTest(uri=uri),self.assertRaises(ValueError):self.check()

    def test_symlink_lib_and_root_alias_rejected(self):
        (self.package/'lib').rmdir();(self.package/'lib').symlink_to(self.cache/'lib',target_is_directory=True)
        with self.assertRaises(ValueError):self.check()
        (self.package/'lib').unlink();(self.package/'lib').mkdir()
        alias=self.root/'alias';alias.symlink_to(self.package,target_is_directory=True)
        self.value['packages'][1]['rootUri']=alias.as_uri()+'/'
        with self.assertRaises(ValueError):self.check()


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='madb-e04-runner-model-')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_actual_process_evidence_has_pid_exit_and_reaping(self):
        commands=Commands(self.root)
        row,ref=commands.run([sys.executable,'-I','-S','-c','import os;print(os.getpid())'],cwd=self.root)
        self.assertEqual(int(row['stdout']),row['pid']);self.assertTrue(row['reaped'])
        self.assertFalse(row['watchdog_killed']);self.assertEqual(row['exit_code'],0)
        self.assertTrue(row['pipes_drained']);self.assertTrue(row['capture_complete'])
        self.assertEqual(file_reference(self.root/ref['path'],self.root),ref)
        self.assertNotIn('DYLD_LIBRARY_PATH',row['environment'])
        self.assertEqual(row['environment']['PUB_CACHE'],str(self.root/'pub-cache'))

    def test_observer_error_cannot_mask_actual_log_write_failure(self):
        commands=Commands(self.root);write=Path.write_text
        def unavailable(path,text,*args,**kwargs):
            if path.parent==self.root/'logs':raise OSError('original log write failure')
            return write(path,text,*args,**kwargs)
        def broken_receiver(fact):raise ValueError('secondary observer failure')
        with patch.object(Path,'write_text',unavailable),self.assertRaisesRegex(OSError,'original log write') as caught:
            commands.run([sys.executable,'-I','-S','-c','pass'],cwd=self.root,
                         execution_token=object(),observe=broken_receiver)
        self.assertTrue(any('secondary observer failure' in note for note in caught.exception.__notes__))

    def test_sdk_archive_full_bytes_not_only_dart_executable(self):
        sdk=self.root/'sdk';(sdk/'bin').mkdir(parents=True);(sdk/'bin/dart').write_bytes(b'dart-model')
        (sdk/'snapshot').write_bytes(b'snapshot-model')
        archive=self.root/'sdk.zip'
        with zipfile.ZipFile(archive,'w') as target:
            target.writestr('dart-sdk/bin/dart',b'dart-model');target.writestr('dart-sdk/snapshot',b'snapshot-model')
        digest=file_digest(archive.read_bytes());bind_sdk(sdk,archive,digest)
        (sdk/'snapshot').write_bytes(b'changed')
        with self.assertRaises(CandidateError):bind_sdk(sdk,archive,digest)

    def archive(self, name, *, special=False):
        path=self.root/(name+'.tar.gz')
        with tarfile.open(path,'w:gz') as target:
            data=b'name: model\n';member=tarfile.TarInfo('pubspec.yaml');member.size=len(data)
            target.addfile(member,io.BytesIO(data))
            if special:
                member=tarfile.TarInfo('lib/link.dart');member.type=tarfile.SYMTYPE;member.linkname='/tmp/outside';target.addfile(member)
        return path

    def test_dependency_install_exact_archive_and_no_links(self):
        path=self.archive('ffi')
        result=install_dependency(self.root/'cache','ffi','2.2.0',path,file_digest(path.read_bytes()))
        self.assertEqual(inventory(Path(result['directory'])),result['files'])
        bad=self.archive('bad',special=True)
        with self.assertRaises(ValueError):install_dependency(self.root/'cache','bad','1.0.0',bad,file_digest(bad.read_bytes()))
        with self.assertRaises(CandidateError):install_dependency(self.root/'cache','wrong','1.0.0',path,'sha256:'+'1'*64)

    def test_missing_dependency_or_developer_cache_not_accepted(self):
        installed=[]
        for name,version in [('ffi','2.2.0'),('crypto','3.0.8')]:
            path=self.archive(name);installed.append(install_dependency(self.root/'cache',name,version,path,file_digest(path.read_bytes())))
        graph={'packages':[{'name':'madb_lab_e04_sync'},{'name':'madb_dart_ffi'},
                           {'name':'ffi','version':'2.2.0','source':'hosted'},
                           {'name':'crypto','version':'3.0.8','source':'hosted'}]}
        verify_dependencies(graph,installed)
        graph['packages'].append({'name':'developer_cache','version':'1.0.0','source':'path'})
        with self.assertRaises(ValueError):verify_dependencies(graph,installed)

    def test_file_cleanup_is_separate_and_does_not_follow_links(self):
        root=self.root/'tmp';root.mkdir();(root/'image').write_bytes(b'image')
        with self.assertRaises(ValueError):cleanup_private_images(root,process_cleanup_confirmed=False)
        self.assertTrue((root/'image').is_file())
        row=cleanup_private_images(root,process_cleanup_confirmed=True);self.assertEqual(row['after'],{})
        self.assertIn('not-native-resource-release-proof',row['scope'])
        (root/'escape').symlink_to(self.root/'elsewhere')
        with self.assertRaises(CandidateError):cleanup_private_images(root,process_cleanup_confirmed=True)

    def test_escaped_pipe_holder_has_bounded_drain_and_unconfirmed_cleanup(self):
        commands=Commands(self.root)
        code=('import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-I","-S","-c",'
              '"import time;time.sleep(1.5)"],start_new_session=True);print(p.pid,flush=True);time.sleep(10)')
        started=time.monotonic();child=None
        try:
            with self.assertRaises(CommandFailure) as caught:
                commands.run([sys.executable,'-I','-S','-c',code],cwd=self.root,timeout=0.15)
            row=caught.exception.value
            if row['stdout'].strip():child=int(row['stdout'].strip())
            self.assertLess(time.monotonic()-started,1.4)
            self.assertTrue(row['timeout']);self.assertTrue(row['reaped'])
            self.assertFalse(row['pipes_drained']);self.assertFalse(row['capture_complete'])
            self.assertEqual(row['process_cleanup'],'not-confirmed');self.assertFalse(commands.cleanup_confirmed)
        finally:
            if child is not None:
                try:os.kill(child,signal.SIGKILL)
                except ProcessLookupError:pass

    def test_output_capture_budget_is_enforced_without_unbounded_buffer(self):
        commands=Commands(self.root)
        with patch('e04_dart_execution.OUTPUT_LIMIT',1024),self.assertRaises(CommandFailure) as caught:
            commands.run([sys.executable,'-I','-S','-c','import sys;sys.stdout.write("x"*2048)'],cwd=self.root)
        row=caught.exception.value
        self.assertTrue(row['output_limit_exceeded']);self.assertFalse(row['capture_complete'])
        self.assertLessEqual(row['stdout_bytes']['size']+row['stderr_bytes']['size'],1024)


class ProfileLayerTests(unittest.TestCase):
    def profile(self):
        return {'schema':'madb.profile/2','id':'dart-profile-model','route':'org.madb.dart.c-ffi',
          'provider':{'language':'c','runtime':'native'},'consumer':{'language':'dart','runtime':'dart-native'},
          'direction':'consumer-to-provider','target':'aarch64-apple-darwin','abi':'c','artifact_kind':'source',
          'build_system':'dart-pub','deployment_target':'14.0','tools':[{'id':'model-tool'}],
          'sdk':{'path':'sdk.json','sha256':'sha256:'+'1'*64,'size':1,'schema':'model-only/1'},
          'macros':[],'required_features':['core.extension-composition@1'],'supported_features':['core.extension-composition@1'],
          'restrictions':[],'defaults':{'values':{},'origin':{'model_only':True}},'backend_config':None,
          'composition':{'id':'model-composition','semantic_digest':'sha256:'+'2'*64,
                         'file':{'path':'composition.json','sha256':'sha256:'+'3'*64,'size':1,'schema':'madb.composition/1'}}}

    def test_profile_v2_composition_semantics_and_raw_bytes_are_distinct(self):
        profile=self.profile();before=profile_v2_digest(profile)
        profile['composition']['file']['sha256']='sha256:'+'4'*64
        self.assertEqual(profile_v2_digest(profile),before)
        profile['composition']['semantic_digest']='sha256:'+'5'*64
        self.assertNotEqual(profile_v2_digest(profile),before)
        profile['schema']='madb.profile/1'
        with self.assertRaises(CandidateError):profile_v2_digest(profile)

    def test_duplicate_features_and_unknown_profile_fields_rejected(self):
        for change in (lambda p:p['required_features'].append('core.extension-composition@1'),
                       lambda p:p.update(unknown=True),lambda p:p['composition'].update(unknown=True)):
            profile=self.profile();change(profile)
            with self.assertRaises(CandidateError):profile_v2_digest(profile)

    def test_composition_duplicate_responsibilities_not_deduplicated(self):
        value={'schema':'madb.composition/1','id':'model-only','recipe':'model-only','selection':{},
               'packages':[],'components':[],'assets':[],'dependencies':[],
               'responsibilities':[{'boundary':'model','subject':{'kind':'output','path':'a'},'stage':'physical-assembly',
                                    'scope':{'kind':'model','anchor':{'kind':'output','path':'a'},'layer':'native'},
                                    'owner':{'kind':'component','id':'org.model/read'}}]}
        composition_digest(value)
        value['responsibilities'].append(copy.deepcopy(value['responsibilities'][0]))
        with self.assertRaises(CandidateError):composition_digest(value)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='madb-e04-report-model-')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.output=self.root/'output';self.output.mkdir()
        fixture=self.root/'model.dart';fixture.write_bytes(b'// model-only, no SDK')
        folder=self.root/'cases/e04/dart-sync';folder.mkdir(parents=True)
        for name in CASE_NAMES:
            case={'schema':'madb.case/1','id':'e04.dart-sync.'+name,'kind':'template','selector':None,
                  'problem_ids':['VERIFY-001'],'source_ids':[],'requires':{'features':[],'environment':[]},
                  'fixture':{**file_reference(fixture,self.root),'schema':'madb.lab-source/1'},
                  'setup':[],'steps':case_steps(name),'assertions':[{'model_only':True}],
                  'expected_result':{'kind':'success'},'cleanup':[{'model_only':True}],
                  'timeout_policy':{'timeout_ms':len(required_probes(name))*60000,'on_timeout':'error','recovery':'isolate'}}
            (folder/(name+'.json')).write_bytes(encoded(case))
        candidate={'manifest':{'required_cases':list(CASE_IDS),'candidate_digest':'sha256:'+'1'*64,
                               'selector':{'profile_id':'model-only','profile_digest':'sha256:'+'2'*64,
                                           'route':'org.madb.dart.c-ffi','target':'aarch64-apple-darwin',
                                           'direction':'consumer-to-provider'}},
                   'provenance':{'input_digest':'sha256:'+'3'*64,'tool_digest':'sha256:'+'4'*64}}
        self.dart=self.root/'dart';self.dart.write_bytes(b'model-only-dart')
        self.aot=self.root/'aot';self.aot.write_bytes(b'model-only-aot')
        self.config=self.root/'config.json';self.config.write_bytes(b'{}')
        environment=[{'id':'dart','version':'model-only','sha256':file_digest(self.dart.read_bytes()),
                      'host':'model-only','target':'model-only','source':'model-only fixture; no Dart execution','arguments':[]}]
        self.reports=Reports(self.root,self.output,candidate,'5'*40,environment)
        self.jit=[str(self.dart),'--packages='+str(self.config),str(fixture)]
        self.reports.bind_commands(self.jit,[str(self.aot)])

    def test_cannot_skip_jit_or_claim_empty_suite_passed(self):
        with self.assertRaises(ValueError):self.reports.begin('values','aot','ordinary',[str(self.aot),'values','/model-native'])
        with self.assertRaises(ValueError):self.reports.verify()

    def actual_reports(self):
        # An actual Python fixture exercises the observer seam, never the Dart SDK.
        rows=expected_rows('values')
        self.dart.write_text('#!'+sys.executable+'\nimport json,os\n'
                             'print(json.dumps({"case":"values","pid":os.getpid(),"observations":'
                             +repr(rows)+'}))\n')
        self.dart.chmod(0o755)
        environment=copy.deepcopy(self.reports.environment)
        environment[0]['sha256']=file_digest(self.dart.read_bytes())
        reports=Reports(self.root,self.output,self.reports.candidate,'5'*40,environment)
        reports.bind_commands(self.jit,[str(self.aot)])
        command=self.jit+['values','/model-native']
        reports.begin('values','jit','ordinary',command)
        commands=Commands(self.output)
        return reports,commands,command,rows

    def test_actual_command_log_passes_strict_reader_and_report_completion(self):
        reports,commands,command,rows=self.actual_reports()
        row,reference=commands.run(command,cwd=self.output,**reports.execution_binding())
        decoded=read_command_log(self.output/reference['path'])
        self.assertEqual(decoded,row)
        self.assertEqual(decoded['drain_timeout_ms'],250)
        self.assertEqual(decoded['reap_timeout_ms'],250)
        self.assertNotIn('drain_timeout_seconds',decoded)
        self.assertNotIn('reap_timeout_seconds',decoded)
        self.assertEqual(reports.complete(reference),rows)
        self.assertEqual([fact.reference() for fact in reports.attempts['values']],[reference])
        self.assertEqual(len(reports.records['values']),1)

    def test_fractional_private_timeout_log_is_still_rejected(self):
        path=self.output/'legacy-fractional-log.json'
        path.write_bytes(encoded({'drain_timeout_seconds':0.25,'reap_timeout_seconds':0.25}))
        with self.assertRaisesRegex(CandidateError,'non-integer JSON number: 0.25'):
            read_command_log(path)

    def failure_report(self,reports,commands,error):
        local={'result':'error','logs':commands.logs,'error':str(error)}
        (self.output/'report.json').write_bytes(encoded(local))
        ref=reports.write(local,error)
        return json.loads((self.output/ref['path']).read_bytes())

    def test_actual_bad_log_keeps_target_run_fact_without_accepting_observation(self):
        reports,commands,command,_=self.actual_reports();write=Path.write_text
        def fractional(path,text,*args,**kwargs):
            if path.parent==self.output/'logs':
                value=json.loads(text);value['drain_timeout_seconds']=0.25;text=json.dumps(value)
            return write(path,text,*args,**kwargs)
        with patch.object(Path,'write_text',fractional):
            row,ref=commands.run(command,cwd=self.output,**reports.execution_binding())
        with self.assertRaises(CandidateError) as caught:reports.complete(ref)
        self.assertEqual(reports.records['values'],[])
        public=self.failure_report(reports,commands,caught.exception)
        result=public['results'][0]
        self.assertEqual((result['status'],result['evidence_level'],result['actual']['kind']),('error','target-run','unavailable'))
        self.assertEqual(result['duration_ms'],row['duration_ns']//1000000)
        facts=json.loads((self.output/'execution-facts.json').read_bytes())['observations']
        self.assertEqual((facts[0]['pid'],facts[0]['argv']),(row['pid'],command))
        self.assertEqual(facts[0]['log'],ref)

    def test_actual_log_write_failure_retains_process_facts(self):
        reports,commands,command,_=self.actual_reports();write=Path.write_text
        def unavailable(path,text,*args,**kwargs):
            if path.parent==self.output/'logs':raise OSError('model log storage unavailable')
            return write(path,text,*args,**kwargs)
        with patch.object(Path,'write_text',unavailable),self.assertRaisesRegex(OSError,'log storage') as caught:
            commands.run(command,cwd=self.output,**reports.execution_binding())
        self.assertEqual(commands.logs,[])
        public=self.failure_report(reports,commands,caught.exception)
        self.assertEqual(public['results'][0]['evidence_level'],'target-run')
        fact=json.loads((self.output/'execution-facts.json').read_bytes())['observations'][0]
        self.assertGreater(fact['pid'],0);self.assertIsNone(fact['log']);self.assertTrue(fact['reaped'])
        self.assertEqual(fact['argv'],command)

    def test_spawn_failure_cannot_reuse_previous_same_command_facts(self):
        reports,commands,command,_=self.actual_reports()
        commands.run(command,cwd=self.output)  # Prior real command has no selected invocation token.
        self.dart.unlink()
        with self.assertRaises(FileNotFoundError) as caught:
            commands.run(command,cwd=self.output,**reports.execution_binding())
        self.assertEqual(reports.attempts['values'],[])
        public=self.failure_report(reports,commands,caught.exception)
        result=public['results'][0]
        self.assertEqual((result['evidence_level'],result['actual']['kind']),('static','not-run'))
        self.assertFalse((self.output/'execution-facts.json').exists())

    def test_old_same_argv_fact_and_duplicate_token_are_rejected(self):
        reports,commands,command,_=self.actual_reports();binding=reports.execution_binding()
        _,ref=commands.run(command,cwd=self.output,**binding)
        fact=reports.attempts['values'][0]
        with self.assertRaises(ValueError):reports.note_execution(fact)
        with patch('e04_dart_execution.subprocess.Popen') as spawn,self.assertRaises(ValueError):
            commands.run(command,cwd=self.output,**binding)
        spawn.assert_not_called()
        other=Reports(self.root,self.output,reports.candidate,'5'*40,reports.environment)
        other.bind_commands(self.jit,[str(self.aot)]);other.begin('values','jit','ordinary',command)
        with self.assertRaises(ValueError):other.note_execution(fact)
        self.assertEqual(other.attempts['values'],[])
        reports.complete(ref)

    def test_changed_log_does_not_become_a_valid_error_attachment(self):
        reports,commands,command,_=self.actual_reports()
        _,ref=commands.run(command,cwd=self.output,**reports.execution_binding())
        (self.output/ref['path']).write_bytes(b'changed after actual execution')
        with self.assertRaises(ValueError) as caught:reports.complete(ref)
        public=self.failure_report(reports,commands,caught.exception)
        self.assertNotIn(ref,public['results'][0]['attachments'])
        fact=json.loads((self.output/'execution-facts.json').read_bytes())['observations'][0]
        self.assertIsNone(fact['log']);self.assertGreater(fact['pid'],0)

    def test_log_pid_must_match_actual_execution_fact(self):
        reports,commands,command,_=self.actual_reports();write=Path.write_text
        def changed(path,text,*args,**kwargs):
            if path.parent==self.output/'logs':
                value=json.loads(text);value['pid']+=1;text=json.dumps(value)
            return write(path,text,*args,**kwargs)
        with patch.object(Path,'write_text',changed):
            _,ref=commands.run(command,cwd=self.output,**reports.execution_binding())
        with self.assertRaisesRegex(ValueError,'actual process observation'):reports.complete(ref)
        self.assertEqual(reports.records['values'],[])

    def test_log_cleanup_must_match_actual_execution_fact(self):
        reports,commands,command,_=self.actual_reports();write=Path.write_text
        def changed(path,text,*args,**kwargs):
            if path.parent==self.output/'logs':
                value=json.loads(text);value['pipes_drained']=False;text=json.dumps(value)
            return write(path,text,*args,**kwargs)
        with patch.object(Path,'write_text',changed):
            _,ref=commands.run(command,cwd=self.output,**reports.execution_binding())
        with self.assertRaisesRegex(ValueError,'actual process cleanup observation'):reports.complete(ref)
        self.assertEqual(reports.records['values'],[])

    def note_model_execution(self,path):
        # Explicit synthetic process facts for report-model tests only.
        raw=json.loads(path.read_bytes());ref=file_reference(path,self.output)
        cleanup=tuple((key,raw.get(key,False)) for key in ('timeout','watchdog_killed','pipes_drained',
                      'capture_complete','output_limit_exceeded','process_cleanup'))
        self.reports.note_execution(ExecutionFact(self.reports.active_token,tuple(raw['argv']),raw['pid'],
            raw['duration_ns'],raw['exit_code'],raw['reaped'],cleanup,
            tuple(ref[key] for key in ('path','sha256','size'))))

    def test_actual_pid_and_reaped_process_required(self):
        command=self.jit+['values','/model-native'];self.reports.begin('values','jit','ordinary',command)
        path=self.output/'log.json';path.write_bytes(encoded({'argv':command,'pid':101,'duration_ns':1,'timeout':False,'exit_code':0,
          'reaped':False,'watchdog_killed':False,'stdout':json.dumps({'case':'values','pid':101,'observations':expected_rows('values')})}))
        self.note_model_execution(path)
        with self.assertRaises(ValueError):self.reports.complete(file_reference(path,self.output))

    def test_success_marker_cannot_replace_actual_values(self):
        command=self.jit+['values','/model-native'];self.reports.begin('values','jit','ordinary',command)
        path=self.output/'log.json';path.write_bytes(encoded({'argv':command,'pid':101,'duration_ns':1,'timeout':False,'exit_code':0,
          'reaped':True,'watchdog_killed':False,'stdout':'{"passed":true}'}))
        self.note_model_execution(path)
        with self.assertRaises(ValueError):self.reports.complete(file_reference(path,self.output))

    def test_aot_cannot_be_reported_as_jit(self):
        with self.assertRaises(ValueError):
            self.reports.begin('values','jit','ordinary',[str(self.aot),'values','/model-native'])

    def test_unreaped_started_target_remains_an_actual_attempt(self):
        command=self.jit+['values','/model-native'];self.reports.begin('values','jit','ordinary',command)
        path=self.output/'unreaped.json';path.write_bytes(encoded({'argv':command,'pid':101,'duration_ns':1,
            'timeout':True,'exit_code':None,'reaped':False,'watchdog_killed':True,
            'pipes_drained':False,'capture_complete':False,'output_limit_exceeded':False,
            'process_cleanup':'not-confirmed','stdout':''}))
        self.note_model_execution(path)
        self.reports.note_attempt(file_reference(path,self.output))
        self.assertEqual(len(self.reports.attempts['values']),1)
        with self.assertRaises(ValueError):self.reports.verify()

    def complete_model(self):
        # Synthetic records exercise the report validator only, never SDK behavior.
        for name in CASE_NAMES:
            for mode,variant in required_probes(name):
                command=(self.jit if mode=='jit' else [str(self.aot)])+[name,'/model-native']
                self.reports.begin(name,mode,variant,command)
                facts=None;kind=None
                if name=='package':
                    kind={'ordinary':'success','missing-native':'missingAsset','changed-native':'digestMismatch','symlink-native':'pathViolation'}[variant]
                    facts={'path':'/model-native/native.dylib','expected_digest':'1'*64 if variant=='changed-native' else None,
                           'actual_digest':'2'*64 if variant=='changed-native' else None}
                    rows=[{'id':'load','kind':'success','sum':3}] if kind=='success' else [{'id':'load','kind':kind,**facts}]
                else:rows=expected_rows(name)
                path=self.output/f'{name}-{mode}-{variant}.json'
                path.write_bytes(encoded({'model_only':True,'argv':command,'pid':101,'duration_ns':1,'timeout':False,'exit_code':0,
                    'reaped':True,'watchdog_killed':False,'pipes_drained':True,'capture_complete':True,
                    'output_limit_exceeded':False,'process_cleanup':'leader-reaped-pipes-drained',
                    'stdout':json.dumps({'case':'load' if name=='package' else name,
                                                                            'pid':101,'observations':rows})}))
                self.note_model_execution(path)
                self.reports.complete(file_reference(path,self.output),load_kind=kind,load_facts=facts)

    def test_complete_model_requires_all_sixteen_invocations_and_preserved_commands(self):
        self.complete_model();self.reports.verify()
        self.assertEqual(sum(len(rows) for rows in self.reports.records.values()),16)
        self.config.write_bytes(b'{"changed":true}')
        with self.assertRaises(ValueError):self.reports.verify()

    def test_duplicate_actual_attempt_cannot_be_hidden_by_complete_records(self):
        self.complete_model();self.reports.attempts['values'].append(self.reports.attempts['values'][0])
        with self.assertRaises(ValueError):self.reports.verify()

    def test_model_report_uses_five_existing_case_results(self):
        self.complete_model()
        local={'result':'passed','model_only':True,'logs':[], 'file_cleanup':{'after':{}}}
        (self.output/'report.json').write_bytes(encoded(local))
        ref=self.reports.write(local)
        public=json.loads((self.output/ref['path']).read_bytes())
        self.assertEqual(public['schema'],'madb.report/1')
        self.assertEqual([row['case_id'] for row in public['results']],list(CASE_IDS))
        self.assertTrue(all(row['cleanup']=='complete' for row in public['results']))


if __name__=='__main__':unittest.main()
