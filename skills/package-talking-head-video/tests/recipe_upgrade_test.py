"""Observable timing, evidence and review contracts; no native editor or network."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import scene_pack as sp
import revision_workflow as rw


class RecipeUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'in.srt').write_text('1\n00:00:00,000 --> 00:00:04,000\n先检索，再处理，最后汇总\n')
        (self.root/'font.otf').write_bytes(b'font fixture, never rendered')
        self.plan = {'schema':'sancheng-scenes/v1','srt':'in.srt','project':{
            'editor':'jianying','width':640,'height':360,'fps':'30000/1001','total_frames':120,
            'accent':'#FFD34E','foreground':'#FFFFFF',
            'font':{'family':'Fixture','file':'font.otf','weight':700}},'sounds':[],
            'scenes':[{'id':'flow','start_frame':0,'end_frame':120,'recipe':'process-flow',
                'params':{'zone':[.1,.1,.8,.8],'steps':['检索','处理','汇总'],
                          'step_events':['search','process','result']},
                'events':{k:{'frame':f,'basis':'SRT 1；合成测试锚点'} for k,f in
                          [('search',0),('process',47),('result',91)]},'assets':{}}]}

    def tearDown(self): self.tmp.cleanup()

    def save(self, name='plan.json', value=None):
        p=self.root/name; p.write_text(json.dumps(self.plan if value is None else value)); return p

    def load(self): return sp.load_plan(self.save())

    def test_event_times_are_localized_from_one_absolute_timebase(self):
        self.plan['scenes'][0]['start_frame']=0
        p=self.load(); data=sp.scene_data(p,p['scenes'][0])
        self.assertEqual(data['events']['process'],47)
        self.assertEqual(data['params']['step_events'],['search','process','result'])

    def test_missing_duplicate_unsorted_and_out_of_range_events_fail(self):
        original=copy.deepcopy(self.plan)
        mutations=[lambda s:s['events'].pop('process'),
                   lambda s:s['params'].update(step_events=['search','search','result']),
                   lambda s:s['events']['process'].update(frame=119),
                   lambda s:s['events']['result'].update(frame=120),
                   lambda s:s['events']['process'].update(basis='')]
        for mutate in mutations:
            self.plan=copy.deepcopy(original); mutate(self.plan['scenes'][0])
            with self.subTest(plan=self.plan), self.assertRaises(ValueError): self.load()

    def test_srt_gate_still_precedes_new_geometry(self):
        self.plan['srt']='missing.srt'
        self.plan['scenes'][0]['assets']['geometry']='missing.json'
        with self.assertRaisesRegex(ValueError,'SRT is required'): self.load()

    def test_event_patch_invalidates_only_consuming_scene(self):
        self.plan['scenes'][0]['end_frame']=100
        self.plan['scenes'].append({'id':'tail','start_frame':100,'end_frame':120,
            'recipe':'impact-title','params':{'zone':[.1,.1,.8,.8],'title':'完成'},'assets':{}})
        before=self.save()
        patch=self.save('patch.json',{'reason':'只延后处理步骤','scenes':[{'id':'flow',
            'events':{'process':{'frame':54,'basis':'SRT 1；局部观察修订'}}}]})
        result=sp.revise(before,patch,self.root/'v2.json')
        self.assertEqual(result['changed'],['flow'])
        self.assertEqual(result['reusable'],['tail'])
        self.assertEqual(sp.read_json(before)['scenes'][0]['events']['process']['frame'],47)

    def test_declared_need_must_be_supported_or_explained(self):
        self.plan['scenes'][0]['needs']=['evidence']
        for invalid in (None, {}, ''):
            self.plan['scenes'][0]['coverage_note']=invalid
            with self.assertRaisesRegex(ValueError,'coverage'): self.load()
        self.plan['scenes'][0]['coverage_note']='本段只解释步骤；证据在下一镜单独展示'
        self.assertEqual(self.load()['scenes'][0]['needs'],['evidence'])

    def test_candidate_filter_explains_missing_real_inputs(self):
        result=sp.candidates('evidence',[])
        entry=next(r for r in result['rejected'] if r['id']=='source-conclusions')
        self.assertIn('image',entry['missing_assets'])
        result=sp.candidates('evidence',['image','geometry'])
        self.assertIn('source-conclusions',[r['id'] for r in result['candidates']])

    def test_geometry_is_bound_to_image_content_and_target_bounds(self):
        image=self.root/'page.png'; image.write_bytes(b'image fixture, no rendering')
        geometry={'schema':'sancheng-evidence/v1','image_sha256':sp.digest(image.read_bytes()),
            'width':800,'height':1200,'targets':{'line':[100,200,400,60]}}
        self.save('geometry.json',geometry)
        s=self.plan['scenes'][0]
        s.update(recipe='detail-overview',assets={'image':'page.png','geometry':'geometry.json'})
        s['params']={'zone':[.1,.1,.8,.8],'focus_target':'line','overview_events':['process','result']}
        self.assertEqual(self.load()['scenes'][0]['recipe'],'detail-overview')
        s['params']['image_fit']='cover'
        with self.assertRaisesRegex(ValueError,'contain'): self.load()
        s['params'].pop('image_fit')
        image.write_bytes(b'changed image at same path')
        with self.assertRaisesRegex(ValueError,'image hash'): self.load()
        image.write_bytes(b'image fixture, no rendering')
        geometry['targets']['line']=[799,200,400,60]; self.save('geometry.json',geometry)
        with self.assertRaisesRegex(ValueError,'target'): self.load()

    def test_review_uses_events_and_actual_fps_without_crossing_scene(self):
        p=self.load(); points,windows=rw.review_points(p['scenes'][0],p['project']['fps'])
        self.assertTrue({0,46,47,48,90,91,92,119}<=set(points))
        self.assertTrue(all(0<=f<120 for f in points))
        event=next(w for w in windows if w['event_id']=='process')
        self.assertEqual(event['range_frames'],[41,54])

    def test_recipe_with_unresolved_events_cannot_bypass_uisfx(self):
        p=self.load()
        with self.assertRaisesRegex(ValueError,'UISFX selection is required'):
            sp.require_uisfx_selection(p)

    def test_scene_level_pass_cannot_hide_an_unobserved_event(self):
        media=self.root/'formal.mov'; media.write_bytes(b'formal fixture')
        review={'formal_output':str(media),'formal_sha256':sp.digest(media.read_bytes()),
            'repair_round':0,'frames':[{'scene':'flow','frame':0,'path':'first.png'},
                                     {'scene':'flow','frame':47,'path':'second.png'}],
            'audio_samples':[],'event_windows':[{'scene':'flow','event_id':'process','frame':47,'path':'event.mov'}]}
        findings={'visual_status':'pass','audio_status':'not_applicable','observations':[
            {'kind':'visual','evidence':'first.png','finding':'Only the opening was inspected'}]}
        with self.assertRaisesRegex(ValueError,'event process'):
            rw.assess(self.save('review.json',review),self.save('findings.json',findings),self.root/'assessed.json')
        findings['observations'].append({'kind':'visual','evidence':'second.png','finding':'The process activation was inspected'})
        result=rw.assess(self.save('review.json',review),self.save('findings.json',findings),self.root/'assessed.json')
        self.assertEqual(result['user_acceptance'],'not_assessed')


if __name__=='__main__': unittest.main()
