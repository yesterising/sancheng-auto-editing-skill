"""Required selection stage blocks assembly without operating the live editor."""
import importlib.util
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sfx = module_at('required_uisfx', ROOT/'scripts/uisfx.py')
scenes = module_at('required_scene_pack', ROOT.parent/'package-talking-head-video/scripts/scene_pack.py')
draft = module_at('required_build_draft', ROOT/'scripts/build_draft.py')


class RequiredSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'input.srt').write_text('1\n00:00:00,000 --> 00:00:03,000\n解释这笔钱的成本组成\n')
        (self.root/'font.otf').write_bytes(b'font fixture; tests do not render')
        (self.root/'video.mov').write_bytes(b'video fixture; tests do not create native projects')
        self.scene = {'schema':'sancheng-scenes/v1', 'srt':str(self.root/'input.srt'),
            'project':{'editor':'jianying', 'width':64, 'height':64, 'fps':'30', 'total_frames':90,
                'font':{'family':'Fixture','file':str(self.root/'font.otf'),'weight':700},
                'accent':'#FFD34E','foreground':'#FFFFFF'},
            'scenes':[{'id':'one','start_frame':0,'end_frame':90,'recipe':'impact-title',
                'params':{'zone':[.1,.1,.8,.3],'title':'成本组成'}, 'assets':{},'depends_on':[]}],
            'sounds':[]}
        self.draft = {'srt':str(self.root/'input.srt'), 'font':'Fixture', 'fps':'30','total_frames':90,
            'video':str(self.root/'video.mov'), 'segments':[{'src':0,'end':3}], 'sounds':[]}
        self.events = {'schema':'uisfx-events/v1','fps':'30','total_frames':90,
            'events':[{'id':'explain','scene_id':'one','decision':'silence','start_frame':0,'end_frame':90,
                'anchor_frame':0,'visual_action':'成本图表保持静止供阅读',
                'speech_context':'解释成本组成，平静陈述而非购买成功', 'purpose':'保持口播与阅读清楚',
                'reason':'当前没有需加强的动作，安静更适合这一段'}]}

    def tearDown(self):
        self.temp.cleanup()

    def save(self, name, data):
        path = self.root/name
        path.write_text(json.dumps(data, ensure_ascii=False))
        return path

    def test_missing_selection_blocks_assembler_before_rendering(self):
        planfile = self.save('scene.json', self.scene)
        with patch.object(scenes, 'run', side_effect=AssertionError('renderer must not run')):
            with self.assertRaisesRegex(ValueError, 'UISFX selection'):
                scenes.build(planfile, self.root/'cache', self.root/'out.mov', sfx.ffmpeg_path(),
                             str(self.root/'font.otf'))
        self.assertFalse((self.root/'cache').exists())

    def test_empty_sound_track_is_not_a_silence_decision(self):
        with self.assertRaisesRegex(ValueError, 'UISFX selection'):
            draft.validate_plan(self.draft)

    def complete(self, mode='scene', audible=False):
        events = copy.deepcopy(self.events)
        if audible:
            events['events'][0].update(decision='sound', sound_id='studio/snap', anchor_frame=30,
                anchor_kind='contact', source_anchor_ms=70, gain=.25,
                visual_action='卡片落稳卡入槽位', purpose='强调实际接触', reason='短促的卡入声贴合落稳')
        report = sfx.prepare(events, self.root/'prepared')
        plan = copy.deepcopy(self.scene if mode == 'scene' else self.draft)
        plan['sounds'] = report['sounds'] if mode == 'scene' else report['draft_sounds']
        context = self.save('context.json', plan)
        output = self.root/'bound.json'
        sfx.bind_selection(context, self.root/'prepared/resolved.json', mode, output)
        return json.loads(output.read_text())

    def test_explicit_full_timeline_silence_is_completed(self):
        plan = self.complete()
        result = scenes.require_uisfx_selection(scenes.load_plan(self.save('checked.json', plan)))
        self.assertEqual(result, {'status':'completed','sound_events':0,'silence_decisions':1})

    def test_draft_accepts_reviewed_silence_without_loading_editor(self):
        plan = self.complete('draft')
        with patch.object(draft, 'load_runtime', side_effect=AssertionError('must not load editor')):
            self.assertEqual(draft.validate_plan(plan), [])

    def test_draft_audible_schedule_is_checked(self):
        plan = self.complete('draft', audible=True)
        self.assertEqual(len(draft.validate_plan(plan)), 1)
        plan['sounds'][0]['time'] += .1
        with self.assertRaisesRegex(ValueError, 'scheduled sounds differ'):
            draft.validate_plan(plan)

    def test_empty_decisions_and_unreviewed_ranges_cannot_be_bound(self):
        variants = [[], [dict(self.events['events'][0], start_frame=1, anchor_frame=1)],
                    [dict(self.events['events'][0], end_frame=89)]]
        for index, events in enumerate(variants):
            with self.subTest(events=events):
                sfx.prepare(dict(self.events, events=events), self.root/f'prepared-{index}')
                context = self.save('context.json', self.scene)
                with self.assertRaises(ValueError):
                    sfx.bind_selection(context, self.root/f'prepared-{index}/resolved.json',
                                       'scene', self.root/f'bound-{index}.json')
                self.assertFalse((self.root/f'bound-{index}.json').exists())

    def test_tampered_receipt_cannot_be_used(self):
        plan = self.complete()
        receipt = Path(plan['uisfx_selection']['receipt'])
        receipt.write_text(receipt.read_text()+' ')
        with self.assertRaisesRegex(ValueError, 'receipt is missing or changed'):
            sfx.validate_selection(plan)

    def test_changed_visual_or_srt_invalidates_previous_review(self):
        plan = self.complete()
        changed = copy.deepcopy(plan)
        changed['scenes'][0]['params']['title'] = '改成收益结果'
        with self.assertRaisesRegex(ValueError, 'stale'):
            sfx.validate_selection(changed)
        (self.root/'input.srt').write_text('1\n00:00:00,000 --> 00:00:03,000\n现在表达收益而不是成本\n')
        with self.assertRaisesRegex(ValueError, 'stale'):
            sfx.validate_selection(plan)

    def test_changed_visual_asset_invalidates_previous_review(self):
        (self.root/'chart.svg').write_text('<svg/>')
        self.scene['scenes'][0]['assets']['chart'] = str(self.root/'chart.svg')
        plan = self.complete()
        (self.root/'chart.svg').write_text('<svg width="100"/>')
        with self.assertRaisesRegex(ValueError, 'stale'):
            sfx.validate_selection(plan)

    def test_unreviewed_audio_and_changed_prepared_file_are_rejected(self):
        plan = self.complete(audible=True)
        changed = copy.deepcopy(plan)
        changed['sounds'][0]['gain'] = .9
        with self.assertRaisesRegex(ValueError, 'scheduled sounds differ'):
            sfx.validate_selection(changed)
        Path(plan['sounds'][0]['path']).write_bytes(b'changed WAV fixture')
        with self.assertRaisesRegex(ValueError, 'prepared audio changed'):
            sfx.validate_selection(plan)

    def test_srt_is_still_required_before_selection(self):
        self.scene.pop('srt')
        with self.assertRaisesRegex(ValueError, 'SRT is required'):
            scenes.build(self.save('missing-srt.json', self.scene), self.root/'cache', self.root/'out.mov',
                         sfx.ffmpeg_path(), str(self.root/'font.otf'))

    def test_mismatched_timing_cannot_be_bound(self):
        sfx.prepare(dict(self.events, fps='25'), self.root/'prepared')
        with self.assertRaisesRegex(ValueError, 'timing differs'):
            sfx.bind_selection(self.save('context.json', self.scene), self.root/'prepared/resolved.json',
                               'scene', self.root/'bound.json')

    def test_one_generic_decision_cannot_stand_in_for_multiple_visual_scenes(self):
        sfx.prepare(self.events, self.root/'prepared')
        self.scene['scenes'][0]['end_frame'] = 45
        self.scene['scenes'].append({**self.scene['scenes'][0], 'id':'two','start_frame':45,'end_frame':90})
        with self.assertRaisesRegex(ValueError, 'actual scene'):
            sfx.bind_selection(self.save('context.json', self.scene), self.root/'prepared/resolved.json',
                               'scene', self.root/'bound.json')


if __name__ == '__main__':
    unittest.main()
