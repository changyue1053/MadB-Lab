"""Pair approved ordinary/companion source closures, independently of target reports."""
from candidate import CandidateError
from c07_route_ownership import verify_route_ownership

def _require(ok,why):
 if not ok:raise CandidateError('ArtifactMismatch','related ordinary profile: '+why)

def verify_profile_pair(ordinary,companion,*,review_id="c07"):
 route=ordinary['route'];_require(route==companion['route'],'different routes')
 if route=='kotlin':
  from c07_kotlin_source_review import verify_kotlin_profile_pair
  return verify_kotlin_profile_pair(ordinary,companion,review_id=review_id)
 _require(route in ('c','cpp','rust'),'unsupported profile pair')
 _require(ordinary.get('companion',False) is False and companion.get('companion') is True,'wrong ordinary/test variant')
 _require(ordinary['profile']['id']+'-test'==companion['profile']['id'],'not corresponding profile IDs')
 a,b=(verify_route_ownership(ordinary),verify_route_ownership(companion)) if review_id=="c07" else (verify_route_ownership(ordinary,review_id=review_id),verify_route_ownership(companion,review_id=review_id))
 for evidence,candidate,variant in ((a,ordinary,'ordinary'),(b,companion,'test')):
  review=evidence.get('source_review',{})
  _require(evidence.get('status')=='bound' and review.get('status')=='bound','finite independent source review/actual build chain incomplete')
  _require(evidence.get('route')==review.get('route')==route and review.get('variant')==variant,'source review route/variant differs')
  _require(evidence.get('candidate_digest')==candidate['manifest']['candidate_digest'],'source evidence candidate differs')
  _require(evidence.get('producer_revision')==review.get('producer_revision')==candidate['provenance']['producer_revision'],'source revision differs')
 _require(a['producer_revision']==b['producer_revision'] and a['source_review']['inventory_sha256']==b['source_review']['inventory_sha256'],'different approved revision/review inventory')
 def refs(evidence):
  items=evidence['source_review']['original_inputs'];r={v['path']:v for v in items}
  _require(len(r)==len(items),'duplicate original source');return r
 left,right=refs(a),refs(b);common=sorted(left.keys()&right.keys())
 _require(bool(common) and all(left[k]==right[k] for k in common),'common source closure differs or empty')
 return {'status':'bound','route':route,'producer_revision':a['producer_revision'],
  'ordinary_candidate_digest':ordinary['manifest']['candidate_digest'],'companion_candidate_digest':companion['manifest']['candidate_digest'],
  'ordinary_profile':ordinary['profile']['id'],'companion_profile':companion['profile']['id'],
  'inventory_sha256':a['source_review']['inventory_sha256'],'common_inputs':[left[k] for k in common],
  'ordinary_source':a,'companion_source':b,'scope':'finite reviewed source and actual build closure relation only; both target observations remain necessary'}
