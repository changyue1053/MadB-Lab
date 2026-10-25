from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c07_kotlin_work_observations import predicates

def native(**values):
 f=[0]*110;f[0]=70501
 for k,v in values.items():f[int(k)]=v
 return f

def control(**values):
 f=['0']*31;f[0]='1';f[4]=f[5]='1';f[6]='-1'
 for k,v in values.items():f[int(k)]=str(v)
 return ','.join(f)

def gate(phase=1):return {'work-held':native(**{'12':1,'39':1,'24':1}),'work-held-control':control(**{'3':phase})}
class WorkOracleTests(unittest.TestCase):
 def test_held_phase_is_not_terminal_ack(self):
  f=gate(2);f.update({'terminal-before':control(**{'3':2,'6':0}),'terminal-after':control(**{'3':2,'6':0}),'terminal-close-pending':native(),'terminal-outcome':[0]})
  self.assertEqual(predicates('kotlin-terminal-success',f),[]);f['terminal-close-pending'][13]=1;self.assertTrue(predicates('kotlin-terminal-success',f))
 def test_ninth_operation_must_not_allocate(self):
  f=gate();f.update({'operations-full':native(**{'24':8,'9':8}),'operations-denied':native(**{'24':8,'9':8}),'operations-recovered':[42]})
  self.assertEqual(predicates('kotlin-operations-capacity',f),[]);f['operations-denied'][9]+=1;self.assertTrue(predicates('kotlin-operations-capacity',f))
 def test_parent_control_cannot_be_business33(self):
  f=gate();f.update({'waiters-full':native(**{'26':32}),'parent-close-full':native(**{'26':32})});self.assertEqual(predicates('kotlin-shared-waiters',f),[]);f['parent-close-full'][26]=33;self.assertTrue(predicates('kotlin-shared-waiters',f))
 def test_settlement_must_be_actual_and_still_charged(self):
  f=gate();f.update({'waiters-full':native(**{'26':32}),'settling-actual':[1,1,0,1,0,1,32,0,1]});self.assertEqual(predicates('kotlin-settling-reentry',f),[]);f['settling-actual'][5]=0;self.assertTrue(predicates('kotlin-settling-reentry',f))
 def test_claim_retry_requires_actual_rollback_not_only_error(self):
  f=gate();f.update({'claim-rollback-control':control(**{'25':1,'30':1}),'claim-rollback-native':native(),'claim-rollback-result':[42]});self.assertEqual(predicates('kotlin-claim-rollback',f),[]);f['claim-rollback-control']=control(**{'25':1});self.assertTrue(predicates('kotlin-claim-rollback',f))
 def test_consumed_failure_requires_paired_guard(self):
  f=gate(2);f.update({'after-guard-control':control(**{'27':1,'28':1,'29':1}),'after-guard-native':native()});self.assertEqual(predicates('kotlin-after-guard',f),[]);f['after-guard-control']=control(**{'27':1,'28':1});self.assertTrue(predicates('kotlin-after-guard',f))
 def test_bytes_not_scratch_count(self):
  f=gate();f.update({label:native(**{'24':4,'27':4096,'33':1,'34':1}) for label in ('bytes-scratch-full','bytes-scratch-denied')});self.assertEqual(predicates('kotlin-bytes-scratch',f),[]);f['bytes-scratch-full'][27]=1;self.assertTrue(predicates('kotlin-bytes-scratch',f))
 def test_missing_frames_never_pass(self):self.assertTrue(predicates('kotlin-terminal-domain',{}))
if __name__=='__main__':unittest.main()
