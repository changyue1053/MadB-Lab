from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import copy,unittest
from c07_companion_cases import assess_group,GROUPS
from c07_kotlin_cases import GROUPS as KN
from c07_kotlin_identity_observations import SCENARIOS as IDENTITY
D='sha256:'+'a'*64
O='sha256:'+'b'*64
RUN='current'
def records(route,groups):
 return {n:{'candidate_digest':D,'run_id':RUN,'observation':{'case':n,'route':route,'status':'passed','nonce':'new-'+n,'pid':1,'frames':{'host-double':[1]},'problems':[],'failures':[],'certifies_c07':False}} for g in groups.values() for n in g['scenarios']}
def related(route):
 return {'candidate_digest':D,'run_id':RUN,'observation':{'status':'bound','route':route,'ordinary_candidate_digest':O,'companion_candidate_digest':D,'report':{'sha256':O},'pair':{'status':'bound','ordinary_candidate_digest':O,'companion_candidate_digest':D}}}
def ownership():
 return {'candidate_digest':D,'run_id':RUN,'observation':{'status':'bound','route':'kotlin','candidate_digest':D,'producer_revision':'S','inventory_sha256':D,'source_review':{'status':'bound','variant':'test'},'applicability':{'status':'bound','execution_domain':'main-env-only','profile_id':'c07-kotlin-arkts-aarch64-ohos23-test'}}}
class AssociationGateTests(unittest.TestCase):
 def assess(self,route='kotlin',group='identity',values=None,**kw):return assess_group(group,route=route,candidate_digest=D,run_id=RUN,observations=values if values is not None else records(route,KN if route=='kotlin' else GROUPS),**kw)
 def test_kotlin_ordinary_six_cannot_replace_test_six(self):
  values=records('kotlin',KN)
  self.assertEqual(self.assess(related_ordinary=related('kotlin'))['status'],'passed')
  for missing in IDENTITY:
   changed=copy.deepcopy(values);del changed[missing]
   self.assertEqual(self.assess(values=changed,related_ordinary=related('kotlin'))['status'],'blocked')
  self.assertEqual(len(KN['identity']['scenarios']),7)
 def test_current_companion_without_ordinary_cannot_pass(self):
  for route in ('c','cpp','rust','kotlin'):
   self.assertEqual(self.assess(route=route)['status'],'blocked')
   self.assertEqual(self.assess(route=route,related_ordinary=related(route))['status'],'passed')
 def test_related_evidence_must_match_current_pair_and_run(self):
  for change in ('run','candidate','source-pair','report','ordinary-pair'):
   item=related('kotlin')
   if change=='run':item['run_id']='old'
   elif change=='candidate':item['candidate_digest']=O
   elif change=='source-pair':item['observation']['pair']['status']='blocked'
   elif change=='report':item['observation']['report']['sha256']='unknown'
   else:item['observation']['pair']['ordinary_candidate_digest']=D
   self.assertEqual(self.assess(related_ordinary=item)['status'],'blocked')
 def test_static_source_never_substitutes_thread_scene(self):
  item=ownership()
  self.assertEqual(self.assess(group='worker-and-domain',route_ownership=item)['status'],'passed')
  values=records('kotlin',KN);del values['kotlin-live-threads']
  self.assertEqual(self.assess(group='worker-and-domain',values=values,route_ownership=item)['status'],'blocked')
  for change in ('source','variant','candidate','applicability'):
   changed=copy.deepcopy(item)
   if change=='source':changed['observation']['source_review']['status']='blocked'
   elif change=='variant':changed['observation']['source_review']['variant']='ordinary'
   elif change=='candidate':changed['candidate_digest']=O
   else:changed['observation']['applicability']['execution_domain']='invented'
   self.assertEqual(self.assess(group='env-exit-full',route_ownership=changed)['status'],'blocked')
if __name__=='__main__':unittest.main()
