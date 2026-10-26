"""Hand-authored oracle sensitivity fixtures; not target observations."""
from pathlib import Path
import sys,copy,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c07_kotlin_fault_observations import predicates as fault,SCENARIOS as FAULTS
from c07_kotlin_handle_observations import predicates as handles
from c07_kotlin_listener_observations import predicates as listener,STATES
from c07_kotlin_admission_observations import PAIRS

def n(**values):
    f=[0]*110;f[0]=70501
    for key,value in values.items():f[int(key)]=value
    return f

def c(**values):
    f=['0']*31;f[0]='1';f[4]='1';f[5]='1'
    for key,value in values.items():f[int(key)]=str(value)
    return ','.join(f)

def complete():
    f=n(**{'1':4,'2':1,'7':1,'72':3})
    for a,b in PAIRS:f[a]=f[b]=1
    return f

def fault_fixture(before):
    final=complete();final[9]=final[10]=final[14]=final[15]=2
    residual=n(**{'9':2,'10':int(not before),'11':1+int(before),'12':1,'14':2,'15':1,'39':1,'26':int(before)})
    frames={'kn-fault-first-control':c(**{'3':2,'5':1}),
      'kn-fault-first-completed':n(**{'9':1,'11':1,'14':1,'15':1,'24':1}),
      'kn-fault-held-control':c(**{'3':2,'5':2}), 'kn-fault-held-native':n(**{'9':2,'11':2,'12':1,'14':2,'15':1,'24':2,'39':1}),
      'kn-fault-close-pending-control':c(**{'3':2,'5':2}), 'kn-fault-close-proof':[0,1,1],
      'kn-fault-settlements':[0,1,0] if before else [1,0,1], 'kn-fault-residual-native':residual,
      'kn-fault-residual-control':c(**{'26':int(before),'28':int(not before),'29':int(not before)}),
      'kn-fault-settler':[int(not before),int(not before),int(not before),int(before),int(not before),0,1,0,0],
      'kn-fault-close-pending':n(**{'1':2,'12':1,'14':2,'15':1,'39':1}), 'kn-fault-close-outcome':[0,1],
      'kn-fault-closed-native':final,'kn-fault-final-settler':[0]*9,
      'kn-fault-late-settlements':[0,1,0,1] if before else [1,0,0,1]}
    if not before:frames['kn-fault-after-resolver']=[1,1,1,0,0,1,1,0,1]
    return frames

def handle_fixture():
    before=n(**{'9':2,'10':1,'11':1,'12':2,'13':1,'24':1,'25':1,'36':2,'39':1})
    return {'kn-handles-first-retired':n(**{'12':1,'13':1,'36':1}),
      'kn-handles-second-open':n(**{'12':2,'13':1,'36':2,'39':1}),
      'kn-handles-work-held':c(**{'3':1,'4':2,'5':2}),
      'kn-handles-before':before,'kn-handles-after':list(before),
      'kn-handles-negative-cases':[1,2,3,4,5],'kn-handles-recovered':[42,52,71,15]}

def listener_fixture():
    return {**{label:list(value) for label,value in STATES.items()},
      'kn-listener-source-native':n(**{'30':1,'28':1}),
      'kn-listener-pending-native':n(**{'28':1}),
      'kn-listener-entry-native':n(**{'25':1,'31':1}),
      'kn-listener-lifetime-counts':[0,0,1],'kn-listener-lifetime-drained':n()}

class FollowupOracles(unittest.TestCase):
    def test_fault_positive_scopes(self):
        for before in (True,False):self.assertEqual(fault('kotlin-fault-before-guard' if before else 'kotlin-fault-after-accepted',fault_fixture(before)),[])
    def test_fault_missing_retained_guard_or_wrong_settlement(self):
        for before in (True,False):
            case='kotlin-fault-before-guard' if before else 'kotlin-fault-after-accepted'
            for label,index,value in [('kn-fault-residual-native',26,int(not before)),('kn-fault-residual-native',13,1),('kn-fault-close-pending',2,1),('kn-fault-close-outcome',0,1),('kn-fault-closed-native',109,0),('kn-fault-final-settler',7,1),('kn-fault-late-settlements',3,2)]:
                frames=fault_fixture(before);frames[label][index]=value
                with self.subTest(before=before,label=label):self.assertTrue(fault(case,frames))
    def test_double_operation_and_handler_time_evidence_is_required(self):
        for before in (True,False):
            case='kotlin-fault-before-guard' if before else 'kotlin-fault-after-accepted'
            for label,index,value in [('kn-fault-first-completed',15,0),('kn-fault-first-completed',26,1),('kn-fault-held-native',14,1),('kn-fault-held-native',15,2),('kn-fault-residual-native',11,int(before)),('kn-fault-close-pending',15,2),('kn-fault-closed-native',14,1),('kn-fault-closed-native',15,1),('kn-fault-close-proof',0,1),('kn-fault-close-proof',1,0),('kn-fault-close-proof',2,0)]:
                f=fault_fixture(before);f[label][index]=value
                with self.subTest(case=case,label=label,index=index):self.assertTrue(fault(case,f))
            for label in ('kn-fault-held-control','kn-fault-close-pending-control'):
                f=fault_fixture(before);parts=f[label].split(',');parts[5]='1';f[label]=','.join(parts)
                self.assertTrue(fault(case,f))

    def test_fault_zero_owner_pair_not_activity(self):
        f=fault_fixture(True);f['kn-fault-closed-native']=n(**{'1':4,'2':1,'7':1,'72':3})
        self.assertTrue(fault('kotlin-fault-before-guard',f))
    def test_handle_positive_and_no_second_generation_inference(self):
        self.assertEqual(handles(handle_fixture()),[])
        for label,index,value in [('kn-handles-first-retired',13,0),('kn-handles-second-open',36,1),('kn-handles-second-open',12,1),('kn-handles-before',25,0),('kn-handles-after',9,3),('kn-handles-after',26,1),('kn-handles-negative-cases',2,7),('kn-handles-recovered',1,51)]:
            f=handle_fixture();f[label][index]=value
            with self.subTest(label=label,index=index):self.assertTrue(handles(f))
    def test_listener_real_closed_wrapper_field_and_entered_positive(self):
        self.assertEqual(listener(listener_fixture()),[])
        for label,index,value in [('kn-listener-source-retained',3,0),('kn-listener-source-released',3,1),('kn-listener-pending-native',31,1),('kn-listener-entry-native',31,0),('kn-listener-entry-released',2,0),('kn-listener-lifetime-counts',2,0),('kn-listener-lifetime-drained',28,1)]:
            f=listener_fixture();f[label][index]=value
            with self.subTest(label=label):self.assertTrue(listener(f))
    def test_missing_labels_fail_closed(self):
        for make,check in [(handle_fixture,handles),(listener_fixture,listener)]:
            f=make();f.pop(next(iter(f)));self.assertTrue(check(f))
        f=fault_fixture(True);f.pop('kn-fault-close-outcome');self.assertTrue(fault('kotlin-fault-before-guard',f))

if __name__=='__main__':unittest.main()
