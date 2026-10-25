from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import unittest
from c07_kotlin_identity_observations import SCENARIOS, U64, predicates, parse


def observer(role, after=False):
    count=(12,83)[role];f=[0]*(18+count);f[:4]=[70602,role,count,(1,6)[role]]
    if role==0:
        n=2 if after else 1
        f[4]=n+1;f[5]=n;f[7]=1;f[12]=U64;f[14]=n;f[17]=n
        f[18]=n;f[19]=1
    return ','.join(map(str,f))


def frames(case):
    provider=case.endswith('-provider')
    return {'before-admission':[0]*13,'before-napi':observer(0)+';unavailable',
      'stage':'test-openRuntime-call','rejected':'ProviderIdentityMismatch' if provider else 'IdentityMismatch',
      'after-admission':([1,1,0,1,1,0,0,1,1,0,0,0,0] if provider else [0,0,0,1,0,0,0,0,0,0,0,0,0]),
      'after-napi':observer(0,True)+';'+(observer(1) if provider else 'unavailable')}


def log(case,f=None,pid='123'):
    f=frames(case) if f is None else f
    prefix='10-25 12:00:00.000 '+pid+' 456 I MadBC07Probe: '
    lines=['PROBE_STARTED n1','PROBE_PAGE_READY n1','KOTLIN_IDENTITY_BEGIN n1 '+case]
    lines+=['KOTLIN_IDENTITY_FRAME n1 '+k+' '+json.dumps(v) for k,v in f.items()]
    lines+=['KOTLIN_IDENTITY_COMPLETE n1 '+case,'PROBE_FINISHED n1']
    return '\n'.join(prefix+x for x in lines)


class KotlinIdentity(unittest.TestCase):
    def test_all_six_positive_transport_and_observations(self):
        for case in SCENARIOS:
            with self.subTest(case=case):self.assertEqual(parse(log(case),nonce='n1',pid='123',case=case)['status'],'passed')

    def test_wrong_provider_cannot_be_unavailable(self):
        case=SCENARIOS[1];f=frames(case);f['after-napi']=observer(0,True)+';unavailable'
        self.assertTrue(predicates(case,f))

    def test_unavailable_cannot_be_filled_with_numeric_zero(self):
        case=SCENARIOS[0];f=frames(case);f['after-napi']=observer(0,True)+';'+observer(1)
        self.assertTrue(predicates(case,f))

    def test_provider_bound_before_identity_gate_fails(self):
        case=SCENARIOS[1];f=frames(case);parts=observer(1).split(',');parts[15]='1'
        f['after-napi']=observer(0,True)+';'+','.join(parts)
        self.assertTrue(predicates(case,f))

    def test_real_provider_api_attempt_before_admission_fails(self):
        case=SCENARIOS[1];f=frames(case);parts=observer(1).split(',')
        for i in (4,5,17,18):parts[i]='1'
        f['after-napi']=observer(0,True)+';'+','.join(parts)
        self.assertTrue(predicates(case,f))

    def test_bootstrap_gate_cannot_load_provider(self):
        case=SCENARIOS[0];f=frames(case);f['after-admission'][4]=1
        self.assertTrue(predicates(case,f))

    def test_provider_gate_cannot_initialize_owner(self):
        case=SCENARIOS[1];f=frames(case);f['after-admission'][5]=1
        self.assertTrue(predicates(case,f))

    def test_wrong_stage_code_is_not_loader_rejection(self):
        case=SCENARIOS[0];f=frames(case);f['rejected']='KotlinLoadFailure'
        self.assertTrue(predicates(case,f))

    def test_missing_positive_bootstrap_attempts_fails(self):
        case=SCENARIOS[0];f=frames(case);f['after-napi']=f['before-napi']
        self.assertTrue(predicates(case,f))

    def test_raw_napi_string_not_number_coerced(self):
        case=SCENARIOS[0];f=frames(case);f['before-napi']=[0]*30
        self.assertTrue(predicates(case,f))

    def test_admission_slot12_is_never_used_as_resource_witness(self):
        case=SCENARIOS[1];f=frames(case);f['before-admission'][12]=77;f['after-admission'][12]=88
        self.assertEqual(predicates(case,f),[])

    def test_nonce_pid_and_duplicate_marker_rejected(self):
        case=SCENARIOS[0];raw=log(case)
        self.assertEqual(parse(raw,nonce='n1',pid='999',case=case)['status'],'failed')
        extra='\n10-25 12:00:00.000 123 456 I MadBC07Probe: KOTLIN_IDENTITY_FRAME n1 rejected "IdentityMismatch"'
        self.assertEqual(parse(raw+extra,nonce='n1',pid='123',case=case)['status'],'failed')

    def test_failed_page_and_missing_finish_rejected(self):
        case=SCENARIOS[0];raw=log(case)
        self.assertEqual(parse(raw+'\n10-25 12:00:00.000 123 456 I MadBC07Probe: PROBE_FAILED n1 not-typed',nonce='n1',pid='123',case=case)['status'],'failed')
        self.assertEqual(parse(raw.replace('PROBE_FINISHED n1','UNFINISHED n1'),nonce='n1',pid='123',case=case)['status'],'failed')

    def test_no_completion_is_incomplete_not_pass(self):
        case=SCENARIOS[0]
        self.assertEqual(parse(log(case).replace('KOTLIN_IDENTITY_COMPLETE','NOT_COMPLETE'),nonce='n1',pid='123',case=case)['status'],'incomplete')

    def test_wrong_route_or_unknown_case_unsupported(self):
        self.assertEqual(parse('',nonce='n1',pid='123',case=SCENARIOS[0],route='c')['status'],'unsupported')
        self.assertEqual(parse('',nonce='n1',pid='123',case='other')['status'],'unsupported')


if __name__=='__main__':unittest.main()
