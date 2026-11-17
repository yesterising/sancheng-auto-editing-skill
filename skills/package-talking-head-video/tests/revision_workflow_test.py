"""Meaningful workflow boundaries, using temporary files rather than a live editor."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import revision_workflow as rw


class RevisionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old = self.record('old', b'old formal fixture')
        self.new = self.record('new', b'new formal fixture')
        self.target = self.save('target.json', {'editor':'jianying','project':'fixture',
            'material_id':'m1','media_path':str(self.root/'old.mov'),
            'placement':{'c1':{'start':0,'duration':30,'speed':1}},'observation':'isolated fixture, not native evidence'})
        self.request = self.save('request.json', {'id':'user-feedback-1','source':'user_message',
            'feedback':'只改标题，并请 AI 替换当前剪映对应素材', 'editor_action':'replace',
            'editor_action_authorized':True, 'authorization_quote':'请 AI 替换当前剪映对应素材'})

    def tearDown(self): self.temp.cleanup()

    def save(self, name, value):
        p = self.root/name; p.write_text(json.dumps(value)); return p

    def record(self, name, data):
        p = self.root/(name+'.mov'); p.write_bytes(data)
        return self.save(name+'.json', {'editor':'jianying','output':str(p),'sha256':rw.sp.digest(data),
            'width':640,'height':360,'frames':30,'fps':'10','sound_events':[],
            'scenes':[{'id':'a','key':'same','start_frame':0,'end_frame':10},
                      {'id':'b','key':name,'start_frame':10,'end_frame':30}]})

    def begin(self):
        return rw.begin_replacement(self.old,self.new,self.target,self.request,self.root/'ledger')

    def review(self, round_number=0):
        return self.save('review.json', {'formal_output':str(self.root/'new.mov'),
            'formal_sha256':rw.sp.digest((self.root/'new.mov').read_bytes()),'repair_round':round_number,
            'frames':[{'scene':'b','path':'frame-b.png'}], 'audio_samples':[]})

    def findings(self, status='pass'):
        return self.save('findings.json', {'visual_status':status,'audio_status':'not_applicable',
            'observations':[{'kind':'visual','evidence':'frame-b.png','finding':'fixture observation'}]})

    def test_only_changed_scene_is_reviewed_even_when_cached(self):
        old, new = rw.build_record(self.old), rw.build_record(self.new)
        new['scenes'][1]['status'] = 'reused'
        self.assertEqual(rw.changed_ranges(new, old, None), ([[10,30]],[]))

    def test_deleted_sound_review_includes_its_old_range(self):
        old, new = rw.build_record(self.old), rw.build_record(self.old)
        old['sound_events'] = [{'path':'old.wav','at_frame':15,'peak_offset_frames':2,'gain':1,
                                'effective_range_frames':[13,17]}]
        with patch.object(rw,'probe',return_value={'format':{'duration':'0.4'}}):
            self.assertEqual(rw.changed_ranges(new,old,None),([],[[13,17]]))

    def test_shortened_sound_at_same_path_keeps_the_old_tail_in_review(self):
        old, new = rw.build_record(self.old), rw.build_record(self.old)
        shared = {'path':'same.wav','at_frame':15,'peak_offset_frames':2,'gain':1}
        old['sound_events'] = [{**shared, 'sha256':'old-one-second', 'effective_range_frames':[13,23]}]
        new['sound_events'] = [{**shared, 'sha256':'new-tenth-second', 'effective_range_frames':[13,14]}]
        with patch.object(rw,'probe',return_value={'format':{'duration':'0.1'}}):
            self.assertEqual(rw.changed_ranges(new,old,None),([],[[13,23]]))

    def test_deleted_source_file_does_not_erase_its_recorded_sound_range(self):
        old, new = rw.build_record(self.old), rw.build_record(self.old)
        old['sound_events'] = [{'path':'no-longer-present.wav','at_frame':15,'peak_offset_frames':2,
                                'gain':1,'effective_range_frames':[13,23]}]
        with patch.object(rw,'probe',side_effect=FileNotFoundError('historical source removed')):
            self.assertEqual(rw.changed_ranges(new,old,None),([],[[13,23]]))

    def test_legacy_sound_without_recorded_range_covers_known_onset_to_end(self):
        old, new = rw.build_record(self.old), rw.build_record(self.old)
        old['sound_events'] = [{'path':'historical-source.wav','at_frame':15,'peak_offset_frames':2,'gain':1}]
        with patch.object(rw,'probe',side_effect=FileNotFoundError('historical source removed')):
            self.assertEqual(rw.changed_ranges(new,old,None),([],[[13,30]]))

    def test_legacy_range_fallback_is_explicitly_recorded(self):
        old, new = rw.build_record(self.old), rw.build_record(self.old)
        old['sound_events'] = [{'path':'historical-source.wav','at_frame':15,'peak_offset_frames':2,'gain':1}]
        fallbacks=[]
        with patch.object(rw,'probe',side_effect=AssertionError('must not read historical source')) as probe:
            self.assertEqual(rw.changed_ranges(new,old,None,fallbacks),([],[[13,30]]))
            probe.assert_not_called()
        self.assertEqual(fallbacks[0]['version'],'previous')
        self.assertEqual(fallbacks[0]['range_frames'],[13,30])
        self.assertIn('no recorded effective sound range',fallbacks[0]['reason'])

    def test_invalid_recorded_sound_range_is_rejected(self):
        old, new = rw.build_record(self.old), rw.build_record(self.old)
        for bounds in ([13,31],[14,13],[13,'23']):
            with self.subTest(bounds=bounds):
                old['sound_events'] = [{'path':'old.wav','at_frame':15,'peak_offset_frames':2,
                                        'gain':1,'effective_range_frames':bounds}]
                with self.assertRaises(ValueError):
                    rw.changed_ranges(new,old,None)

    def test_rendering_does_not_imply_visual_pass(self):
        with self.assertRaisesRegex(ValueError,'explicit'):
            rw.assess(self.review(),self.save('empty.json',{}),self.root/'assessment.json')

    def test_pass_is_not_user_acceptance(self):
        result=rw.assess(self.review(),self.findings(),self.root/'assessment.json')
        self.assertEqual(result['next_action'],'verify_delivery')
        self.assertEqual(result['user_acceptance'],'not_assessed')

    def test_repair_limit_stops_after_two_rounds(self):
        for n, expected in [(0,'revise'),(1,'revise'),(2,'stop_and_report')]:
            result=rw.assess(self.review(n),self.findings('issues'),self.root/f'assessment-{n}.json')
            self.assertEqual(result['next_action'],expected)

    def test_evidence_cannot_be_invented(self):
        f=self.save('bad.json',{'visual_status':'pass','audio_status':'not_applicable',
                              'observations':[{'kind':'visual','evidence':'other.png','finding':'fine'}]})
        with self.assertRaisesRegex(ValueError,'observations'):
            rw.assess(self.review(),f,self.root/'assessment.json')

    def test_unavailable_cannot_be_passed_as_success(self):
        f=self.save('unavailable.json',{'visual_status':'unavailable','visual_limitation':'viewer unavailable',
                                      'audio_status':'not_applicable'})
        self.assertEqual(rw.assess(self.review(),f,self.root/'assessment.json')['next_action'],'stop_and_report')

    def test_duplicate_request_is_consumed_before_native_action(self):
        result=self.begin()
        self.assertFalse(result['native_mutation_performed_by_helper'])
        with self.assertRaises(FileExistsError): self.begin()
        self.assertEqual((self.root/'old.mov').read_bytes(),b'old formal fixture')

    def test_ordinary_revision_does_not_authorize_editor_replacement(self):
        self.save('request.json', {'id':'ordinary-revision','source':'user_message','feedback':'只改标题'})
        with self.assertRaisesRegex(ValueError,'Explicit user authorization'):
            self.begin()
        self.assertFalse((self.root/'ledger').exists())

    def test_action_flag_without_user_operation_quote_is_rejected(self):
        request=rw.sp.read_json(self.request); request.pop('authorization_quote')
        self.save('request.json',request)
        with self.assertRaisesRegex(ValueError,'Explicit user authorization'):
            self.begin()

    def test_operation_quote_must_come_from_the_recorded_user_feedback(self):
        request=rw.sp.read_json(self.request); request['feedback']='只改标题'
        self.save('request.json',request)
        with self.assertRaisesRegex(ValueError,'Explicit user authorization'):
            self.begin()

    def test_failed_attempt_does_not_allow_retry(self):
        result=self.begin()
        o=self.save('observed.json',{'status':'failed','evidence':'fixture native failure'})
        rw.finish_replacement(result['claim'],o)
        with self.assertRaises(FileExistsError): self.begin()

    def test_success_requires_unchanged_placement(self):
        result=self.begin()
        o=self.save('observed.json',{'status':'succeeded','evidence':'fixture',
            'media_path':str(self.root/'new.mov'),'material_id':'m1','placement':{}})
        with self.assertRaisesRegex(ValueError,'same target/timing'):
            rw.finish_replacement(result['claim'],o)

    def test_success_receipt_is_explicitly_agent_recorded(self):
        result=self.begin(); target=rw.sp.read_json(self.target)
        o=self.save('observed.json',{'status':'succeeded','evidence':'fixture not actual native check',
            'media_path':str(self.root/'new.mov'),'material_id':'m1','placement':target['placement']})
        receipt=rw.finish_replacement(result['claim'],o)
        self.assertEqual(receipt['native_outcome'],'agent_recorded_not_independently_verified')
        with self.assertRaises(FileExistsError): rw.finish_replacement(result['claim'],o)

    def test_wrong_target_rejected_without_consuming_attempt(self):
        target=rw.sp.read_json(self.target); target['media_path']='wrong.mov'; self.save('target.json',target)
        with self.assertRaisesRegex(ValueError,'exact old'): self.begin()
        self.assertFalse((self.root/'ledger').exists())

    def test_timing_change_is_not_a_replacement(self):
        new=rw.sp.read_json(self.new); new['frames']=40; self.save('new.json',new)
        with self.assertRaisesRegex(ValueError,'timing'): self.begin()

    def test_modified_delivery_cannot_reuse_build_record(self):
        (self.root/'new.mov').write_bytes(b'modified after rendering')
        with self.assertRaisesRegex(ValueError,'changed since'): self.begin()

    def clip_target(self):
        target=rw.sp.read_json(self.target)
        target.update(replacement_mode='clip',clip_locator='fixture|timeline01|main|0..30')
        self.save('target.json',target)
        return target

    def clip_observation(self, target):
        return {'status':'succeeded','evidence':'unit fixture, not native evidence',
            'media_path':str(self.root/'new.mov'),'material_id':'m2',
            'clip_locator':target['clip_locator'],'placement':target['placement']}

    def test_native_clip_replace_may_create_new_material_identity(self):
        target=self.clip_target(); result=self.begin()
        receipt=rw.finish_replacement(result['claim'],self.save('observed.json',self.clip_observation(target)))
        self.assertEqual(receipt['status'],'succeeded')
        self.assertEqual(receipt['observation']['material_id'],'m2')

    def test_clip_replace_requires_same_unique_locator(self):
        target=self.clip_target(); result=self.begin(); observed=self.clip_observation(target)
        observed['clip_locator']='different clip'
        with self.assertRaisesRegex(ValueError,'same target/timing'):
            rw.finish_replacement(result['claim'],self.save('observed.json',observed))

    def test_clip_replace_cannot_change_source_in_point(self):
        target=self.clip_target(); target['placement']['c1']['source_in_frame']=10
        self.save('target.json',target); result=self.begin(); observed=self.clip_observation(target)
        observed['placement']['c1']['source_in_frame']=0
        with self.assertRaisesRegex(ValueError,'same target/timing'):
            rw.finish_replacement(result['claim'],self.save('observed.json',observed))

    def test_clip_replace_is_one_located_clip(self):
        target=self.clip_target(); target['placement']['c2']=target['placement']['c1']
        self.save('target.json',target)
        with self.assertRaisesRegex(ValueError,'one located timeline clip'): self.begin()
        self.assertFalse((self.root/'ledger').exists())

    def test_unknown_replace_mode_does_not_consume_attempt(self):
        target=rw.sp.read_json(self.target); target['replacement_mode']='guess'
        self.save('target.json',target)
        with self.assertRaisesRegex(ValueError,'replacement mode'): self.begin()
        self.assertFalse((self.root/'ledger').exists())

    def test_material_relink_still_requires_same_material_identity(self):
        result=self.begin(); target=rw.sp.read_json(self.target)
        observed={'status':'succeeded','evidence':'unit fixture','media_path':str(self.root/'new.mov'),
                  'material_id':'m2','placement':target['placement']}
        with self.assertRaisesRegex(ValueError,'same target/timing'):
            rw.finish_replacement(result['claim'],self.save('observed.json',observed))


if __name__=='__main__': unittest.main()
