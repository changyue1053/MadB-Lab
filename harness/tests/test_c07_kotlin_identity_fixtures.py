from pathlib import Path
import sys,json,hashlib,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c07_kotlin_identity_fixtures import admit_kotlin_identity_fixtures,COMPONENTS,FACADE,PROVIDER
from candidate import CandidateError

def ref(p,name=None):
 b=p.read_bytes();return {'path':name or str(p),'sha256':'sha256:'+hashlib.sha256(b).hexdigest(),'size':len(b)}
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,sort_keys=True,indent=2)+'\n')
def setup(root,variant='test'):
 normal=root/'candidate';normal.mkdir();module='madbc07sdkkotlin'+('test' if variant=='test' else '')
 identity={'schema':'madb.arkts-runtime-identity/1','bootstrap_version':1,**{k:'sha256:'+v*64 for k,v in zip(COMPONENTS.values(),'abc')}}
 identity['expected_identity']='madb-arkts/1:'+':'.join(identity[k][7:] for k in COMPONENTS.values())
 write(normal/'identity.json',identity)
 p=normal/FACADE;p.parent.mkdir(parents=True);p.write_text('const EXPECTED_IDENTITY: string = "'+identity['expected_identity']+'";\n')
 source={'path':'source.kt','sha256':'sha256:'+'d'*64,'size':4};write(normal/'madb.lock',{'inputs':[source]})
 inventory=[ref(normal/n,n) for n in ('identity.json',FACADE,'madb.lock')]
 candidate={'root':normal,'route':'kotlin','companion':variant=='test','module':module,'identity':identity,'manifest':{'generation_id':'generation','selector':{'profile_id':'kn'+('-test' if variant=='test' else '')},'files':inventory,'dependencies':[],'build_evidence':[]}}
 base=root/'fixtures';base.mkdir();references=[]
 for kind,component in COMPONENTS.items():
  folder=base/kind;folder.mkdir();changed=dict(identity);changed[component]='sha256:'+'f'*64;changed['expected_identity']='madb-arkts/1:'+':'.join(changed[k][7:] for k in COMPONENTS.values())
  write(folder/'identity.json',changed)
  libraries=[]
  for name in ('lib'+module+'.so',PROVIDER):
   elf=bytearray(64);elf[:6]=b'\x7fELF\x02\x01';elf[18:20]=(183).to_bytes(2,'little')
   p=folder/name;p.write_bytes(bytes(elf)+changed['expected_identity'].encode()+b'\x00');libraries.append(ref(p))
  phases=[]
  for phase in ('compile','link'):
   p=folder/(phase+'.json');write(p,[]);phases.append({'phase':phase,'log':ref(p),'outputs':[]})
  phases[-1]['outputs']=[dict(v,path='native/'+Path(v['path']).name) for v in libraries]
  original=[source,ref(normal/'identity.json','identity.json'),ref(normal/FACADE,FACADE)]
  rec={'case':kind,'candidate':False,'target_executed':False,'variant':variant,'build_status':'compiled-and-linked','generation_id':'generation','selector':candidate['manifest']['selector'],'native_module':'lib'+module+'.so','changed_files':['identity.json'],'logical_identity_component':component,'original_identity':identity,'fixture_identity':changed,'original_inputs':original,'fixture_inputs':[source,ref(folder/'identity.json','identity.json'),ref(normal/FACADE,FACADE)],'unchanged_facade':ref(normal/FACADE,FACADE),'bootstrap_error':'IdentityMismatch','provider_only_error':'ProviderIdentityMismatch','phases':phases,'libraries':libraries}
  p=folder/'receipt.json';write(p,rec);references.append(ref(p))
 collection=base/'fixtures.json';write(collection,{'candidate':False,'target_executed':False,'variant':variant,'fixtures':references})
 return candidate,collection

def mutate(collection,change):
 d=json.loads(collection.read_text());p=Path(d['fixtures'][0]['path']);r=json.loads(p.read_text());change(r);write(p,r);d['fixtures'][0]=ref(p);write(collection,d)

class KotlinFixtureAdmission(unittest.TestCase):
 def test_six_actual_member_roles_for_each_variant(self):
  for variant in ('ordinary','test'):
   with tempfile.TemporaryDirectory() as tmp:
    c,p=setup(Path(tmp),variant);fixtures,used=admit_kotlin_identity_fixtures(p,ref(p)['sha256'],c)
    self.assertEqual(len(fixtures),6);self.assertEqual(len(used),16)
    self.assertEqual({v['error'] for v in fixtures.values()},{'IdentityMismatch','ProviderIdentityMismatch'})
 def test_variants_generation_and_stages_not_interchangeable(self):
  for change in (lambda r:r.update(variant='ordinary'),lambda r:r.update(generation_id='old'),lambda r:r.update(native_module='libwrong.so'),lambda r:r.update(bootstrap_error='ProviderIdentityMismatch'),lambda r:r.update(changed_files=['identity.json',FACADE])):
   with tempfile.TemporaryDirectory() as tmp:
    c,p=setup(Path(tmp));mutate(p,change)
    with self.assertRaises(CandidateError):admit_kotlin_identity_fixtures(p,ref(p)['sha256'],c)
 def test_only_one_logical_component_and_derived_string(self):
  for change in (lambda r:r['fixture_identity'].update(build_id='sha256:'+'e'*64),lambda r:r.update(logical_identity_component='build_id'),lambda r:r['fixture_inputs'][1].update(sha256='sha256:'+'0'*64),lambda r:r['fixture_identity'].update(extra='unreviewed')):
   with tempfile.TemporaryDirectory() as tmp:
    c,p=setup(Path(tmp));mutate(p,change)
    with self.assertRaises(CandidateError):admit_kotlin_identity_fixtures(p,ref(p)['sha256'],c)
 def test_real_dso_hash_and_identity_required(self):
  with tempfile.TemporaryDirectory() as tmp:
   c,p=setup(Path(tmp));doc=json.loads(p.read_text());r=json.loads(Path(doc['fixtures'][0]['path']).read_text());lib=Path(r['libraries'][0]['path']);lib.write_bytes(lib.read_bytes()+b'changed')
   with self.assertRaises(CandidateError):admit_kotlin_identity_fixtures(p,ref(p)['sha256'],c)
 def test_parent_and_facade_source_closure_required(self):
  for change in (lambda r:r['original_inputs'][0].update(sha256='sha256:'+'e'*64),lambda r:r['unchanged_facade'].update(size=0),lambda r:r['phases'][1].update(outputs=[]),lambda r:r.update(libraries=r['libraries'][:1])):
   with tempfile.TemporaryDirectory() as tmp:
    c,p=setup(Path(tmp));mutate(p,change)
    with self.assertRaises(CandidateError):admit_kotlin_identity_fixtures(p,ref(p)['sha256'],c)
 def test_collection_pin_and_duplicate_case_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   c,p=setup(Path(tmp))
   with self.assertRaises(CandidateError):admit_kotlin_identity_fixtures(p,'sha256:'+'0'*64,c)
   d=json.loads(p.read_text());d['fixtures'][1]=d['fixtures'][0];write(p,d)
   with self.assertRaises(CandidateError):admit_kotlin_identity_fixtures(p,ref(p)['sha256'],c)
