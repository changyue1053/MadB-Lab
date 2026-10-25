from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copy import deepcopy
import unittest
from c07_kotlin_thread_observations import SCENARIOS,UNKNOWN,parse,predicates

def csv(**values):
 f=['0']*21;f[0]='70604';f[1]='9007199254740993';f[2]='9007199254740995'
 for i in (7,8,9):f[i]=UNKNOWN
 for k,v in values.items():f[int(k)]=str(v)
 return ','.join(f)
def frame(**values):
 f=[0]*110;f[0]=70501
 for k,v in values.items():f[int(k)]=v
 return f

def positive():
 before=csv(**{'3':1,'4':1,'14':1})
 armed=csv(**{'3':1,'4':1,'10':1,'14':1})
 live=csv(**{str(i):1 for i in (3,4,5,6,7,8,9,10,11,14,16)})
 released=csv(**{str(i):1 for i in (3,4,6,10,11,12,14,16)})
 final=csv(**{'3':1,**{str(i):1 for i in range(10,20)}})
 return {'kn-thread-'+name:raw for name,raw in [('before',before),('armed',armed),('live-first',live),('live-heartbeat',live),('released',released),('final',final)]}|{'kn-thread-work':[42],'kn-thread-heartbeat':[2,0,0],'kn-thread-close-pending':frame(**{'12':1}), 'kn-thread-closed-native':frame(**{'1':4,'2':1,'7':1,'12':1,'13':1,'72':3}),'kn-thread-close-outcome':[1,0]}
def mutate(f,label,index,value):
 v=f[label].split(',');v[index]=str(value);f[label]=','.join(v)

class Threads(unittest.TestCase):
 def test_positive_raw_identity_and_fresh_scope(self):
  self.assertEqual(predicates(positive()),[])
  self.assertEqual(parse(positive()['kn-thread-final'])[1:3],['9007199254740993','9007199254740995'])
 def test_every_successful_snapshot_is_an_actual_owner_entry(self):
  for label in ('before','armed','released','final'):
   f=positive();mutate(f,'kn-thread-'+label,3,0);self.assertTrue(predicates(f))
 def test_live_fields_are_real_and_simultaneous(self):
  for label in ('kn-thread-live-first','kn-thread-live-heartbeat'):
   for index in range(3,10):
    f=positive();mutate(f,label,index,0)
    with self.subTest(label=label,index=index):self.assertTrue(predicates(f))
 def test_unknown_is_not_distinct(self):
  for index in (7,8,9):
   f=positive();mutate(f,'kn-thread-live-first',index,UNKNOWN);self.assertTrue(predicates(f))
 def test_actual_join_must_not_return_while_held(self):
  for index in (12,13,15,17,18,19):
   f=positive();mutate(f,'kn-thread-live-heartbeat',index,1);self.assertTrue(predicates(f))
 def test_heartbeat_not_same_turn_or_resolved_close(self):
  for value in ([1,0,0],[2,1,0],[2,0,1],[0,0,0]):
   f=positive();f['kn-thread-heartbeat']=value;self.assertTrue(predicates(f))
 def test_every_exit_tls_join_destroy_ack_required(self):
  for index in range(10,20):
   f=positive();mutate(f,'kn-thread-final',index,0);self.assertTrue(predicates(f))
 def test_historical_comparisons_and_final_active_flags_rejected(self):
  for index,value in [(4,1),(5,1),(6,1),(7,1),(8,1),(9,1),(20,1)]:
   f=positive();mutate(f,'kn-thread-final',index,value);self.assertTrue(predicates(f))
 def test_epoch_generation_or_zero_identity_rejected(self):
  for label,index,value in [('kn-thread-live-first',1,1),('kn-thread-final',2,1),('kn-thread-before',1,0)]:
   f=positive();mutate(f,label,index,value);self.assertTrue(predicates(f))
 def test_native_pending_and_final_checkpoint_required(self):
  for label,index,value in [('kn-thread-close-pending',13,1),('kn-thread-close-pending',2,1),('kn-thread-closed-native',13,0),('kn-thread-closed-native',2,0)]:
   f=positive();f[label][index]=value;self.assertTrue(predicates(f))
 def test_raw_wire_invalid_and_missing_labels(self):
  for raw in (None,[1]*21,'0'*441,csv().replace('70604','70605'),csv(**{'1':'01'}),csv(**{'1':'18446744073709551616'}),csv(**{'7':2}),csv(**{'4':2})):
   with self.assertRaises(ValueError):parse(raw)
  for label in SCENARIOS['kotlin-live-threads']:
   f=positive();del f[label];self.assertTrue(predicates(f))
  f=positive();f['kn-thread-fake']=[];self.assertTrue(predicates(f))
if __name__=='__main__':unittest.main()
