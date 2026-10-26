import sys, copy, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from c07_kotlin_napi_inventory import inspect_relocations, OPTIONAL_CALLSITE
from c07_kotlin_napi_observations import validate, NapiObservationFailure
from test_c07_kotlin_napi import positive

def static_fixture():
 names=OPTIONAL_CALLSITE|{'napi_get_undefined'}
 rows=[{'name':n,'section':'UND','binding':'WEAK' if n in OPTIONAL_CALLSITE else 'GLOBAL'} for n in names]
 lines=[f'000100 000001 R_AARCH64_JUMP_SLOT 000000 {n} + 0' for n in sorted(names)]
 lines += [f'000200 000002 R_AARCH64_GLOB_DAT 000000 {n} + 0' for n in sorted(OPTIONAL_CALLSITE)]
 return '\n'.join(lines),rows,names

def dynamic_fixture():
 a=positive();p=a[3]['roles']['provider'];p['napi_relocations'] += [{'type':'R_AARCH64_GLOB_DAT','api':n} for n in sorted(OPTIONAL_CALLSITE)];p['weak_got_imports']=sorted(OPTIONAL_CALLSITE);return a

class WeakImportTests(unittest.TestCase):
 def test_exact_weak_quartet_retains_all_plt_delegates(self):
  text,rows,names=static_fixture();r,w=inspect_relocations(text,rows,'provider',names);self.assertEqual(w,sorted(OPTIONAL_CALLSITE));self.assertEqual(len(r),9)
  validate(*dynamic_fixture())
 def test_strong_or_mixed_binding_rejected(self):
  for name in OPTIONAL_CALLSITE:
   text,rows,names=static_fixture();rows=[dict(r,binding='GLOBAL') if r['name']==name else r for r in rows]
   with self.subTest(name=name),self.assertRaises(ValueError):inspect_relocations(text,rows,'provider',names)
  text,rows,names=static_fixture();rows.append(dict(next(r for r in rows if r['name']=='napi_create_callsite_info'),binding='GLOBAL'))
  with self.assertRaises(ValueError):inspect_relocations(text,rows,'provider',names)
 def test_bootstrap_extra_missing_and_unknown_relocations_rejected(self):
  text,rows,names=static_fixture()
  for bad,role in [(text,'bootstrap'),('\n'.join(text.splitlines()[:-1]),'provider'),(text+'\n000300 000003 R_AARCH64_GLOB_DAT 000000 napi_get_undefined + 0','provider'),(text.replace('R_AARCH64_GLOB_DAT','R_AARCH64_ABS64'),'provider'),(text.replace('napi_create_callsite_info','napi_unknown'),'provider')]:
   with self.subTest(role=role,bad=bad),self.assertRaises(ValueError):inspect_relocations(bad,rows,role,names)
 def test_missing_plt_even_with_got_rejected(self):
  text,rows,names=static_fixture();text='\n'.join(l for l in text.splitlines() if not ('JUMP_SLOT' in l and 'napi_create_callsite_info' in l))
  with self.assertRaises(ValueError):inspect_relocations(text,rows,'provider',names)
 def test_oracle_rejects_unbound_extra_partial_or_missing_delegation(self):
  for mutation in ['no-proof','partial','extra','wrong-kind','no-plt','no-delegate','wrong-role','duplicate-proof']:
   a=dynamic_fixture();p=a[3]['roles']['provider'];r=p['napi_relocations']
   if mutation=='no-proof':p.pop('weak_got_imports')
   elif mutation=='partial':p['weak_got_imports'].pop()
   elif mutation=='extra':r.append({'type':'R_AARCH64_GLOB_DAT','api':'napi_get_undefined'});p['weak_got_imports']=sorted(OPTIONAL_CALLSITE|{'napi_get_undefined'})
   elif mutation=='wrong-kind':r[-1]['type']='R_AARCH64_ABS64'
   elif mutation=='no-plt':p['napi_relocations']=[x for x in r if not (x['api']=='napi_create_callsite_info' and x['type']=='R_AARCH64_JUMP_SLOT')]
   elif mutation=='no-delegate':p['callsites']['napi_create_callsite_info']['delegates']=[]
   elif mutation=='wrong-role':a[3]['roles']['bootstrap']['napi_relocations'].append({'type':'R_AARCH64_GLOB_DAT','api':'napi_module_register'});a[3]['roles']['bootstrap']['weak_got_imports']=['napi_module_register']
   else:p['weak_got_imports'].append(p['weak_got_imports'][0])
   with self.subTest(mutation=mutation),self.assertRaises(NapiObservationFailure):validate(*a)

if __name__=='__main__':unittest.main()
