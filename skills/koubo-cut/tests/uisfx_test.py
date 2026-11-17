"""Offline behavior and real audio-assembly compatibility; no Jianying app operations."""
import array
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sfx = module_at('uisfx', ROOT/'scripts/uisfx.py')
scenes = module_at('scene_pack', ROOT.parent/'package-talking-head-video/scripts/scene_pack.py')


class UISFXTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest, self.source, self.assets = sfx.catalog()
        self.plan = {'schema': 'uisfx-events/v1', 'fps': '30', 'total_frames': 90,
            'events': [{'id': 'impact', 'decision': 'sound', 'visual_action': '卡片快速移入并卡入槽位',
                'speech_context': '口播正在解释成本组成，语气平静', 'purpose': '让槽位卡住的瞬间可感知',
                'reason': '需要短而干脆的接触声，避免暗示购买成功', 'sound_id': 'studio/snap',
                'anchor_frame': 30, 'anchor_kind': 'contact', 'source_anchor_ms': 70, 'gain': .25,
                'start_frame': 0, 'end_frame': 90, 'scene_id': 'one'}]}

    def tearDown(self):
        self.temp.cleanup()

    def test_every_installed_audio_checksum_and_license(self):
        self.assertEqual(len(self.assets), 936)
        self.assertEqual(self.source['audio_license'], 'CC0-1.0')
        for asset in self.assets.values():
            sfx.source_file(asset, self.source)

    def test_default_catalog_excludes_loops(self):
        result = json.loads(subprocess.check_output([sys.executable, str(ROOT/'scripts/uisfx.py'), 'catalog']))
        self.assertEqual(result['count'], 864)
        self.assertTrue(all(not a['loop'] for a in result['assets']))

    def test_missing_context_unknown_id_and_loop_fail_before_output(self):
        invalid = [dict(self.plan['events'][0], speech_context=''),
                   dict(self.plan['events'][0], sound_id='money/automatic'),
                   dict(self.plan['events'][0], sound_id='studio/loading')]
        for event in invalid:
            with self.subTest(event=event):
                plan = dict(self.plan, events=[event])
                with self.assertRaises(ValueError):
                    sfx.prepare(plan, self.root/'invalid')
                self.assertFalse((self.root/'invalid').exists())

    def test_timing_and_nonfinite_values_are_rejected(self):
        for change in [{'anchor_frame': 0}, {'anchor_frame': 90}, {'source_anchor_ms': float('nan')},
                       {'gain': float('inf')}, {'anchor_frame': True}, {'source_anchor_ms': 99999}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                plan = copy.deepcopy(self.plan)
                plan['events'][0].update(change)
                sfx.validate_plan(plan, self.assets)

    def test_silence_does_not_invoke_decoder_or_manufacture_sound(self):
        event = {k:v for k,v in self.plan['events'][0].items()
                 if k not in ('sound_id', 'source_anchor_ms', 'gain', 'anchor_kind')}
        event.update(decision='silence', reason='解释本身足够清楚，此处声音会打断口播')
        with patch.object(sfx, 'ffmpeg_path', side_effect=AssertionError('silence needs no decoder')):
            result = sfx.prepare(dict(self.plan, events=[event]), self.root/'silent')
        self.assertEqual(result['sounds'], [])
        self.assertEqual(list((self.root/'silent').glob('*.wav')), [])

    def test_output_does_not_overwrite_or_enter_installed_skills(self):
        for destination in [self.root, ROOT/'assets/forbidden-project', scenes.ROOT/'work/forbidden']:
            with self.subTest(destination=destination), self.assertRaises((ValueError, FileExistsError)):
                sfx.prepare(self.plan, destination)

    def test_tampered_source_fails_without_changing_original(self):
        relative = self.assets['studio/snap']['files']['mp3']['path']
        path = self.root/relative
        path.parent.mkdir(parents=True)
        path.write_bytes(b'not the pinned CC0 file')
        with patch.object(sfx, 'BANK', self.root), self.assertRaisesRegex(ValueError, 'checksum'):
            sfx.source_file(self.assets['studio/snap'], self.source)

    def test_failed_decoding_leaves_no_partial_project_output(self):
        with patch.object(sfx, 'decode', side_effect=ValueError('decoder failed')):
            with self.assertRaisesRegex(ValueError, 'decoder failed'):
                sfx.prepare(self.plan, self.root/'failed')
        self.assertFalse((self.root/'failed').exists())
        self.assertEqual(list(self.root.glob('.uisfx-*')), [])

    def test_explicit_different_choices_and_silence_survive_identical_spoken_words(self):
        plan = copy.deepcopy(self.plan)
        second = dict(plan['events'][0], id='reveal', sound_id='glass/complete', anchor_frame=60,
                      visual_action='核算结果数字逐渐亮起', purpose='温和确认结果', reason='呈现明确结果')
        third = {k:v for k,v in second.items() if k not in ('sound_id','source_anchor_ms','gain','anchor_kind')}
        third.update(id='explain', decision='silence', anchor_frame=75, visual_action='图表静止供阅读', reason='保留阅读空间')
        plan['events'] += [second, third]
        result = sfx.prepare(plan, self.root/'context-choices')
        self.assertEqual([e['sound_id'] for e in result['sounds']], ['studio/snap', 'glass/complete'])
        self.assertEqual([e['decision'] for e in result['decisions']], ['sound', 'sound', 'silence'])
        self.assertEqual(len({e['speech_context'] for e in result['decisions']}), 1)

    def test_fractional_fps_preserves_anchor_within_half_frame(self):
        plan = dict(self.plan, fps='30000/1001')
        result = sfx.prepare(plan, self.root/'fractional')
        sound = result['sounds'][0]
        self.assertEqual(sound['peak_offset_frames'], 2)
        self.assertLessEqual(abs(sound['frame_rounding_error_ms']), 1000/(30000/1001)/2)
        self.assertAlmostEqual(result['draft_sounds'][0]['time'], (30-2)/(30000/1001))

    def test_real_existing_assembler_places_decoded_audio_at_expected_sample(self):
        ffmpeg = sfx.ffmpeg_path()
        resolved = sfx.prepare(self.plan, self.root/'prepared')
        sound = resolved['sounds'][0]
        self.assertEqual((sound['at_frame'], sound['peak_offset_frames']), (30, 2))
        (self.root/'input.srt').write_text('1\n00:00:00,000 --> 00:00:03,000\n合成验证\n')
        (self.root/'font.otf').write_bytes(b'font fixture; visual renderer is stubbed in this audio test')
        scene_plan = {'schema': 'sancheng-scenes/v1', 'srt': 'input.srt',
            'project': {'editor': 'jianying', 'width': 64, 'height': 64, 'fps': '30', 'total_frames': 90,
                'accent': '#FFD34E', 'foreground': '#FFFFFF',
                'font': {'family': 'Fixture', 'file': 'font.otf', 'weight': 700}},
            'scenes': [{'id':'one', 'start_frame':0, 'end_frame':90, 'recipe':'impact-title',
                'params': {'zone':[.1,.1,.8,.3], 'title':'fixture'}, 'assets':{}, 'depends_on':[]}],
            'sounds': resolved['sounds']}
        planfile = self.root/'scene-plan.json'
        planfile.write_text(json.dumps(scene_plan, ensure_ascii=False))
        self.assertEqual(scenes.load_plan(planfile)['sounds'][0]['path'], sound['path'])
        reviewed = self.root/'reviewed-scene-plan.json'
        sfx.bind_selection(planfile, self.root/'prepared/resolved.json', 'scene', reviewed)
        original_run = scenes.run

        def visual_fixture_only(argv):
            if len(argv) > 1 and Path(str(argv[1])) == scenes.RENDERER:
                target = argv[argv.index('--output')+1]
                original_run([ffmpeg,'-n','-v','error','-f','lavfi','-i',
                    'color=black@0:s=64x64:r=30:d=3,format=argb','-frames:v','90','-c:v','qtrle',target])
                return json.dumps({'frames':90})
            return original_run(argv)

        output = self.root/'assembled.mov'
        with patch.object(scenes, 'run', side_effect=visual_fixture_only):
            report = scenes.build(reviewed, self.root/'cache', output, ffmpeg, str(self.root/'font.otf'))
        self.assertFalse(report['imported_to_jianying'])
        self.assertEqual(report['uisfx_selection']['status'], 'completed')
        actual = subprocess.check_output([ffmpeg,'-v','error','-i',str(output),'-map','0:a:0',
                    '-f','s16le','-c:a','pcm_s16le','-'])
        expected = subprocess.check_output([ffmpeg,'-v','error','-i',sound['path'],'-af','volume=0.25',
                    '-f','s16le','-c:a','pcm_s16le','-'])
        delay_bytes = 44800*4  # (30 - 2) / 30 * 48000 stereo PCM16 frames.
        self.assertEqual(len(actual), 3*48000*4)
        self.assertEqual(actual[:delay_bytes], bytes(delay_bytes))
        left, right = array.array('h', actual[delay_bytes:delay_bytes+len(expected)]), array.array('h', expected)
        self.assertEqual(len(left), len(right))
        self.assertLessEqual(max(abs(a-b) for a,b in zip(left,right)), 1)
        self.assertEqual(actual[delay_bytes+len(expected):], bytes(len(actual)-delay_bytes-len(expected)))


if __name__ == '__main__':
    unittest.main()
