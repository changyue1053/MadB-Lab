from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import copy,io,json,tempfile,unittest,zipfile
from unittest.mock import patch
from candidate import CandidateError,file_digest
from c07_observations import EXPECTED,parse_ordinary
from c07_ordinary_identity_observations import expected_cases,parse
from c07_related_ordinary import verify_related_ordinary,read_ref,verify_hap
from c07_profile_pair import verify_profile_pair

ID='madb-arkts/1:'+':'.join(['a'*64,'b'*64,'c'*64])
DIGEST='sha256:'+'a'*64
OTHER='sha256:'+'b'*64

def encoded(value):return (json.dumps(value,sort_keys=True)+'\n').encode()
def elf(value):return b'\x7fELF\x02\x01'+b'\0'*12+b'\xb7\0'+value

def log(nonce,messages):return '\n'.join('date time 123 I '+m.replace('NONCE',nonce) for m in messages)
class RelatedOrdinaryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.normal=elf(b'normal');self.bad=elf(b'bad');self.refs={};self.commands=[]
  self.ordinary={'root':self.root/'candidate','route':'c','companion':False,'profile':{'id':'ordinary'},'manifest':{'candidate_digest':DIGEST,'selector':{'profile_id':'ordinary'}},'identity':{'expected_identity':ID},'native_members':{'package/libs/arm64-v8a/libm.so':self.normal},'provenance':{'producer_revision':'S','provisional':False}}
  self.companion={'route':'c','companion':True,'manifest':{'candidate_digest':OTHER}}
  self.ordinary['root'].mkdir();(self.ordinary['root']/'candidate.json').write_bytes(b'candidate')
  self.fixtures={kind:{'library':self.bad,'replaced_member':'package/libs/arm64-v8a/libm.so'} for kind in ['wrong-abi','wrong-profile','wrong-build']}
  self.pair={'status':'bound','ordinary_candidate_digest':DIGEST,'companion_candidate_digest':OTHER}
  self.add('admission.json',{'candidate_digest':DIGEST,'candidate_file':{'source':str(self.ordinary['root']),'sha256':file_digest(b'candidate')}})
  nonce='normal'
  raw=log(nonce,['PROBE_STARTED NONCE','PROBE_PAGE_READY NONCE']+['ORDINARY_CASE NONCE '+k+' '+json.dumps(v) for k,v in EXPECTED.items()]+['ORDINARY_COMPLETE NONCE','PROBE_FINISHED NONCE'])
  observation=parse_ordinary(raw,nonce=nonce,pid='123');self.assertEqual(observation['status'],'passed')
  self.add(nonce+'-observation-1.json',observation);self.build('',nonce,self.normal);self.command('commands/',raw)
  self.negatives={'status':'passed','route':'c','candidate_digest':DIGEST,'run_id':'negative-run','fixture_inputs':[{'path':'explicit/collection','sha256':OTHER,'size':1}],'observations':{}}
  for i,(case,error) in enumerate(expected_cases('c').items()):
   nonce='negative'+str(i);prefix='ordinary-identity/'+case+'/'
   raw=log(nonce,['PROBE_STARTED NONCE','PROBE_PAGE_READY NONCE','ORDINARY_IDENTITY_BEGIN NONCE '+case,'ORDINARY_IDENTITY_FRAME NONCE stage "ordinary-openRuntime-call"','ORDINARY_IDENTITY_FRAME NONCE rejected '+json.dumps(error),'ORDINARY_IDENTITY_COMPLETE NONCE '+case,'PROBE_FINISHED NONCE'])
   observation=parse(raw,nonce=nonce,pid='123',case=case,route='c');self.assertEqual(observation['status'],'passed')
   refs=self.build(prefix,nonce,self.bad);self.command(prefix+'commands/',raw)
   self.negatives['observations'][case]={'candidate_digest':DIGEST,'run_id':'negative-run','cleanup':'complete','observation':observation,'attachments':refs}
  self.add('ordinary-identity-results.json',self.negatives)
  self.add('command-manifest.json',{'commands':self.commands})
  self.report={'schema':'madb.report/1','run_id':'formal','identity':{'lab_revision':'L','candidate_digest':DIGEST},'selector':{'profile_id':'ordinary'},'results':[{'case_id':'required','status':'passed','cleanup':'complete','attachments':list(self.refs.values())}]}
 def put(self,name,data):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
  return {'path':name,'sha256':file_digest(data),'size':len(data)}
 def add(self,name,value):
  ref=self.put(name,encoded(value));self.refs[name]=ref;return ref
 def command(self,prefix,raw):
  for name,args,stdout in [('001-pid.json',['shell','pidof','com.madb.c07probe'],'123'),('002-hilog.json',['shell','hilog','-x','-T','MadBC07Probe'],raw)]:
   self.commands.append(self.put(prefix+name,encoded({'command':['hdc','-p','-t','target']+args,'stdout':stdout,'timeout':False,'exit_code':0})))
 def build(self,prefix,nonce,native):
  app={'buildMode':'release','minAPIVersion':60100023}
  members={'module.json':encoded({'app':app}),'ets/modules.abc':ID.encode()+b'\0','libs/arm64-v8a/libm.so':native}
  out=io.BytesIO()
  with zipfile.ZipFile(out,'w') as z:
   for n,v in members.items():z.writestr(n,v)
  refs=[]
  def item(suffix,data):
   ref=self.put(prefix+nonce+suffix,data);refs.append(ref);return dict(ref,path=nonce+suffix)
  build={'candidate_digest':DIGEST,'nonce':nonce,'app':app,'hap':item('.hap',out.getvalue()),'source_archive':item('.tar',b'sources'),'namecache':item('-cache.json',b'cache'),'members':[{'path':k,'size':len(v),'sha256':file_digest(v)} for k,v in sorted(members.items())]}
  refs.append(self.put(prefix+nonce+'-build.json',encoded(build)))
  if not prefix:self.refs.update({r['path']:r for r in refs})
  return refs
 def check(self):
  self.put('report.json',encoded(self.report))
  with patch('c07_related_ordinary.verify_candidate',return_value=self.ordinary),patch('c07_related_ordinary.verify_profile_pair',return_value=self.pair),patch('c07_related_ordinary.case_requirements',return_value=[{'id':'required'}]),patch('c07_identity_fixtures.admit_identity_fixtures',return_value=(self.fixtures,[])):
   return verify_related_ordinary(self.root/'report.json',file_digest(encoded(self.report)),self.companion,lab_revision='L')
 def refresh(self,name,value):
  ref=self.add(name,value)
  self.report['results'][0]['attachments']=[ref if x['path']==name else x for x in self.report['results'][0]['attachments']]
 def test_actual_zip_and_raw_positive_negative_replay(self):
  result=self.check();self.assertEqual(result['status'],'bound');self.assertEqual(len(result['negatives']),3)
 def test_clean_revision_profile_and_required_results(self):
  for change in ['dirty','revision','partial','source-pair']:
   with self.subTest(change=change):
    old=copy.deepcopy(self.report);pair=copy.deepcopy(self.pair)
    if change=='dirty':self.report['extensions']={'state':'provisional'}
    elif change=='revision':self.report['identity']['lab_revision']='old'
    elif change=='partial':self.report['results'][0]['status']='blocked'
    else:self.pair['status']='blocked'
    with self.assertRaises(CandidateError):self.check()
    self.report=old;self.pair=pair
 def test_pinned_raw_logs_cannot_be_substituted_or_pid_faked(self):
  command=self.commands[-1];path=self.root/command['path'];value=json.loads(path.read_text());value['stdout']=value['stdout'].replace(' 123 I ',' 0 I ')
  replacement=self.put(command['path'],encoded(value));self.commands[-1]=replacement
  self.refresh('command-manifest.json',{'commands':self.commands})
  with self.assertRaises(CandidateError):self.check()
 def test_saved_status_without_correct_library_fails(self):
  self.fixtures['wrong-build']['library']=self.normal
  with self.assertRaises(CandidateError):self.check()
 def test_missing_negative_and_envelope_replay_fail(self):
  old=copy.deepcopy(self.negatives)
  for action in ('missing','run','candidate'):
   self.negatives=copy.deepcopy(old);key=next(iter(self.negatives['observations']))
   if action=='missing':del self.negatives['observations'][key]
   else:self.negatives['observations'][key]['run_id' if action=='run' else 'candidate_digest']='old'
   self.refresh('ordinary-identity-results.json',self.negatives)
   with self.assertRaises(CandidateError):self.check()
 def test_escape_or_changed_attachment(self):
  with self.assertRaises(CandidateError):read_ref(self.root,{'path':'../escape','sha256':DIGEST,'size':0})
  (self.root/'normal.hap').write_bytes(b'changed')
  with self.assertRaises(CandidateError):self.check()

