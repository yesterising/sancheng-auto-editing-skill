"""Behavioral checks for local scene revisions; no Jianying app interaction."""
import copy
import importlib.util
import json
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/scene_pack.py'
spec = importlib.util.spec_from_file_location('scene_pack', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ScenePlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'input.srt').write_text('1\n00:00:00,000 --> 00:00:02,000\n合成验证字幕\n')
        (self.root/'font.otf').write_bytes(b'font fixture; unit tests do not render')
        self.plan = {
            'schema': 'sancheng-scenes/v1', 'srt': 'input.srt',
            'project': {'editor': 'jianying', 'width': 640, 'height': 360, 'fps': '10',
                        'total_frames': 20, 'accent': '#FFD34E', 'foreground': '#FFFFFF',
                        'font': {'family': 'Fixture', 'file': 'font.otf', 'weight': 700}},
            'scenes': [{'id': sid, 'start_frame': i*10, 'end_frame': (i+1)*10,
                        'recipe': 'impact-title', 'params': {'zone': [.1,.1,.8,.3], 'title': sid},
                        'assets': {}, 'depends_on': []} for i, sid in enumerate(['one', 'two'])],
            'sounds': [],
        }
        self.path = self.save('plan.json', self.plan)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, name, value):
        path = self.root/name
        path.write_text(json.dumps(value, ensure_ascii=False))
        return path

    def load(self, plan=None):
        return module.load_plan(self.save('input.json', plan or self.plan))

    def test_valid_complete_timeline(self):
        self.assertEqual(self.load()['project']['total_frames'], 20)

    def test_missing_srt_precedes_font_and_asset_reads(self):
        self.plan.pop('srt')
        self.plan['project']['font']['file'] = 'missing-font.otf'
        with self.assertRaisesRegex(ValueError, 'SRT is required'):
            self.load()

    def test_reject_gap(self):
        self.plan['scenes'][1]['start_frame'] = 11
        with self.assertRaisesRegex(ValueError, 'contiguous'):
            self.load()

    def test_reject_non_jianying_host(self):
        self.plan['project']['editor'] = 'other'
        with self.assertRaisesRegex(ValueError, 'editor=jianying'):
            self.load()

    def test_protected_region(self):
        self.plan['project']['protected_regions'] = [[.2,.2,.2,.2]]
        with self.assertRaisesRegex(ValueError, 'protected'):
            self.load()

    def test_cycle_rejected(self):
        self.plan['scenes'][0]['depends_on'] = ['two']
        self.plan['scenes'][1]['depends_on'] = ['one']
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            self.load()

    def test_local_patch_invalidates_one_scene_and_preserves_source(self):
        source = self.path.read_bytes()
        patch = self.save('patch.json', {'reason': '调整第一场标题', 'scenes': [{'id': 'one', 'params': {'title': '新重点'}}]})
        result = module.revise(self.path, patch, self.root/'v2.json')
        self.assertEqual(result['changed'], ['one'])
        self.assertEqual(result['reusable'], ['two'])
        self.assertEqual(self.path.read_bytes(), source)
        self.assertEqual(module.load_plan(self.root/'v2.json')['history'][-1]['status'], 'requested')

    def test_dependencies_invalidate_dependents(self):
        before = self.load()
        before['scenes'][1]['depends_on'] = ['one']
        after = copy.deepcopy(before)
        after['scenes'][0]['params']['title'] = 'changed'
        self.assertEqual(module.changed(before, after)['changed'], ['one', 'two'])

    def test_asset_content_changes_cache_key(self):
        (self.root/'image.svg').write_text('<svg/>')
        self.plan['scenes'][0]['assets']['evidence'] = 'image.svg'
        p = self.load()
        before = module.fingerprints(p)
        (self.root/'image.svg').write_text('<svg width="2"/>')
        after = module.fingerprints(p)
        self.assertNotEqual(before['one'], after['one'])
        self.assertEqual(before['two'], after['two'])

    def test_font_change_invalidates_all(self):
        p = self.load()
        before = module.fingerprints(p)
        (self.root/'font.otf').write_bytes(b'changed font fixture')
        after = module.fingerprints(p)
        self.assertTrue(all(before[k] != after[k] for k in before))

    def test_patch_cannot_change_project_or_timing(self):
        for patch in [{'reason':'x','project':{'fps':'12'}},
                      {'reason':'x','scenes':[{'id':'one','end_frame':9}]}]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                module.revise(self.path, self.save('patch.json', patch), self.root/'v2.json')
        self.assertFalse((self.root/'v2.json').exists())

    def test_unknown_id_and_noop_rejected(self):
        for patch in [{'reason':'x','scenes':[{'id':'unknown','params':{'title':'x'}}]},
                      {'reason':'x','scenes':[]}]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                module.revise(self.path, self.save('patch.json', patch), self.root/'v2.json')

    def test_patch_relative_asset_paths_survive_output_relocation(self):
        (self.root/'patches').mkdir()
        (self.root/'patches/image.svg').write_text('<svg/>')
        patch = self.save('patches/patch.json', {'reason':'换图','scenes':[{'id':'one','assets':{'image':'image.svg'}}]})
        module.revise(self.path, patch, self.root/'new-dir/v2.json')
        result = module.load_plan(self.root/'new-dir/v2.json')
        self.assertEqual(result['scenes'][0]['assets']['image'], str((self.root/'patches/image.svg').resolve()))

    def test_existing_revision_is_not_overwritten(self):
        output = self.root/'v2.json'
        output.write_text('keep me')
        patch = self.save('patch.json', {'reason':'x','scenes':[{'id':'one','params':{'title':'new'}}]})
        with self.assertRaises(FileExistsError):
            module.revise(self.path, patch, output)
        self.assertEqual(output.read_text(), 'keep me')

    def test_srt_beyond_timeline_rejected(self):
        (self.root/'input.srt').write_text('1\n00:00:00,000 --> 00:00:05,000\n不同步\n')
        with self.assertRaisesRegex(ValueError, 'SRT exceeds'):
            self.load()

    def test_network_assets_rejected(self):
        self.plan['scenes'][0]['assets']['image'] = 'https://example.com/file.png'
        with self.assertRaisesRegex(ValueError, 'local file path'):
            self.load()

    def sound_file(self, frames):
        path = self.root/'prepared.wav'
        with wave.open(str(path), 'wb') as stream:
            stream.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
            stream.writeframes(b'\0'*frames*4)
        return path

    def test_build_records_actual_sound_range_before_source_is_shortened(self):
        source = self.sound_file(48000)
        self.plan['sounds'] = [{'path':str(source),'at_frame':8,'peak_offset_frames':2,'gain':1}]
        self.plan['uisfx_selection'] = {'receipt':'isolated fixture; no production authorization'}
        self.save('plan.json',self.plan)
        executable = self.root/'ffmpeg-fixture'
        executable.write_bytes(b'fixture; no process is executed')
        def fake_run(args):
            if args[-1] == '--version':
                return 'node fixture'
            if '--output' in args:
                Path(args[args.index('--output')+1]).write_bytes(b'rendered scene fixture')
                return json.dumps({'frames':10})
            Path(args[-1]).write_bytes(b'assembled media fixture')
            return ''
        with patch.object(module,'require_uisfx_selection',return_value={'status':'completed'}), \
                patch.object(module,'run',side_effect=fake_run):
            result=module.build(self.path,self.root/'cache',self.root/'v1.mov',str(executable),str(self.path))
        original_hash=module.digest(source.read_bytes())
        self.sound_file(4800)
        recorded=module.read_json(str(self.root/'v1.mov')+'.build.json')['sound_events'][0]
        self.assertEqual(recorded['effective_range_frames'],[6,16])
        self.assertEqual(recorded['sha256'],original_hash)
        self.assertNotEqual(recorded['sha256'],module.digest(source.read_bytes()))
        self.assertEqual(result['sound_events'][0],recorded)

    def test_sound_range_uses_sample_rounding_and_clips_at_timeline_end(self):
        source = self.sound_file(48)
        event={'path':str(source),'at_frame':2,'peak_offset_frames':0,'gain':1}
        result=module.sound_event_records([event],Fraction(30000,1001),20)
        self.assertEqual(result[0]['effective_range_frames'],[1,3])
        self.sound_file(48000)
        result=module.sound_event_records([{**event,'at_frame':19}],Fraction(10),20)
        self.assertEqual(result[0]['effective_range_frames'],[19,20])


if __name__ == '__main__':
    unittest.main()
