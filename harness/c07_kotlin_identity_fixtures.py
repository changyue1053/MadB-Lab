"""Independent six substitutions from public Kotlin C04 fixture receipts.

Only the explicit collection and admitted candidate bytes are consumed. Ordinary
and companion variants cannot be interchanged. ELF literals prove bounded byte
consistency, not arbitrary executable semantics.
"""
from pathlib import Path
import json,re
from candidate import file_digest,read_json
from c07_candidate import identity_values
from c07_identity_fixtures import require,fields,rows
COMPONENTS={'wrong-abi':'abi_digest','wrong-profile':'profile_digest','wrong-build':'build_id'}
FACADE='generated/facade/Boundary.ets'
PROVIDER='libmadb_kotlin_owned_runtime.so'

def admit_kotlin_identity_fixtures(collection_path,collection_sha256,candidate):
 require(candidate['route']=='kotlin','Kotlin fixture requires Kotlin candidate')
 path=Path(collection_path).resolve();root=path.parent
 require(file_digest(path.read_bytes())==collection_sha256,'collection pin differs')
 used=[{'path':str(path),'sha256':collection_sha256,'size':path.stat().st_size}]
 def external(reference):
  value=fields(reference);target=Path(value['path']).resolve()
  require(target.is_relative_to(root),'fixture output escapes explicit collection directory')
  data=target.read_bytes();require(file_digest(data)==value['sha256'] and len(data)==value['size'],'changed fixture output')
  used.append(value);return data
 manifest=candidate['manifest'];variant='test' if candidate.get('companion',False) else 'ordinary'
 collection=read_json(path)
 require(collection.get('candidate') is False and collection.get('target_executed') is False and collection.get('variant')==variant and len(collection.get('fixtures',[]))==3,'not exact requested variant three invalid inputs')
 inventory={item['path']:fields(item) for section in ('files','dependencies','build_evidence') for item in manifest[section]}
 require(all(n in inventory for n in (FACADE,'identity.json','madb.lock')),'normal public contract incomplete')
 for name in (FACADE,'identity.json','madb.lock'):
  raw=(candidate['root']/name).read_bytes();require(file_digest(raw)==inventory[name]['sha256'] and len(raw)==inventory[name]['size'],'normal candidate changed')
 pinned=rows(read_json(candidate['root']/'madb.lock')['inputs']);normal=candidate['identity']
 require(read_json(candidate['root']/'identity.json')==normal,'candidate identity changed')
 bootstrap='lib'+candidate['module']+'.so';seen=set();admitted={}
 for reference in collection['fixtures']:
  external(reference);receipt=read_json(Path(reference['path']));kind=receipt.get('case')
  require(kind in COMPONENTS and kind not in seen,'unknown or duplicate negative kind');seen.add(kind)
  component=COMPONENTS[kind]
  require(receipt.get('candidate') is False and receipt.get('target_executed') is False and receipt.get('variant')==variant and receipt.get('build_status')=='compiled-and-linked','negative not compiled requested variant')
  require(receipt.get('generation_id')==manifest['generation_id'] and receipt.get('selector')==manifest['selector'] and receipt.get('native_module')==bootstrap,'fixture generation/profile/module differs')
  require(receipt.get('changed_files')==['identity.json'] and receipt.get('logical_identity_component')==component and fields(receipt['unchanged_facade'])==inventory[FACADE],'facade or permitted edited file differs')
  original,changed=rows(receipt['original_inputs']),rows(receipt['fixture_inputs'])
  require(set(original)==set(changed) and all(original.get(k)==v for k,v in pinned.items()),'normal locked input closure differs')
  require(all(original.get(k)==v for k,v in inventory.items() if k in original),'normal published input differs')
  require([k for k in original if original[k]!=changed[k]]==['identity.json'],'more than identity input changed')
  require(receipt.get('original_identity')==normal,'original identity tuple differs')
  new=receipt['fixture_identity'];require(isinstance(new,dict) and set(new)==set(normal),'negative identity keys differ')
  require(isinstance(new.get(component),str) and re.fullmatch(r'sha256:[0-9a-f]{64}',new[component]) and new[component]!=normal[component],'negative component absent or same')
  expected=dict(normal);expected[component]=new[component];expected['expected_identity']='madb-arkts/1:'+':'.join(expected[k][7:] for k in COMPONENTS.values())
  require(new==expected,'not an isolated tuple component with exact derived identity')
  encoded=(json.dumps(new,sort_keys=True,indent=2)+'\n').encode()
  require(changed['identity.json']['sha256']==file_digest(encoded) and changed['identity.json']['size']==len(encoded),'exact identity JSON transformation differs')
  require(receipt.get('bootstrap_error')=='IdentityMismatch' and receipt.get('provider_only_error')=='ProviderIdentityMismatch','wrong rejection stage contract')
  phases=receipt.get('phases',[]);require([x.get('phase') for x in phases]==['compile','link'],'missing compile/link receipts')
  for phase in phases:external(phase['log'])
  outputs=rows(phases[1]['outputs']);libraries=receipt.get('libraries',[])
  require(len(libraries)==2 and {Path(v['path']).name for v in libraries}=={bootstrap,PROVIDER},'two exact libraries required')
  for value in libraries:
   data=external(value);name=Path(value['path']).name
   require(data[:6]==b'\x7fELF\x02\x01' and int.from_bytes(data[18:20],'little')==183,'not AArch64 ELF')
   require(identity_values(data,binary=True,allow_parser_prefix=True)=={new['expected_identity'].encode()},'negative DSO identity absent/ambiguous/different')
   require(not re.findall(rb'[A-Za-z0-9_-]+/madb-arkts/1:[0-9a-f]{64}:[0-9a-f]{64}:[0-9a-f]{64}(?=\x00)',data),'foreign route identity in Kotlin DSO')
   linked=outputs.get('native/'+name);require(linked and linked['sha256']==value['sha256'] and linked['size']==len(data),'linked output differs from supplied library')
   role='bootstrap' if name==bootstrap else 'provider'
   admitted[kind+'-'+role]={'kind':kind,'role':role,'error':receipt['bootstrap_error' if role=='bootstrap' else 'provider_only_error'], 'library':data,'library_ref':fields(value),'receipt_ref':fields(reference),'wrong_identity':new['expected_identity'],'expected_identity':normal['expected_identity'],'replaced_member':'package/libs/arm64-v8a/'+name}
 require(seen==set(COMPONENTS) and len(admitted)==6,'missing exact six substitutions')
 return admitted,used
