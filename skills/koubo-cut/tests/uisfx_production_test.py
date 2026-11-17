"""Real production-plan binding without a scene renderer, fake font, or native draft."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
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


sfx = module_at('production_uisfx', ROOT/'scripts/uisfx.py')


class ProductionSelectionTests(unittest.TestCase):
    def setUp(self):
        if not os.environ.get('KOUBO_FFMPEG'):
            existing = shutil.which('ffmpeg') or '/Applications/ChatCut.app/Contents/Resources/app.asar.unpacked/node_modules/ffmpeg-ffprobe-static/ffmpeg'
            if Path(existing).is_file():
                environment = patch.dict(os.environ, {'KOUBO_FFMPEG':existing})
                environment.start()
                self.addCleanup(environment.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root/'source.mov').write_bytes(b'actual source identity fixture; no render or UI')
        (self.root/'input.srt').write_text('1\n00:00:00,000 --> 00:00:03,000\n解释加工过程\n')
        (self.root/'scene.blend').write_bytes(b'actual declared Blender dependency fixture')
        self.plan = {'srt':'input.srt', 'source':'source.mov',
            'project':{'fps':'30', 'total_frames':90},
            'scenes':[{'id':'one','start_frame':0,'end_frame':90,
                'renderer':'blender', 'assets':{'project':'scene.blend'},
                'layout':{'presenter':'circle-small'},
                'source_map':[{'timeline_start':0,'timeline_end':90,'source_in':0,'speed':1}]}],
            'sounds':[]}
        self.events = {'schema':'uisfx-events/v1','fps':'30','total_frames':90,
            'events':[{'id':'explain','scene_id':'one','decision':'silence','start_frame':0,'end_frame':90,
                'anchor_frame':0,'visual_action':'加工场景保持静止供阅读',
                'speech_context':'解释加工过程，平静说明机制', 'purpose':'保持口播与阅读清楚',
                'reason':'此段无需强化动作，声音留白'}]}

    def tearDown(self):
        self.temp.cleanup()

    def save(self, name, value):
        path = self.root/name
        path.write_text(json.dumps(value, ensure_ascii=False))
        return path

    def bind(self, plan=None, events=None, name='bound'):
        receipt = self.root/(name+'-prepared')
        resolved = sfx.prepare(copy.deepcopy(events or self.events), receipt)
        value = copy.deepcopy(plan or self.plan)
        value['sounds'] = resolved['sounds']
        context = self.save(name+'-context.json', value)
        target = self.root/(name+'.json')
        sfx.bind_selection(context, receipt/'resolved.json', 'production', target)
        return sfx.load_context(target, 'production')

    def test_real_plan_roundtrip_needs_no_font_html_or_native_runtime(self):
        with patch.object(sfx,'load_module',side_effect=AssertionError('no renderer or draft adapter')):
            with patch.object(sfx,'ffmpeg_path',side_effect=AssertionError('silence needs no decoder')):
                plan = self.bind()
                result = sfx.validate_selection(plan,'production')
        self.assertEqual(result,{'status':'completed','sound_events':0,'silence_decisions':1})
        self.assertEqual(plan['scenes'][0]['renderer'],'blender')
        self.assertEqual(plan['scenes'][0]['source_map'],self.plan['scenes'][0]['source_map'])
        self.assertEqual(plan['source'],str(self.root/'source.mov'))
        self.assertEqual(plan['scenes'][0]['assets']['project'],str(self.root/'scene.blend'))
        self.assertNotIn('font',plan['project'])
        self.assertNotIn('html',plan['scenes'][0])

    def test_readable_srt_is_checked_before_source_project_or_assets(self):
        invalid = copy.deepcopy(self.plan)
        invalid.update(srt='missing.srt', source='missing-source.mov', project=None)
        with patch.object(sfx,'load_module',side_effect=AssertionError('no native adapter')):
            with self.assertRaisesRegex(ValueError,'SRT'):
                sfx.load_context(self.save('missing-srt.json',invalid),'production')
        (self.root/'bad.srt').write_bytes(b'\xff\xfe\x00')
        invalid['srt']='bad.srt'
        with self.assertRaisesRegex(ValueError,'SRT'):
            sfx.load_context(self.save('bad-srt.json',invalid),'production')

    def test_srt_beyond_project_duration_is_not_bound(self):
        (self.root/'input.srt').write_text('1\n00:00:00,000 --> 00:00:04,000\n解释加工过程\n')
        with self.assertRaisesRegex(ValueError,'SRT exceeds'):
            self.bind()

    def test_missing_real_source_and_declared_assets_are_rejected(self):
        for field in ('source','asset'):
            with self.subTest(field=field):
                plan=copy.deepcopy(self.plan)
                if field=='source':plan['source']='missing.mov'
                else:plan['scenes'][0]['assets']['project']='missing.blend'
                with self.assertRaises(ValueError):
                    sfx.load_context(self.save('missing-'+field+'.json',plan),'production')

    def test_scene_ranges_must_really_cover_the_full_timeline(self):
        variants = [[],[dict(self.plan['scenes'][0],start_frame=1)],
                    [dict(self.plan['scenes'][0],end_frame=89)],
                    [dict(self.plan['scenes'][0],end_frame=50),dict(self.plan['scenes'][0],id='two',start_frame=49)],
                    [dict(self.plan['scenes'][0],end_frame=45),dict(self.plan['scenes'][0],start_frame=45)]]
        for i,scenes in enumerate(variants):
            with self.subTest(scenes=scenes),self.assertRaises(ValueError):
                sfx.load_context(self.save(f'bad-scenes-{i}.json',dict(self.plan,scenes=scenes)),'production')

    def test_decisions_stay_with_their_real_scene(self):
        plan=copy.deepcopy(self.plan)
        plan['scenes'][0]['end_frame']=45
        plan['scenes'].append(dict(plan['scenes'][0],id='two',start_frame=45,end_frame=90))
        with self.assertRaisesRegex(ValueError,'actual scene'):
            self.bind(plan=plan)

    def test_explicit_silence_must_cover_all_frames(self):
        for i,update in enumerate(({'start_frame':1,'anchor_frame':1},{'end_frame':89})):
            events=copy.deepcopy(self.events);events['events'][0].update(update)
            with self.subTest(update=update),self.assertRaisesRegex(ValueError,'complete timeline'):
                self.bind(events=events,name=f'partial-{i}')

    def test_actual_source_content_invalidates_binding_even_with_same_stat(self):
        plan=self.bind();source=self.root/'source.mov';stat=source.stat()
        source.write_bytes(b'x'*stat.st_size)
        os.utime(source,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'stale'):
            sfx.validate_selection(plan,'production')

    def test_actual_srt_and_asset_contents_invalidate_binding(self):
        plan=self.bind()
        (self.root/'input.srt').write_text('1\n00:00:00,000 --> 00:00:03,000\n现在解释结果\n')
        with self.assertRaisesRegex(ValueError,'stale'):
            sfx.validate_selection(plan,'production')
        (self.root/'input.srt').write_text('1\n00:00:00,000 --> 00:00:03,000\n解释加工过程\n')
        (self.root/'scene.blend').write_bytes(b'changed declared scene contents')
        with self.assertRaisesRegex(ValueError,'stale'):
            sfx.validate_selection(plan,'production')

    def test_source_mapping_renderer_fields_and_plan_history_are_bound(self):
        plan=self.bind()
        variants=[]
        changed=copy.deepcopy(plan);changed['scenes'][0]['source_map'][0]['source_in']=10;variants.append(changed)
        changed=copy.deepcopy(plan);changed['scenes'][0]['layout']['presenter']='rect-large';variants.append(changed)
        changed=copy.deepcopy(plan);changed['scenes'][0]['renderer']='ffmpeg';variants.append(changed)
        changed=copy.deepcopy(plan);changed['history']=[{'reason':'new actual version'}];variants.append(changed)
        for changed in variants:
            with self.subTest(changed=changed),self.assertRaisesRegex(ValueError,'stale'):
                sfx.validate_selection(changed,'production')

    def test_optional_font_and_top_level_dependencies_are_bound_when_declared(self):
        (self.root/'font.otf').write_bytes(b'font dependency fixture')
        (self.root/'global.svg').write_text('<svg/>')
        plan=copy.deepcopy(self.plan)
        plan['project']['font']={'file':'font.otf','family':'Actual selected font'}
        plan['assets']={'diagram':'global.svg'}
        bound=self.bind(plan=plan)
        self.assertEqual(bound['project']['font']['file'],str(self.root/'font.otf'))
        (self.root/'global.svg').write_text('<svg width="100"/>')
        with self.assertRaisesRegex(ValueError,'stale'):
            sfx.validate_selection(bound,'production')

    def test_audible_prepare_schedule_uses_the_same_existing_sound_contract(self):
        events=copy.deepcopy(self.events)
        events['events'][0].update(decision='sound',sound_id='studio/snap',anchor_frame=30,
            anchor_kind='contact',source_anchor_ms=70,gain=.25,
            visual_action='物件落稳接触台面',purpose='加强实际接触',reason='短促接触声与动作一致')
        plan=self.bind(events=events)
        self.assertEqual(sfx.validate_selection(plan,'production')['sound_events'],1)
        self.assertEqual(plan['sounds'][0]['peak_offset_frames'],2)
        plan['sounds'][0]['gain']=.5
        with self.assertRaisesRegex(ValueError,'stale|scheduled sounds differ'):
            sfx.validate_selection(plan,'production')

    def test_cli_bind_and_check_accept_production_without_rendering(self):
        sfx.prepare(self.events,self.root/'cli-prepared')
        context=self.save('cli-context.json',self.plan)
        bound=self.root/'cli-bound.json'
        base=[sys.executable,str(ROOT/'scripts/uisfx.py')]
        result=subprocess.run(base+['bind','--context',str(context),'--receipt',str(self.root/'cli-prepared/resolved.json'),
            '--mode','production','--out',str(bound)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        checked=subprocess.run(base+['check','--context',str(bound),'--mode','production'],capture_output=True,text=True)
        self.assertEqual(checked.returncode,0,checked.stderr)
        self.assertEqual(json.loads(checked.stdout)['silence_decisions'],1)

    def test_finalizer_accepts_the_actual_production_context_mode(self):
        fixtures=module_at('production_handoff_fixture',ROOT.parent/'video-editing-playbook/tests/finalize_delivery_test.py')
        fixture=fixtures.HandoffTests('runTest');fixture.setUp()
        try:
            plan={'srt':fixture.srt['path'],'source':fixture.source['path'],
                'project':{'fps':'5','total_frames':5},
                'scenes':[{'id':'one','start_frame':0,'end_frame':5,'renderer':'blender',
                    'source_map':[{'timeline_start':0,'timeline_end':5,'source_in':0,'speed':1}]}],
                'sounds':[]}
            ref=fixture.bind_plan(plan,'actual-blender-plan',mode='production')
            fixture.replace_plan(ref)
            fixture.manifest['uisfx_mode']='production'
            result=fixtures.gate.check(fixture.manifest)
            self.assertTrue(result['delivery_ready'])
        finally:
            fixture.tearDown()


if __name__=='__main__':
    unittest.main()
