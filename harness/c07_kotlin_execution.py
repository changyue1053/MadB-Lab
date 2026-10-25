"""Kotlin public companion HAPs use Kotlin contracts and their own oracles."""
from copy import copy
import json
import uuid
import sys
from candidate import CandidateError, read_json, file_digest
from c07_contract import SOURCE
from c07_execution import Session, ref, write_json
from c07_controlled_execution import ControlledSession
from c07_kotlin_observations import SCENARIOS, parse_kotlin, validate_kotlin_contracts


def napi_inventory_command(python, contract, bootstrap, provider, llvm, output):
    return [python, '-I', '-S', '-B', SOURCE.parents[2]/'harness/c07_kotlin_napi_inventory.py',
        '--contract', contract, '--bootstrap', bootstrap, '--provider', provider,
        '--readelf', llvm/'llvm-readelf', '--objdump', llvm/'llvm-objdump', '--output', output]


def kotlin_contracts(candidate):
    inventory = {item['path'] for section in ('files','dependencies','build_evidence')
                 for item in candidate['manifest'][section]}
    paths = {'kotlin-frame-layout.json':'generated/contract/kotlin-frame-layout.json',
             'kotlin-controls-layout.json':'generated/contract/test/controls-frame.json',
             'admission-frame.json':'generated/contract/test/admission-frame.json',
             'settlement-frame.json':'generated/contract/test/settlement-frame.json',
             'memory-frame.json':'generated/contract/test/memory-frame.json',
             'napi-observer-frame.json':'generated/contract/test/napi-observer-frame.json'}
    if not set(paths.values()) <= inventory:
        raise CandidateError('ArtifactMismatch','Kotlin companion lacks explicit candidate contract files')
    contracts = {name:read_json(candidate['root']/path) for name,path in paths.items()}
    errors = validate_kotlin_contracts(contracts,controls=True,admission=True,settling=True,memory=True)
    if errors:raise CandidateError('ProfileMismatch','; '.join(errors))
    return contracts,[ref(candidate['root']/path,candidate['root']) for path in paths.values()]


class KotlinSession(ControlledSession):
    def __init__(self,args,candidate,scenario,contracts,napi_binding=None,napi_identity=None):
        super().__init__(args,candidate,scenario,contracts)
        self.napi_binding,self.napi_identity=napi_binding,napi_identity

    def prepare(self):
        # Share the admitted HAR/native inventory, Release build and signing code.
        # C controlled templates and C frame declarations are not copied.
        Session.prepare(self)
        target = self.root/'entry/src/main/ets'
        for source in sorted((SOURCE/'kotlin').rglob('*.ets.in')):
            relative = source.relative_to(SOURCE)
            if relative.as_posix()=='kotlin/workers/WorkerFirst.ets.in':
                relative = relative.parent.parent.parent/'workers/KotlinWorkerFirst.ets.in'
            destination = target/relative.with_suffix('')
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_text(source.read_text().replace('@MADB_PUBLIC_MODULE@',json.dumps(self.candidate['module'])))
        (target/'pages/Index.ets').write_text((SOURCE/'KotlinPage.ets.in').read_text().replace(
            '@MADB_PUBLIC_MODULE@',json.dumps(self.candidate['module'])))
        (target/'ProbeCase.ets').write_text('export const PROBE_CASE: string = '+json.dumps(self.scenario)+';\n')
        with (self.root/'entry/obfuscation-rules.txt').open('a') as stream:
            stream.write('\n-keep-file-name\nKotlinWorkerFirst\n')

    def parse_observation(self,raw,pid):
        return parse_kotlin(raw,nonce=self.nonce,pid=pid,case=self.scenario,contracts=self.contracts,
            napi_binding=self.napi_binding,napi_identity=self.napi_identity)


def run_kotlin_companion(args,candidate):
    contracts,inputs=kotlin_contracts(candidate)
    result={'run_id':'c07-kotlin-controlled-'+uuid.uuid4().hex,
            'candidate_digest':candidate['manifest']['candidate_digest'],'observations':{},
            'target':{},'contract_inputs':inputs,'certifies_c07':False,
            'scope':'current Kotlin companion; explicit normal main-env shutdown, no host VM destruction claim'}
    parent=Session(args,candidate)
    parent.verify_tools();result['target']=parent.verify_target()
    native = candidate['root']/'native'
    identity = {name:file_digest(path.read_bytes())[7:] for name,path in {
        'bootstrap':native/('lib'+candidate['module']+'.so'),
        'provider':native/'libmadb_kotlin_owned_runtime.so',
        'contract':candidate['root']/'generated/contract/test/napi-observer-frame.json'}.items()}
    inventory = args.output/'napi-inventory'
    parent.run('independent-napi-inventory',napi_inventory_command(sys.executable,
        candidate['root']/'generated/contract/test/napi-observer-frame.json',
        native/('lib'+candidate['module']+'.so'),native/'libmadb_kotlin_owned_runtime.so',
        parent.sdk/'openharmony/native/llvm/bin',inventory),timeout=120)
    binding=read_json(inventory/'binding.json')
    result['napi_static_binding']={'identity':identity,'files':[ref(path,args.output) for path in sorted(inventory.rglob('*')) if path.is_file()]}
    try:
        for scenario in SCENARIOS:
            output=args.output/'scenarios'/scenario;output.mkdir(parents=True)
            child_args=copy(args);child_args.output=output
            child=KotlinSession(child_args,candidate,scenario,contracts,binding,identity)
            observed=None
            try:
                child.prepare();child.build();observed=child.execute()
            except (OSError,RuntimeError,ValueError,KeyError) as error:
                observed={'status':'error','case':scenario,'route':'kotlin','nonce':child.nonce,
                          'pid':None,'frames':{},'problems':[str(error)],'failures':[],'certifies_c07':False}
            finally:
                if hasattr(child,'hap'):
                    try:child.stop()
                    except (OSError,RuntimeError) as error:
                        observed=dict(observed or {},status='error',case=scenario,route='kotlin',
                                      problems=['test recovery failed: '+str(error)])
                envelope={'candidate_digest':result['candidate_digest'],'run_id':result['run_id'],
                          'observation':observed,'cleanup':'complete' if child.stopped else 'not-run',
                          'attachments':[ref(path,args.output) for path in sorted(output.iterdir()) if path.is_file()]}
                write_json(output/'result.json',envelope);result['observations'][scenario]=envelope
            print('C07 Kotlin controlled '+scenario+': '+observed['status'],flush=True)
            if observed['status']=='error':break
    finally:parent.verify_closure('after')
    return result
