from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json,unittest
from c07_ordinary_identity_observations import expected_cases,parse

def raw(case,error,stage='ordinary-openRuntime-call'):
    messages=['PROBE_STARTED nonce','PROBE_PAGE_READY nonce','PROBE_FINISHED nonce',
      'ORDINARY_IDENTITY_BEGIN nonce '+case,
      'ORDINARY_IDENTITY_FRAME nonce stage '+json.dumps(stage),
      'ORDINARY_IDENTITY_FRAME nonce rejected '+json.dumps(error),
      'ORDINARY_IDENTITY_COMPLETE nonce '+case]
    return '\n'.join('date time 123 I '+message for message in messages)
class OrdinaryIdentityTests(unittest.TestCase):
    def test_all_routes_and_member_specific_exact_errors(self):
        for route in ('c','cpp','rust','kotlin'):
            for case,error in expected_cases(route).items():
                result=parse(raw(case,error),nonce='nonce',pid='123',case=case,route=route)
                self.assertEqual(result['status'],'passed');self.assertNotIn('delta',result);self.assertFalse(result['certifies_c07'])
    def test_loader_failure_wrong_code_or_stage_does_not_pass(self):
        case='ordinary-identity-wrong-abi'
        for error,stage in [('ModuleNotFound','ordinary-openRuntime-call'),('ProfileMismatch','ordinary-openRuntime-call'),('AbiMismatch','module-import')]:
            self.assertEqual(parse(raw(case,error,stage),nonce='nonce',pid='123',case=case,route='c')['status'],'failed')
    def test_zero_wrong_pid_duplicate_missing_and_replayed_nonce(self):
        case='ordinary-identity-wrong-build';text=raw(case,'ArtifactMismatch')
        for changed,pid in [(text,'0'),(text,'124'),(text+'\n'+text.splitlines()[-1],'123'),(text.replace('PROBE_FINISHED','MISSING'),'123'),(text.replace('nonce','nonce-old'),'123')]:
            self.assertNotEqual(parse(changed,nonce='nonce',pid=pid,case=case,route='c')['status'],'passed')
    def test_no_completion_and_mixed_provider_error(self):
        case='ordinary-identity-wrong-build-provider';text=raw(case,'ProviderIdentityMismatch')
        self.assertEqual(parse(text.rsplit('\n',1)[0],nonce='nonce',pid='123',case=case,route='kotlin')['status'],'incomplete')
        self.assertEqual(parse(text.replace('ProviderIdentityMismatch','IdentityMismatch'),nonce='nonce',pid='123',case=case,route='kotlin')['status'],'failed')
if __name__=='__main__':unittest.main()
