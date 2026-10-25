"""Run wrong libraries under unchanged ordinary public HAR expectations."""
from copy import copy
import json,uuid
from c07_contract import SOURCE
from c07_execution import Session,ref,write_json
from c07_identity_execution import IdentitySession
from c07_ordinary_identity_observations import parse,expected_cases

class OrdinaryIdentitySession(IdentitySession):
 def prepare(self):
  # The ordinary source set has no test helper import or companion dispatch.
  Session.prepare(self)
  target=self.root/'entry/src/main/ets'
  (target/'pages/Index.ets').write_text((SOURCE/'OrdinaryIdentityPage.ets.in').read_text().replace('@MADB_PUBLIC_MODULE@',json.dumps(self.candidate['module'])))
  (target/'IdentityConfig.ets').write_text('export const IDENTITY_CASE: string = '+json.dumps(self.scenario)+';\nexport const IDENTITY_ERROR: string = '+json.dumps(self.fixture['error'])+';\n')
  self.apply_fixture()
 def parse_observation(self,raw,pid):
  return parse(raw,nonce=self.nonce,pid=pid,case=self.scenario,route=self.args.route)

def run_ordinary_identity(args,candidate):
 if candidate.get('companion',False):raise ValueError('ordinary identity cannot consume companion candidate')
 if args.route=='kotlin':
  from c07_kotlin_identity_fixtures import admit_kotlin_identity_fixtures as admit
 else:
  from c07_identity_fixtures import admit_identity_fixtures as admit
 fixtures,used=admit(args.identity_fixtures,args.identity_fixtures_sha256,candidate)
 result={'run_id':'c07-ordinary-identity-'+uuid.uuid4().hex,'candidate_digest':candidate['manifest']['candidate_digest'],'route':args.route,
  'observations':{},'fixture_inputs':used,'scope':'actual ordinary bootstrap rejection; resource counters require separately matched companion','certifies_c07':False}
 for scenario in expected_cases(args.route):
  child_args=copy(args);child_args.output=args.output/'ordinary-identity'/scenario;child_args.output.mkdir(parents=True)
  child=OrdinaryIdentitySession(child_args,candidate,scenario,{},fixtures[scenario.removeprefix('ordinary-identity-')]);observation=None
  try:
   child.prepare();child.build();observation=child.execute()
  except (OSError,RuntimeError,ValueError,KeyError) as error:
   observation={'status':'error','case':scenario,'route':args.route,'nonce':child.nonce,'pid':None,'frames':{},'problems':[str(error)],'certifies_c07':False}
  finally:
   if hasattr(child,'hap'):
    try:child.stop()
    except (OSError,RuntimeError) as error:observation=dict(observation or {},status='error',problems=['recovery failed: '+str(error)])
   envelope={'candidate_digest':result['candidate_digest'],'run_id':result['run_id'],'observation':observation,'cleanup':'complete' if child.stopped else 'not-run',
    'attachments':[ref(p,args.output) for p in sorted(child_args.output.iterdir()) if p.is_file()]}
   write_json(child_args.output/'result.json',envelope);result['observations'][scenario]=envelope
  print('C07 ordinary identity '+scenario+': '+observation['status'],flush=True)
  if observation['status']=='error':break
 result['status']='passed' if set(result['observations'])==set(expected_cases(args.route)) and all(v['observation']['status']=='passed' for v in result['observations'].values()) else 'failed'
 return result
