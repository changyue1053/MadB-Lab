"""Checks of independent value-case evidence rules; no SDK runtime claim."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('verify_l02_values', Path(__file__).with_name('verify_l02_values.py'))
values = importlib.util.module_from_spec(spec); spec.loader.exec_module(values)
import l02_values_reports as records
from candidate import file_digest
from check_cases import errors as case_errors
from l02_reports import CommandFailure, ObservationFailure


class OutputChecks(unittest.TestCase):
    identity = {'interface_digest': 'sha256:' + '1'*64, 'profile_digest': 'sha256:' + '2'*64}
    library = Path('/private/tmp/independent-values-test-library')

    def output(self, group='author-0', mode='values'):
        terminal = {'result': 'passed', 'mode': mode, 'author': values.GROUPS.index(group), 'checks': 123,
                    'helper_vectors': (24 if group in ('author-1','author-2','author-3') else 22) if mode == 'helper-protocol' else 0,
                    'scope': 'helper-only' if mode == 'helper-protocol' else 'native-sdk'}
        binding = {'event': 'binding', 'image': str(self.library), 'identity': '1'*64 + '2'*64, 'pid': 123}
        return [terminal] if mode == 'helper-protocol' else [binding, terminal]

    def inspect(self, rows, group='author-0', mode='values'):
        return values.inspect_output('\n'.join(json.dumps(x) for x in rows), group, mode, self.library, self.identity)

    def test_all_native_and_helper_scope_rows(self):
        for group in values.GROUPS:
            mode = 'output-capacity' if group == 'aux-grow' else 'unwind' if group == 'aux-panic' else 'values'
            self.inspect(self.output(group,mode),group,mode)
            if group.startswith('author-'): self.inspect(self.output(group,'helper-protocol'),group,'helper-protocol')

    def test_incomplete_and_wrong_types_are_errors(self):
        rows = self.output()
        for row_index in (0,1):
            for key in rows[row_index]:
                changed=copy.deepcopy(rows);del changed[row_index][key]
                with self.subTest(row=row_index,key=key),self.assertRaises(ValueError) as caught:self.inspect(changed)
                self.assertNotIsInstance(caught.exception,ObservationFailure)
        for index,key,value in ((0,'pid',True),(0,'image',None),(0,'identity',None),(0,'event',None),
                                (1,'author',True),(1,'checks',True),(1,'helper_vectors',True),
                                (1,'result',None),(1,'mode',None),(1,'scope',None)):
            changed=copy.deepcopy(rows);changed[index][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError) as caught:self.inspect(changed)
            self.assertNotIsInstance(caught.exception,ObservationFailure)
        for changed in ([],rows[:1],rows+[rows[-1]],['not-an-object',rows[-1]]):
            with self.assertRaises(ValueError):self.inspect(changed)

    def test_complete_contradictions_are_failures(self):
        for index,key,value in ((0,'image','/wrong/library'),(0,'identity','3'*128),(0,'pid',0),(0,'event','wrong'),
                                (1,'mode','wrong'),(1,'author',1),(1,'checks',0),(1,'helper_vectors',22),(1,'scope','helper-only'),(1,'result','failed')):
            rows=self.output();rows[index][key]=value
            with self.subTest(key=key),self.assertRaises(ObservationFailure):self.inspect(rows)

    def test_helper_cannot_claim_native_or_wrong_vector_count(self):
        rows=self.output('author-1','helper-protocol')
        for key,value in (('scope','native-sdk'),('helper_vectors',22),('author',0)):
            changed=copy.deepcopy(rows);changed[0][key]=value
            with self.assertRaises(ObservationFailure):self.inspect(changed,'author-1','helper-protocol')

    def test_json_duplicates_and_noninteger_numbers_refused(self):
        text='{"result":"passed","result":"passed"}'
        with self.assertRaises(ValueError):values.inspect_output(text,'author-0','helper-protocol',None,None)
        text=json.dumps(self.output()[0]).replace('123','1.5')+'\n'+json.dumps(self.output()[1])
        with self.assertRaises(ValueError):values.inspect_output(text,'author-0','values',self.library,self.identity)

    def test_pins_are_complete_unique_and_closed(self):
        pins=[g+'=sha256:'+str(i)*64 for i,g in enumerate(values.GROUPS)]
        self.assertEqual(set(values.parse_pins(pins)),set(values.GROUPS))
        for bad in (pins[:-1],pins+[pins[0]],pins+['unknown=sha256:'+'1'*64],[p.replace('sha256:','') for p in pins]):
            with self.assertRaises(ValueError):values.parse_pins(bad)

    def test_exact_export_sets_reject_foreign_and_old_symbols(self):
        for group in values.GROUPS:
            expected=values.expected_exports(group)
            output='\n'.join('0000 T _'+s for s in sorted(expected))
            contract={'symbols':[{'shape':{'link_name':s}} for s in expected]}
            self.assertEqual(set(values.inspect_exports(output,group,contract)),expected)
            for bad in (output+'\n0000 T _foreign_function',output+'\n0000 T _reading_demo_raw_deleted','\n'.join(output.splitlines()[:-1])):
                with self.assertRaises(values.CandidateError):values.inspect_exports(bad,group,contract)
            with self.assertRaises(values.CandidateError):values.inspect_exports(output,group,{'symbols':[]})

    def test_selections_reject_wrong_identity_scope_and_obligations(self):
        group='author-0';target='aarch64-apple-darwin';pin='sha256:'+'1'*64;producer='2'*40
        valid={'manifest':{'candidate_digest':pin,'required_cases':records.required_ids(group),
                          'selector':{'profile_id':'l02-native-values-author-0-'+target,'target':target,'route':'RUST-C-ABI','direction':'consumer-to-provider'},
                          'files':[{'path':'include/'+name} for name in ('madb_value_abi_v1.h','reading_demo_native.h','reading_demo.h')]},
               'provenance':{'producer_revision':producer},'contract':{'sdk_namespace':'reading_demo'}}
        values.check_selection(group,valid,pin,producer,target)
        mutations=[lambda x:x['provenance'].update(provisional=True),lambda x:x['provenance'].update(producer_revision='3'*40),
                   lambda x:x['manifest']['required_cases'].append('extra'),lambda x:x['manifest']['selector'].update(target='wrong'),
                   lambda x:x['manifest']['files'].pop(),lambda x:x['contract'].update(sdk_namespace='wrong')]
        for mutation in mutations:
            changed=copy.deepcopy(valid);mutation(changed)
            with self.assertRaises(values.CandidateError):values.check_selection(group,changed,pin,producer,target)

    def test_author_bytes_must_match_fixed_change_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=values.ROOT/'fixtures/l02/native-values/author-2.rs';ref=values.reference(source)
            lock={'inputs':[{'path':'author.rs',**ref}]};(root/'madb.lock').write_text(json.dumps(lock))
            self.assertEqual(values.verify_author(root,'author-2')['sha256'],ref['sha256'])
            for changed in ({'inputs':[]},{'inputs':[lock['inputs'][0],lock['inputs'][0]]},{'inputs':[{'path':'author.rs','sha256':'sha256:'+'0'*64,'size':ref['size']}]}):
                (root/'madb.lock').write_text(json.dumps(changed))
                with self.assertRaises(values.CandidateError):values.verify_author(root,'author-2')

    def test_expected_rejection_requires_specific_diagnostic_not_crash(self):
        class Commands:
            output=Path('/private/tmp')
            def __init__(self,value):self.value=value
            def run(self,*args,**kwargs):raise CommandFailure(Path('/private/tmp/log.json'),self.value)
        good={'exit_code':1,'timeout':False,'stderr':"error: use of undeclared identifier 'reading_demo_offset'"}
        self.assertEqual(values.expect_rejection(Commands(good),[],'reading_demo_offset','declaration')['stage'],'declaration')
        for patch in ({'exit_code':-11},{'timeout':True},{'stderr':'error: unrelated missing header'}, {'stderr':good['stderr']+'\nfatal error: header missing'}):
            with self.assertRaises((CommandFailure,ObservationFailure)):values.expect_rejection(Commands({**good,**patch}),[],'reading_demo_offset','declaration')
        link={'exit_code':1,'timeout':False,'stderr':"undefined reference to `reading_demo_raw_offset'"}
        self.assertEqual(values.expect_rejection(Commands(link),[],'reading_demo_raw_offset','link')['stage'],'link')

    def test_mixed_compile_selects_only_shared_entry_for_both_header_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            class Commands:
                output=root;c_flags=[];system_roots=[]
                def __init__(self):self.compilations=[];self.calls=[]
                def run(self,argv,timeout):
                    self.calls.append(argv)
                    if '-MF' in argv:Path(argv[argv.index('-MF')+1]).write_text('unit dependency record')
            for group in ('author-0','author-2'):
                commands=Commands()
                with patch.object(values,'dependency_inputs',return_value={}):
                    values.compile_consumer(commands,Path('/unit/clang'),root,root/'provider',root/'consumer',group,mismatch=True)
                self.assertEqual(len(commands.calls),2)
                self.assertTrue(all('-DMADB_LAB_MISMATCH_ONLY=1' in argv for argv in commands.calls))
                self.assertTrue(all('-DMADB_LAB_STUB=1' not in argv for argv in commands.calls))
            for group,stub in (('author-1',False),('aux-grow',False),('author-0',True)):
                with self.assertRaises(ValueError):
                    values.compile_consumer(Commands(),Path('/unit/clang'),root,root/'provider',root/'consumer',group,stub=stub,mismatch=True)

    def test_assertion_classification_is_precise(self):
        self.assertEqual(records.failure_status(ObservationFailure('wrong')),'failed')
        self.assertEqual(records.failure_status(ValueError('missing')),'error')
        for code,timeout,stderr,expected in [(2,False,'L02 values assertion:3:r.kind==0','failed'),
                (2,False,'other crash','error'),(-11,False,'L02 values assertion:3:x','error'),(2,True,'L02 values assertion:3:x','error')]:
            error=CommandFailure(Path('log'),{'exit_code':code,'timeout':timeout,'stderr':stderr})
            self.assertEqual(records.failure_status(error),expected)


class ReportChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='madb-values-report-unit-');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'lab';self.output=self.base/'output';self.output.mkdir()
        for name in ('cases/l02/native-values','consumers/c','fixtures/l02/native-values'):
            shutil.copytree(values.ROOT/name,self.root/name)
        self.candidates={g:{'manifest':{'required_cases':records.required_ids(g),'candidate_digest':'sha256:'+'1'*64,
                         'selector':{'profile_id':g,'profile_digest':'sha256:'+'2'*64,'route':'RUST-C-ABI','target':'aarch64-apple-darwin','direction':'consumer-to-provider'}},
                         'provenance':{'input_digest':'sha256:'+'3'*64,'tool_digest':'sha256:'+'4'*64}} for g in records.GROUPS}
        self.reports=records.Reports(self.root,self.output,self.candidates,'5'*40,[])

    def complete(self):
        for number,(group,name) in enumerate(self.reports.cases):
            self.reports.begin(group,name)
            p=self.output/('log-'+str(number)+'.json');p.write_text('{"exit_code":0,"timeout":false}')
            self.reports.finish(10,20,[records.file_reference(p,self.output)],[{'unit_evidence_only':True}])

    def test_definitions_frozen_before_case_invocation(self):
        self.assertEqual(len(self.reports.cases),29)
        self.assertEqual(len(read_json(self.output/'case-inputs.json')['cases']),29)
        self.assertEqual(case_errors(self.root),[])
        self.assertEqual(self.reports.completed,{})
        with self.assertRaises(ValueError):self.reports.verify()

    def test_complete_reports_preserve_candidate_scope_and_levels(self):
        self.complete();self.reports.verify();(self.output/'report.json').write_text('{}')
        paths=self.reports.write({'result':'passed','logs':[]})
        self.assertEqual(len(paths),7)
        for path in paths:
            report=read_json(self.output/path['path']);self.assertEqual(report['schema'],'madb.report/1')
            for row in report['results']:
                self.assertEqual(row['status'],'passed');self.assertEqual(row['resource_observations'],[])
                name=row['case_id'].split('.')[-1]
                self.assertEqual(row['evidence_level'],records.LEVELS.get(name,'target-run'))

    def test_final_closure_failure_does_not_keep_partial_passes(self):
        self.complete();(self.output/'report.json').write_text('{}')
        paths=self.reports.write({'result':'failed','logs':[]},ValueError('final image changed'))
        rows=[x for p in paths for x in read_json(self.output/p['path'])['results']]
        self.assertEqual([x['status'] for x in rows].count('error'),1)
        self.assertEqual([x['status'] for x in rows].count('blocked'),28)
        self.assertNotIn('passed',[x['status'] for x in rows])

    def test_failed_target_attempt_keeps_actual_evidence_level_and_time(self):
        self.reports.begin('author-0','values')
        log=self.output/'target.json'
        evidence={'exit_code':2,'timeout':False,'duration_ns':123456789,
                  'stderr':'L02 values assertion:3:r.kind==0'}
        log.write_text(json.dumps(evidence));self.reports.note_target('target.json')
        (self.output/'report.json').write_text('{}')
        paths=self.reports.write({'result':'failed','logs':[{'path':'target.json'}]},CommandFailure(log,evidence))
        rows=read_json(self.output/paths[0]['path'])['results'];attempt=rows[0]
        self.assertEqual(attempt['status'],'failed')
        self.assertEqual(attempt['evidence_level'],'target-run')
        self.assertEqual(attempt['duration_ms'],123)
        self.assertEqual(attempt['resource_observations'],[])
        self.assertEqual(rows[1]['status'],'blocked')
        self.assertEqual(rows[1]['evidence_level'],'static')
        self.assertEqual(rows[1]['duration_ms'],0)

    def test_target_attempt_requires_active_case_and_complete_process_record(self):
        with self.assertRaises(ValueError):self.reports.note_target('missing.json')
        self.reports.begin('author-0','values')
        log=self.output/'target.json'
        valid={'exit_code':0,'timeout':False,'duration_ns':10}
        for patch in ({'exit_code':None},{'exit_code':True},{'timeout':None},
                      {'duration_ns':True},{'duration_ns':-1}):
            log.write_text(json.dumps({**valid,**patch}))
            with self.assertRaises(ValueError):self.reports.note_target('target.json')
        self.assertEqual(self.reports.attempted,{})

    def test_changed_instance_catalog_fixture_and_log_refused(self):
        self.complete();self.reports.verify()
        for ref in [self.reports.index,*list(self.reports.refs.values())[:1],*next(iter(self.reports.logs.values()))]:
            p=self.output/ref['path'];original=p.read_bytes();p.write_bytes(original+b' ')
            with self.assertRaises(ValueError):self.reports.verify()
            p.write_bytes(original)
        source=self.root/'consumers/c/l02_values.c';original=source.read_bytes();source.write_bytes(original+b' ')
        with self.assertRaises(ValueError):self.reports.verify()
        source.write_bytes(original)

    def test_unknown_duplicate_and_budget_overrun_refused(self):
        with self.assertRaises(ValueError):self.reports.begin('author-0','unknown')
        self.reports.begin('author-0','values')
        with self.assertRaises(ValueError):self.reports.begin('author-0','values')
        p=self.output/'one.json';p.write_text('{}')
        with self.assertRaises(RuntimeError):self.reports.finish(0,180000000001,[records.file_reference(p,self.output)],[{'unit':True}])

    def test_candidate_cannot_drop_required_case(self):
        changed=copy.deepcopy(self.candidates);changed['author-0']['manifest']['required_cases'].pop()
        with self.assertRaises(ValueError):records.Reports(self.root,self.base/'other',changed,'5'*40,[])


from candidate import read_json
if __name__=='__main__':unittest.main()
