from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_c07_kotlin_napi import positive
from c07_kotlin_observations import NATIVE_FIELDS,CONTROL_FIELDS,SETTLEMENT_FIELDS,SCENARIOS,parse_kotlin


def native(**values):
    f=[0]*110;f[0]=70501
    for key,value in values.items():f[int(key)]=value
    return f


def normal_frames():
    end=native(**{'1':4,'2':1,'7':1,'72':3})
    for left,right in ((12,13),(45,46),(48,49),(78,79),(102,103),(108,109)):end[left]=end[right]=1
    before,opened,final,_,_=positive()
    return {'napi-before-open':before,'napi-open':opened,'napi-final':final,'runtime-open':native(**{'1':1,'7':1,'39':1}),'runtime-closed':end,'runtime-complete':[1],'js-final':[0]*9,
            'subscriptions-full':native(**{'25':8}),'subscriptions-denied':native(**{'25':8}),
            'subscriptions-recovered':[1]}


def log(frames):
    lines=['PROBE_STARTED nonce','PROBE_PAGE_READY nonce','PROBE_FINISHED nonce','KOTLIN_BEGIN nonce kotlin-subscriptions-capacity']
    lines += ['KOTLIN_FRAME nonce '+k+' '+json.dumps(v) for k,v in frames.items()]
    lines += ['KOTLIN_COMPLETE nonce kotlin-subscriptions-capacity']
    return '\n'.join('10-25 12:00:00.000 123 456 I Probe: '+line for line in lines)


class KotlinControllerTests(unittest.TestCase):
    def parse(self,frames=None,**changes):
        fixture=positive()
        args=dict(napi_binding=fixture[3],napi_identity=fixture[4],raw=log(normal_frames() if frames is None else frames),nonce='nonce',pid='123',
                  case='kotlin-subscriptions-capacity',contracts={'settlement-frame.json':{'length':9,'fields':[{'index':i,'name':v} for i,v in enumerate(SETTLEMENT_FIELDS)]},'kotlin-frame-layout.json':
                  {'format':70501,'length':110,'fields':[{'index':i,'name':v} for i,v in enumerate(NATIVE_FIELDS)]}})
        args.update(changes);return parse_kotlin(**args)

    def test_normal_main_runtime_close_not_vm_destruction(self):
        result=self.parse();self.assertEqual(result['status'],'passed')
        self.assertEqual(result['frames']['runtime-closed'][51],0)
        self.assertEqual(result['frames']['runtime-closed'][86],0)

    def test_actual_candidate_napi_binding_and_raw_checkpoints_required(self):
        self.assertEqual(self.parse(napi_binding=None)['status'],'failed')
        frames=normal_frames();del frames['napi-final']
        self.assertEqual(self.parse(frames)['status'],'failed')
        result=self.parse()
        self.assertEqual(result['napi_observation']['env_validity'],'unobserved')

    def test_each_real_owner_and_finalizer_is_required(self):
        for index in (13,46,49,79,103,109):
            frames=normal_frames();frames['runtime-closed'][index]=0
            with self.subTest(index=index):self.assertEqual(self.parse(frames)['status'],'failed')

    def test_zero_equal_zero_cannot_replace_actual_work_or_tsfn(self):
        frames=normal_frames();frames['runtime-closed']=native(**{'1':4,'2':1,'7':1,'72':3})
        self.assertEqual(self.parse(frames)['status'],'failed')

    def test_sentinel_and_metadata_must_reach_zero(self):
        for index in (77,80,83,96,99):
            frames=normal_frames();frames['runtime-closed'][index]=1
            with self.subTest(index=index):self.assertEqual(self.parse(frames)['status'],'failed')

    def test_complete_requires_full_final_frame(self):
        frames=normal_frames();del frames['runtime-closed']
        self.assertEqual(self.parse(frames)['status'],'failed')
        self.assertEqual(self.parse(raw=log(normal_frames())+'\n10-25 12:00:00.000 123 456 I Probe: KOTLIN_FRAME nonce runtime-complete [1]')['status'],'failed')

    def test_negative_native_or_c178_not_a_kotlin_frame(self):
        frames=normal_frames();frames['runtime-open'][3]=-1
        self.assertEqual(self.parse(frames)['status'],'failed')
        frames['runtime-open']=[1]*178
        self.assertEqual(self.parse(frames)['status'],'failed')

    def test_scenario_inventory_has_independent_routes_only(self):
        self.assertEqual(len(SCENARIOS),31)
        self.assertTrue(all(name.startswith('kotlin-') for name in SCENARIOS))
        self.assertNotIn('worker-env-exit',SCENARIOS)