class ProfilePairTests(unittest.TestCase):
 def setUp(self):
  self.a={'route':'c','companion':False,'profile':{'id':'p'},'manifest':{'candidate_digest':DIGEST},'provenance':{'producer_revision':'S'}}
  self.b={'route':'c','companion':True,'profile':{'id':'p-test'},'manifest':{'candidate_digest':OTHER},'provenance':{'producer_revision':'S'}}
  self.sources=[]
  for c,v in [(self.a,'ordinary'),(self.b,'test')]:
   self.sources.append({'status':'bound','route':'c','candidate_digest':c['manifest']['candidate_digest'],'producer_revision':'S','source_review':{'status':'bound','route':'c','variant':v,'producer_revision':'S','inventory_sha256':DIGEST,'original_inputs':[{'path':'common','sha256':DIGEST,'size':1}]}})
 def check(self):
  with patch('c07_profile_pair.verify_route_ownership',side_effect=self.sources):return verify_profile_pair(self.a,self.b)
 def test_both_source_and_build_closure_required(self):self.assertEqual(self.check()['status'],'bound')
 def test_same_revision_alone_does_not_bind_variants(self):
  for k,v in [('status','blocked'),('inventory_sha256',OTHER),('variant','ordinary'),('original_inputs',[{'path':'common','sha256':OTHER,'size':1}])]:
   old=copy.deepcopy(self.sources)
   self.sources[1]['source_review'][k]=v
   with self.assertRaises(CandidateError):self.check()
   self.sources=old
if __name__=='__main__':unittest.main()
