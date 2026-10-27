"""I01 evidence rules only; model fixtures do not execute or certify an SDK."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'harness'))
sys.path.insert(0, str(ROOT / 'scripts'))
import verify_i01_values as values
import i01_values_reports as records
from candidate import CandidateError, read_json
from l02_reports import CommandFailure, ObservationFailure


def candidate():
    return {'manifest': {'candidate_digest': 'sha256:' + '1'*64,
                         'required_cases': records.required_ids(values.GROUP),
                         'selector': {'profile_id': 'i01-native-values-macos-arm64-0-1-1',
                                      'profile_digest': 'sha256:'+'2'*64, 'target': 'aarch64-apple-darwin',
                                      'route': 'RUST-C-ABI', 'direction': 'consumer-to-provider'},
                         'files': [{'path': p} for p in ('include/madb_value_abi_v1.h',
                                   'include/reading_demo_native.h', 'include/reading_demo.h', 'lib/libreading_demo.dylib')]},
            'provenance': {'producer_revision': '3'*40, 'input_digest': 'sha256:'+'4'*64, 'tool_digest': 'sha256:'+'5'*64},
            'contract': {'sdk_namespace': 'reading_demo', 'symbols': [
                {'shape': {'link_name': 'reading_demo_bootstrap_v1'}}, {'shape': {'link_name': 'reading_demo_raw_normalize'}}]}}


class OracleTests(unittest.TestCase):
    def setUp(self):
        self.library = Path('/tmp/i01-model-library.dylib')
        self.identity = {'interface_digest': 'sha256:'+'a'*64, 'profile_digest': 'sha256:'+'b'*64}

    def rows(self, mode):
        rows = [{'event': 'binding', 'image': str(self.library), 'identity': 'a'*64+'b'*64, 'pid': 1}]
        if mode == 'ordinary':
            rows += [{'event': 'value', 'id': n, 'value': v, 'hex': b.hex(), 'input_preserved': True,
                      'tail_zero': True, 'kind': 0, 'status': 0, 'domain': 0, 'code': 0} for n,v,b in values.EXPECTED]
        return rows + [{'result': 'passed', 'mode': mode, 'checks': 1,
                        'vectors': 11 if mode == 'ordinary' else 0, 'scope': 'i01-initial-native-values'}]

    def inspect(self, rows, mode='ordinary'):
        return values.inspect_output('\n'.join(json.dumps(r) for r in rows), mode, self.library, self.identity)

    def test_exact_two_modes_and_eleven_vectors(self):
        for mode in ('bootstrap', 'ordinary'): self.inspect(self.rows(mode), mode)
        self.assertEqual(len(values.EXPECTED), 11)
        self.assertEqual(dict((n,b) for n,_,b in values.EXPECTED)['nul'], b'a\0b')

    def test_terminal_marker_cannot_replace_values(self):
        rows = self.rows('ordinary')
        for bad in (rows[:1]+rows[-1:], rows+rows[-1:], rows[1:], rows[:-1]):
            with self.assertRaises(ValueError): self.inspect(bad)

    def test_wrong_values_preservation_tail_and_status_are_rejections(self):
        for field,value in [('hex','20'),('value',8),('input_preserved',False),('tail_zero',False),
                            ('kind',1),('status',1),('domain',1),('code',1)]:
            rows=self.rows('ordinary');rows[1][field]=value
            with self.subTest(field=field), self.assertRaises(ObservationFailure): self.inspect(rows)

    def test_ill_typed_evidence_is_error_not_boolean_integer_equality(self):
        for index,field,value in [(0,'pid',True),(1,'value',True),(1,'status',False),(-1,'vectors',True)]:
            rows=self.rows('ordinary');rows[index][field]=value
            with self.assertRaises(ValueError): self.inspect(rows)

    def test_loaded_image_and_both_digests_are_required(self):
        for field,value in [('image','/tmp/other.dylib'),('identity','c'*128),('pid',0)]:
            rows=self.rows('bootstrap');rows[0][field]=value
            with self.assertRaises(ObservationFailure): self.inspect(rows,'bootstrap')

    def test_scope_selection_and_case_set_are_independent(self):
        good=candidate()
        def check(c): values.check_selection(c,'sha256:'+'1'*64,'3'*40,'aarch64-apple-darwin')
        check(good)
        for names in ([],records.required_ids(values.GROUP)[:1],records.required_ids(values.GROUP)*2,
                      records.required_ids(values.GROUP)+['l02.native-values.author-0.values']):
            bad=copy.deepcopy(good);bad['manifest']['required_cases']=names
            with self.assertRaises(CandidateError):check(bad)
        for location,key,value in [('provenance','provisional',True),('provenance','producer_revision','6'*40),
                                   ('contract','sdk_namespace','other')]:
            bad=copy.deepcopy(good);bad[location][key]=value
            with self.assertRaises(CandidateError):check(bad)

    def test_failure_classification_does_not_accept_arbitrary_crash(self):
        for code,timeout,stderr,status in [(2,False,'I01 values assertion:1:x','failed'),
                (2,False,'other','error'),(-11,False,'I01 values assertion:1:x','error'),
                (2,True,'I01 values assertion:1:x','error')]:
            error=CommandFailure(Path('log'),{'exit_code':code,'timeout':timeout,'stderr':stderr})
            self.assertEqual(records.failure_status(error),status)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='madb-i01-evidence-unit-');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'lab';self.output=self.base/'output';self.output.mkdir()
        for name in ('cases/i01','consumers/c'):
            shutil.copytree(ROOT/name,self.root/name)
        self.reports=records.Reports(self.root,self.output,{values.GROUP:candidate()},'6'*40,[])

    def complete(self, name):
        self.reports.begin(values.GROUP,name)
        path=self.output/(name+'.json')
        path.write_text(json.dumps({'exit_code':0,'timeout':False,'duration_ns':10,'stdout':'model-only'}))
        self.reports.note_target(path.name)
        self.reports.finish(10,20,[records.file_reference(path,self.output)],[{'model_only':True}])

    def test_definitions_frozen_before_target_and_cannot_drop_required(self):
        self.assertEqual(len(read_json(self.output/'case-inputs.json')['cases']),2)
        with self.assertRaises(ValueError):self.reports.verify()
        for names in ([],records.required_ids(values.GROUP)*2):
            c=candidate();c['manifest']['required_cases']=names
            with self.assertRaises(ValueError):records.Reports(self.root,self.output,{values.GROUP:c},'6'*40,[])

    def test_success_requires_actual_target_log_and_both_cases(self):
        self.reports.begin(values.GROUP,'bootstrap');p=self.output/'fake.json';p.write_text('{}')
        with self.assertRaises(ValueError):
            self.reports.finish(0,1,[records.file_reference(p,self.output)],[{'model':True}])
        with self.assertRaises(ValueError):self.reports.verify()

    def test_case_catalog_source_instance_and_log_drift_rejected(self):
        for name in ('bootstrap','ordinary'):self.complete(name)
        self.reports.verify()
        paths=[self.root/'consumers/c/i01_values.c',self.output/self.reports.index['path'],
               self.output/'ordinary.json',self.output/self.reports.refs[(values.GROUP,'bootstrap')]['path']]
        for path in paths:
            before=path.read_bytes();path.write_bytes(before+b' ')
            with self.assertRaises(ValueError):self.reports.verify()
            path.write_bytes(before)

    def test_final_shared_failure_blocks_success_and_preserves_actual_level(self):
        for name in ('bootstrap','ordinary'):self.complete(name)
        (self.output/'report.json').write_text('{}')
        refs=self.reports.write({'result':'failed','logs':[]},ValueError('final image drift'))
        report=read_json(self.output/refs[0]['path'])
        self.assertEqual([r['status'] for r in report['results']],['error','blocked'])
        self.assertTrue(all(r['evidence_level']=='target-run' for r in report['results']))
        self.assertEqual(report['identity']['lab_revision'],'6'*40)

    def test_both_actual_model_observations_encode_existing_report(self):
        for name in ('bootstrap','ordinary'):self.complete(name)
        (self.output/'report.json').write_text('{}')
        refs=self.reports.write({'result':'passed','logs':[]})
        report=read_json(self.output/refs[0]['path'])
        self.assertEqual(report['schema'],'madb.report/1')
        self.assertEqual([r['case_id'] for r in report['results']],records.required_ids(values.GROUP))
        self.assertTrue(all(r['status']=='passed' and r['cleanup']=='complete' for r in report['results']))

    def test_initial_author_bytes_are_exact_and_unique(self):
        path=self.base/'candidate';path.mkdir()
        expected=values.reference(ROOT/'cases/i01/rust-c-values/author.rs')
        def write(items):(path/'madb.lock').write_text(json.dumps({'inputs':items}))
        row={'path':'author.rs',**expected};write([row]);values.verify_author(path)
        for entries in ([],[row,row],[{**row,'sha256':'sha256:'+'0'*64}]):
            write(entries)
            with self.assertRaises(CandidateError):values.verify_author(path)


if __name__=='__main__':unittest.main()
