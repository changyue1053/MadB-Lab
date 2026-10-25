from pathlib import Path
import sys,copy,json,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from c07_kotlin_observations import parse_kotlin,normal_shutdown,NATIVE_FIELDS,CONTROL_FIELDS,SETTLEMENT_FIELDS
from test_c07_kotlin_controller import normal_frames
from test_c07_kotlin_followup import fault_fixture
from test_c07_kotlin_napi import positive

def fixture(before=True):
 case='kotlin-fault-before-guard' if before else 'kotlin-fault-after-accepted'
 f={k:v for k,v in normal_frames().items() if not k.startswith('subscriptions-')}
 f.update(fault_fixture(before));f['runtime-closed']=list(f['kn-fault-closed-native'])
 return case,f

def parse(case,frames):
 markers=['PROBE_STARTED nonce','PROBE_PAGE_READY nonce','PROBE_FINISHED nonce','KOTLIN_BEGIN nonce '+case]
 markers+=['KOTLIN_FRAME nonce '+k+' '+json.dumps(v) for k,v in frames.items()]
 markers+=['KOTLIN_COMPLETE nonce '+case]
 raw='\n'.join('10-25 12:00:00.000 123 456 I Probe: '+x for x in markers)
 binding=positive()
 return parse_kotlin(raw,nonce='nonce',pid='123',case=case,napi_binding=binding[3],napi_identity=binding[4],contracts={
 'kotlin-frame-layout.json':{'format':70501,'length':110,'fields':[{'index':i,'name':v} for i,v in enumerate(NATIVE_FIELDS)]},
 'kotlin-controls-layout.json':{'frame':{'fields':[{'index':i,'name':v} for i,v in enumerate(CONTROL_FIELDS)]}},
 'settlement-frame.json':{'length':9,'fields':[{'index':i,'name':v} for i,v in enumerate(SETTLEMENT_FIELDS)]}})

class FollowupTransport(unittest.TestCase):
 def test_failed_close_scope_is_separate_from_normal_close(self):
  for before in (True,False):
   case,f=fixture(before);r=parse(case,f)
   self.assertEqual(r['status'],'passed',r['problems'])
   self.assertIn('no normal-close oracle attribution',r['napi_observation']['scope'])
 def test_no_fault_turns_into_success_or_skips_outer_physical_ack(self):
  for label,index,value in [('kn-fault-close-outcome',0,1),('runtime-closed',109,0),('js-final',7,1),('kn-fault-close-pending',2,1)]:
   case,f=fixture();f[label][index]=value
   self.assertEqual(parse(case,f)['status'],'failed')
 def test_fault_napi_violations_and_missing_raw_are_not_silenced(self):
  case,f=fixture();del f['napi-final'];self.assertEqual(parse(case,f)['status'],'failed')
  case,f=fixture();pieces=f['napi-open'].split(';');csv=pieces[1].split(',');csv[10]='1';pieces[1]=','.join(csv);f['napi-open']=';'.join(pieces)
  self.assertEqual(parse(case,f)['status'],'failed')
 def test_exact_generation_count_not_merely_positive(self):
  f=normal_frames()
  for expected in (2,3):
   self.assertTrue(normal_shutdown(f,expected_engines=expected))
   f['runtime-closed'][12]=f['runtime-closed'][13]=expected
   self.assertEqual(normal_shutdown(f,expected_engines=expected),[])
   f['runtime-closed'][13]=expected-1
   self.assertTrue(normal_shutdown(f,expected_engines=expected))
