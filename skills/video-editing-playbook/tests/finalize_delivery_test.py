"""Handoff records are unit fixtures; one separate test uses actual local QTRLE decoding."""
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

ROOT = Path(__file__).resolve().parents[1]


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = module_at('finalize_delivery', ROOT / 'scripts/finalize_delivery.py')
verify = module_at('verify_delivery', ROOT / 'scripts/verify_delivery.py')
sfx = module_at('handoff_uisfx', ROOT.parent / 'koubo-cut/scripts/uisfx.py')


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.file('source.mov', b'source media unit fixture, not a codec proof')
        self.srt = self.file('source.srt', b'1\n00:00:00,000 --> 00:00:01,000\nTest\n')
        self.frame = self.file('frame.png', b'isolated evidence fixture, not visual acceptance')
        self.media = self.file('新包装 [修订] 空格.mov', b'formal media unit fixture, not a codec proof')
        self.manifest = {'schema': 'jianying-handoff/v1', 'job_id': 'job-one', 'version_id': 'v2',
            'operation': 'initial', 'product': 'overlay', 'source': self.source, 'srt': self.srt,
            'assets': [], 'project': {'width': 16, 'height': 16, 'fps': '5', 'total_frames': 5}}
        font = self.file('fixture-font.otf', b'font context fixture; tests do not render glyphs')
        self.plan = {'schema': 'sancheng-scenes/v1', 'srt': self.srt['path'],
            'project': {'editor': 'jianying', 'width': 16, 'height': 16, 'fps': '5', 'total_frames': 5,
                'font': {'family': 'Fixture', 'file': font['path'], 'weight': 700},
                'accent': '#FFD34E', 'foreground': '#FFFFFF'},
            'scenes': [{'id': 'one', 'start_frame': 0, 'end_frame': 5, 'recipe': 'impact-title',
                'params': {'zone': [.1, .1, .8, .3], 'title': 'Test'},
                'assets': {'source': self.source['path']}, 'depends_on': []}], 'sounds': []}
        self.production = self.bind_plan(self.plan, 'initial-plan')
        self.manifest.update(production_plan=self.production, uisfx_mode='scene')
        inputs = [self.source, self.srt]
        timeline = self.review(inputs + [self.production, self.media])
        timeline.update(anchors=[self.anchor()], required_motion_ranges=[
            {'file_id': 'main', 'start_frame': 0, 'end_frame': 5, 'risk': 'high'}])
        srt_match = self.review(inputs + [self.production])
        srt_match['anchors'] = [self.anchor()]
        compatibility = self.review([self.media])
        compatibility.update(current_version='11.6.fixture', basis_version='11.6.fixture',
            profile={'container': 'mov', 'codec': 'qtrle', 'pix_fmt': 'argb', 'audio': 'none',
                     'colour': 'fixture', 'hdr': False},
            change_assessment='Unit fixture, not native compatibility evidence', revalidation_required=False)
        self.manifest['checks'] = {'assets': self.review(inputs), 'timeline': timeline,
                                   'srt_match': srt_match, 'compatibility': compatibility,
                                   'visual_references': self.visual_review([self.production, self.media])}
        tech = self.technical(self.media)
        motion = self.review([self.media], evidence=[self.media])
        motion.update(start_frame=0, end_frame=5, method='continuous')
        self.manifest['files'] = [{**self.media, 'id': 'main', 'kind': 'overlay', 'label': '新版 [包装]',
            'role': 'main', 'layer': 1, 'audio': 'absent', 'alignment_frame': 0,
            'disposition': 'new', 'previous_files': [], 'technical_report': tech,
            'content_review': self.review([self.media]), 'motion_reviews': [motion]}]

    def tearDown(self):
        self.temp.cleanup()

    def file(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return {'path': str(path.resolve()), 'sha256': gate.sha256(path)}

    def save(self, name, value):
        return self.file(name, json.dumps(value, ensure_ascii=False).encode())

    def review(self, targets, evidence=None):
        return {'job_id': 'job-one', 'version_id': 'v2', 'status': 'pass',
                'finding': 'Explicit unit-fixture observation, not actual visual acceptance',
                'targets': copy.deepcopy(targets), 'evidence': copy.deepcopy(evidence or [self.frame])}

    def visual_review(self, targets):
        value = self.review(targets)
        value.update(scope='researched', materials=[{'noun': 'Fixture title', 'purpose': 'Unit test layout'}],
            searches={site: {'status': 'pass', 'method': method, 'queries': ['fixture title layout'],
                            'evidence': [self.frame]}
                      for site, method in [('pinterest', 'browser'), ('cosmos', 'mcp')]},
            selected_references=[{'url': 'https://www.cosmos.so/e/61898117',
                                  'image_evidence': [self.frame], 'takeaway': 'Fixture hierarchy observation'}],
            design_rules='Fixture: one title with consistent type, colour, shape and flat lighting',
            comparison='Fixture output compared to its reference; not actual aesthetic acceptance')
        return value

    def bind_plan(self, plan, name, mode='scene'):
        project = plan['project'] if mode in ('scene', 'production') else plan
        decisions = {'schema': 'uisfx-events/v1', 'fps': project['fps'], 'total_frames': project['total_frames'],
            'events': [{'id': 'quiet', 'scene_id': 'one', 'decision': 'silence',
                'start_frame': 0, 'end_frame': project['total_frames'], 'anchor_frame': 0,
                'visual_action': '测试画面保持稳定用于读取内容', 'speech_context': 'Test 的独立测试口播',
                'purpose': '保持口播清楚', 'reason': '该段没有需要强化的声音动作'}]}
        sfx.prepare(decisions, self.root / (name + '-selection'))
        context = self.save(name + '-context.json', plan)
        bound = self.root / (name + '-bound.json')
        sfx.bind_selection(context['path'], self.root / (name + '-selection/resolved.json'), mode, bound)
        return {'path': str(bound), 'sha256': gate.sha256(bound)}

    def replace_plan(self, ref):
        old = self.manifest['production_plan']
        self.manifest['production_plan'] = ref
        for key in ('timeline', 'srt_match', 'visual_references'):
            self.manifest['checks'][key]['targets'] = [ref if value['path'] == old['path'] else value
                                                      for value in self.manifest['checks'][key]['targets']]

    def add_auxiliary(self, previous_files=None, layer_change='added'):
        ref = self.file('auxiliary-v2.mov', b'new auxiliary fixture')
        report = json.loads(Path(self.manifest['files'][0]['technical_report']['path']).read_text())
        report.update(file=ref['path'], sha256=ref['sha256'])
        item = {**ref, 'id': 'auxiliary', 'kind': 'overlay', 'label': 'Auxiliary', 'role': 'auxiliary',
            'layer': 2, 'audio': 'absent', 'alignment_frame': 0, 'disposition': 'new',
            'layer_change': layer_change, 'previous_files': previous_files or [],
            'technical_report': self.save('auxiliary-technical.json', report),
            'content_review': self.review([ref]), 'motion_reviews': []}
        self.manifest['files'].append(item)
        self.manifest['checks']['timeline']['targets'].append(ref)
        self.manifest['checks']['compatibility']['targets'].append(ref)
        self.manifest['checks']['visual_references']['targets'].append(ref)
        return item

    def anchor(self):
        return {'timeline_frame': 0, 'source_frame': 0, 'srt_cue': '1',
                'finding': 'Fixture cue corresponds to the declared timeline start', 'evidence': [self.frame]}

    def technical(self, media, kind='overlay', audio='absent'):
        report = {'schema': 'jianying-delivery-technical/v1', 'status': 'technical_pass',
            'file': media['path'], 'sha256': media['sha256'], 'full_decode': 'pass',
            'expected': {'kind': kind, 'width': 16, 'height': 16, 'fps': '5', 'frames': 5, 'audio': audio},
            'decoded_video_frames': None if kind == 'audio' else 5,
            'streams': ([] if kind == 'audio' else [{'codec_type': 'video'}]) +
                       ([{'codec_type': 'audio'}] if audio == 'present' else []),
            'alpha_samples': [{'frame': 0, 'alpha_min': 0, 'alpha_max': 255}] if kind == 'overlay' else []}
        return self.save('technical-' + kind + '.json', report)

    def test_ready_links_are_bound_to_the_current_file_with_unicode_spaces_and_brackets(self):
        result = gate.check(self.manifest)
        self.assertTrue(result['delivery_ready'])
        self.assertEqual(result['files'][0]['sha256'], self.media['sha256'])
        self.assertEqual(result['links'], ['[新版 \\[包装\\]](<' + self.media['path'] + '>)'])
        self.assertEqual(result['user_performs'], ['import', 'placement', 'replacement'])
        self.assertFalse(result['post_import_review'])

    def test_missing_visual_reference_step_blocks_links(self):
        self.manifest['checks'].pop('visual_references')
        path = self.save('missing-visual-research.json', self.manifest)['path']
        result = gate.finalize(path, self.root / 'missing-visual-result.json')
        self.assertFalse(result['delivery_ready'])
        self.assertEqual(result['links'], [])

    def test_both_reference_sources_must_have_search_evidence(self):
        for platform in ('pinterest', 'cosmos'):
            for mutation in ('missing', 'failed', 'no-query', 'no-evidence'):
                manifest = copy.deepcopy(self.manifest)
                searches = manifest['checks']['visual_references']['searches']
                if mutation == 'missing':
                    searches.pop(platform)
                elif mutation == 'failed':
                    searches[platform]['status'] = 'unavailable'
                elif mutation == 'no-query':
                    searches[platform]['queries'] = []
                else:
                    searches[platform]['evidence'] = []
                with self.subTest(platform=platform, mutation=mutation), self.assertRaisesRegex(ValueError, 'Visual-reference'):
                    gate.check(manifest)

    def test_browser_cosmos_does_not_count_as_mcp_search(self):
        self.manifest['checks']['visual_references']['searches']['cosmos']['method'] = 'browser'
        with self.assertRaisesRegex(ValueError, 'Cosmos MCP'):
            gate.check(self.manifest)

    def test_reference_urls_do_not_replace_actual_image_evidence(self):
        selected = self.manifest['checks']['visual_references']['selected_references'][0]
        selected['image_evidence'] = []
        with self.assertRaisesRegex(ValueError, 'image evidence'):
            gate.check(self.manifest)
        selected['image_evidence'] = [self.srt]
        with self.assertRaisesRegex(ValueError, 'image evidence'):
            gate.check(self.manifest)

    def test_visual_reference_materials_rules_and_comparison_cannot_be_omitted(self):
        for field, empty in [('materials', []), ('design_rules', ''), ('comparison', '')]:
            manifest = copy.deepcopy(self.manifest)
            manifest['checks']['visual_references'][field] = empty
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Visual-reference'):
                gate.check(manifest)

    def test_reused_visual_references_require_reason_and_original_evidence(self):
        value = self.manifest['checks']['visual_references']
        value['scope'] = 'reused'
        with self.assertRaisesRegex(ValueError, 'reuse reason'):
            gate.check(self.manifest)
        value['reuse_reason'] = 'Same title, style and source; current output compared again'
        self.assertTrue(gate.check(self.manifest)['delivery_ready'])
        value['searches']['pinterest']['evidence'] = []
        with self.assertRaisesRegex(ValueError, 'Visual-reference'):
            gate.check(self.manifest)

    def test_no_new_visuals_requires_explicit_reason_and_empty_materials(self):
        value = self.manifest['checks']['visual_references']
        value['scope'] = 'not_required'
        with self.assertRaisesRegex(ValueError, 'reason'):
            gate.check(self.manifest)
        value['reason'] = 'Only audio levels changed; visuals and existing design are unchanged'
        with self.assertRaisesRegex(ValueError, 'materials'):
            gate.check(self.manifest)
        value['materials'] = []
        self.assertTrue(gate.check(self.manifest)['delivery_ready'])

    def test_visual_reference_review_must_bind_current_plan_and_output(self):
        self.manifest['checks']['visual_references']['targets'] = [self.production]
        with self.assertRaisesRegex(ValueError, 'targets'):
            gate.check(self.manifest)

    def test_wrong_version_observation_without_hash_based_reuse_is_rejected(self):
        self.manifest['checks']['assets']['version_id'] = 'v1'
        with self.assertRaisesRegex(ValueError, 'reuse reason'):
            gate.check(self.manifest)

    def test_content_identical_evidence_can_be_reused_only_with_explicit_reason(self):
        review = self.manifest['checks']['assets']
        review.update(version_id='v1', reuse_reason='Source and SRT exact content hashes are unchanged')
        self.assertTrue(gate.check(self.manifest)['delivery_ready'])

    def test_reused_wrong_content_hash_is_rejected(self):
        review = self.manifest['checks']['assets']
        review.update(version_id='v1', reuse_reason='Claimed reuse', targets=[self.media])
        with self.assertRaisesRegex(ValueError, 'current content hashes'):
            gate.check(self.manifest)

    def test_render_or_technical_pass_does_not_replace_missing_content_observation(self):
        self.manifest['files'][0]['content_review']['finding'] = ''
        with self.assertRaisesRegex(ValueError, 'concrete text'):
            gate.check(self.manifest)

    def test_missing_evidence_cannot_pass(self):
        self.manifest['checks']['timeline']['evidence'] = []
        with self.assertRaisesRegex(ValueError, 'readable evidence'):
            gate.check(self.manifest)

    def test_changed_evidence_and_final_media_are_rejected(self):
        for target in (self.frame, self.media):
            old = Path(target['path']).read_bytes()
            Path(target['path']).write_bytes(b'changed')
            with self.subTest(target=target['path']), self.assertRaisesRegex(ValueError, 'changed'):
                gate.check(self.manifest)
            Path(target['path']).write_bytes(old)

    def test_wrong_file_technical_report_is_rejected(self):
        ref = self.manifest['files'][0]['technical_report']
        data = json.loads(Path(ref['path']).read_text())
        data['file'] = self.source['path']
        self.manifest['files'][0]['technical_report'] = self.save('wrong-file.json', data)
        with self.assertRaisesRegex(ValueError, 'another file/version'):
            gate.check(self.manifest)

    def test_width_height_fps_and_total_frames_cannot_drift(self):
        for key, value in [('width', 32), ('height', 32), ('fps', '6'), ('total_frames', 6)]:
            manifest = copy.deepcopy(self.manifest)
            manifest['project'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.check(manifest)

    def test_revision_requires_a_new_path_and_preserved_previous_file(self):
        self.manifest['operation'] = 'revision'
        item = self.manifest['files'][0]
        with self.assertRaisesRegex(ValueError, 'identify the preserved previous'):
            gate.check(self.manifest)
        item['previous_files'] = [self.media]
        with self.assertRaisesRegex(ValueError, 'preserve source and previous'):
            gate.check(self.manifest)
        previous = self.file('old.mov', b'old immutable delivery')
        item['previous_files'] = [previous]
        self.assertTrue(gate.check(self.manifest)['delivery_ready'])
        self.assertEqual(Path(previous['path']).read_bytes(), b'old immutable delivery')

    def test_redo_cannot_reuse_old_main_delivery_as_an_auxiliary_reuse(self):
        self.manifest['operation'] = 'redo'
        self.manifest['files'][0].update(disposition='reused', reuse_reason='same file')
        with self.assertRaisesRegex(ValueError, 'Main delivery must be new'):
            gate.check(self.manifest)

    def test_source_media_cannot_become_the_new_delivery(self):
        self.manifest['assets'] = [self.media]
        inputs = [self.source, self.srt, self.media]
        self.manifest['checks']['assets'] = self.review(inputs)
        self.manifest['checks']['timeline']['targets'] = inputs + [self.production, self.media]
        with self.assertRaisesRegex(ValueError, 'preserve source'):
            gate.check(self.manifest)

    def test_new_main_cannot_collide_with_an_old_auxiliary_path(self):
        self.manifest['operation'] = 'revision'
        self.manifest['files'][0]['previous_files'] = [self.file('previous-main.mov', b'old main')]
        self.add_auxiliary(previous_files=[self.media], layer_change='updated')
        with self.assertRaisesRegex(ValueError, 'previous delivery'):
            gate.check(self.manifest)

    def test_updated_auxiliary_requires_its_previous_identity_and_added_has_none(self):
        self.manifest['operation'] = 'redo'
        self.manifest['files'][0]['previous_files'] = [self.file('previous-main.mov', b'old main')]
        auxiliary = self.add_auxiliary(layer_change='updated')
        with self.assertRaisesRegex(ValueError, 'Updated auxiliary'):
            gate.check(self.manifest)
        auxiliary.update(layer_change='added', previous_files=[self.file('previous-aux.mov', b'old aux')])
        with self.assertRaisesRegex(ValueError, 'Added auxiliary'):
            gate.check(self.manifest)
        auxiliary['previous_files'] = []
        self.assertTrue(gate.check(self.manifest)['delivery_ready'])

    def test_new_auxiliary_cannot_collide_with_another_old_layer(self):
        self.manifest['operation'] = 'revision'
        auxiliary = self.add_auxiliary(layer_change='added')
        self.manifest['files'][0]['previous_files'] = [
            {'path': auxiliary['path'], 'sha256': auxiliary['sha256']}]
        with self.assertRaisesRegex(ValueError, 'previous delivery'):
            gate.check(self.manifest)

    def test_new_file_hardlink_cannot_alias_a_source_or_previous_layer(self):
        for protected in (self.source, self.file('old-file.mov', b'old file')):
            alias = self.root / ('hardlink-' + Path(protected['path']).name)
            os.link(protected['path'], alias)
            manifest = copy.deepcopy(self.manifest)
            item = manifest['files'][0]
            ref = {'path': str(alias), 'sha256': gate.sha256(alias)}
            item.update(ref, content_review=self.review([ref]))
            original_report = json.loads(Path(item['technical_report']['path']).read_text())
            original_report.update(file=ref['path'], sha256=ref['sha256'])
            item['technical_report'] = self.save('hardlink-' + alias.name + '.json', original_report)
            item['motion_reviews'][0].update(targets=[ref], evidence=[ref])
            manifest['checks']['timeline']['targets'] = [self.source, self.srt, self.production, ref]
            manifest['checks']['compatibility']['targets'] = [ref]
            if protected != self.source:
                manifest['operation'] = 'revision'
                item['previous_files'] = [protected]
            with self.subTest(protected=protected['path']), self.assertRaisesRegex(ValueError, 'same file'):
                gate.check(manifest)

    def test_missing_production_plan_or_invalid_mode_is_rejected(self):
        for mutation in (lambda m: m.pop('production_plan'), lambda m: m.update(uisfx_mode='arbitrary')):
            manifest = copy.deepcopy(self.manifest)
            mutation(manifest)
            with self.assertRaises((ValueError, KeyError)):
                gate.check(manifest)

    def test_plan_hash_is_required_in_timeline_and_srt_match_observations(self):
        for key in ('timeline', 'srt_match'):
            manifest = copy.deepcopy(self.manifest)
            manifest['checks'][key]['targets'] = [v for v in manifest['checks'][key]['targets']
                                                  if v['path'] != self.production['path']]
            with self.subTest(check=key), self.assertRaisesRegex(ValueError, 'targets'):
                gate.check(manifest)

    def test_changed_plan_cannot_reuse_old_observations_even_if_media_is_identical(self):
        plan = copy.deepcopy(self.plan)
        plan['source_time_mapping'] = [{'source_frame': 1, 'timeline_frame': 0}]
        self.manifest['production_plan'] = self.bind_plan(plan, 'changed-mapping')
        with self.assertRaisesRegex(ValueError, 'targets'):
            gate.check(self.manifest)

    def test_production_plan_srt_and_project_identity_must_match_handoff(self):
        for key, value in (('fps', '6'), ('total_frames', 6), ('srt', self.file('other.srt', b'1\n00:00:00,000 --> 00:00:01,000\nOther\n')['path'])):
            plan = copy.deepcopy(self.plan)
            if key == 'srt':
                plan['srt'] = value
            else:
                plan['project'][key] = value
                if key == 'total_frames':
                    plan['scenes'][0]['end_frame'] = value
            self.replace_plan(self.bind_plan(plan, 'mismatch-' + key))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'Production plan'):
                gate.check(self.manifest)

    def test_missing_or_stale_uisfx_binding_blocks_final_handoff(self):
        for mode in ('missing', 'stale'):
            plan = json.loads(Path(self.production['path']).read_text())
            if mode == 'missing':
                plan.pop('uisfx_selection')
            else:
                plan['scenes'][0]['params']['title'] = 'Changed title'
            self.replace_plan(self.save('uisfx-' + mode + '.json', plan))
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'UISFX'):
                gate.check(self.manifest)

    def test_existing_draft_uisfx_context_is_reused_without_loading_editor(self):
        plan = {'srt': self.srt['path'], 'font': 'Fixture', 'fps': '5', 'total_frames': 5,
                'video': self.source['path'], 'segments': [{'src': 0, 'end': 1}], 'sounds': []}
        self.manifest['uisfx_mode'] = 'draft'
        self.replace_plan(self.bind_plan(plan, 'real-draft-context', 'draft'))
        result = gate.check(self.manifest)
        self.assertEqual(result['uisfx_selection'], {'mode': 'draft', 'status': 'completed',
                                                    'sound_events': 0, 'silence_decisions': 1})

    def test_real_production_context_needs_no_fake_font_html_or_native_draft(self):
        plan = {'srt': self.srt['path'], 'source': self.source['path'],
            'project': {'fps': '5', 'total_frames': 5},
            'scenes': [{'id': 'one', 'start_frame': 0, 'end_frame': 5, 'renderer': 'ffmpeg',
                        'source_mapping': [{'source_frame': 0, 'timeline_frame': 0}]}], 'sounds': []}
        self.manifest['uisfx_mode'] = 'production'
        self.replace_plan(self.bind_plan(plan, 'actual-production-context', 'production'))
        result = gate.check(self.manifest)
        self.assertEqual(result['uisfx_selection']['mode'], 'production')
        self.assertEqual(result['uisfx_selection']['silence_decisions'], 1)
        self.assertNotIn('font', plan['project'])
        self.assertNotIn('html', plan['scenes'][0])

    def test_production_source_identity_must_match_the_current_handoff(self):
        plan = {'srt': self.srt['path'], 'source': self.file('other-source.mov', b'other real input fixture')['path'],
            'project': {'fps': '5', 'total_frames': 5},
            'scenes': [{'id': 'one', 'start_frame': 0, 'end_frame': 5, 'renderer': 'blender'}], 'sounds': []}
        self.manifest['uisfx_mode'] = 'production'
        self.replace_plan(self.bind_plan(plan, 'wrong-production-source', 'production'))
        with self.assertRaisesRegex(ValueError, 'Production plan source'):
            gate.check(self.manifest)

    def test_high_risk_motion_needs_continuous_viewing_of_entire_declared_range(self):
        motion = self.manifest['files'][0]['motion_reviews'][0]
        motion['method'] = 'keyframes'
        with self.assertRaisesRegex(ValueError, 'continuous/keyframe'):
            gate.check(self.manifest)
        motion.update(method='continuous', end_frame=4)
        with self.assertRaisesRegex(ValueError, 'continuous/keyframe'):
            gate.check(self.manifest)

    def test_still_or_unverified_renamed_still_cannot_prove_continuous_motion(self):
        motion = self.manifest['files'][0]['motion_reviews'][0]
        for evidence in ([self.frame], [self.file('renamed-still.mov', b'PNG fixture renamed as MOV')]):
            motion['evidence'] = evidence
            with self.subTest(evidence=evidence), self.assertRaisesRegex(ValueError, 'actual video'):
                gate.check(self.manifest)

    def test_low_risk_motion_allows_keyframes_and_static_video_requires_reason(self):
        self.manifest['checks']['timeline']['required_motion_ranges'][0]['risk'] = 'low'
        self.manifest['files'][0]['motion_reviews'][0].update(method='keyframes', evidence=[self.frame])
        self.assertTrue(gate.check(self.manifest)['delivery_ready'])
        self.manifest['checks']['timeline']['required_motion_ranges'] = []
        with self.assertRaisesRegex(ValueError, 'rationale'):
            gate.check(self.manifest)
        self.manifest['checks']['timeline']['motion_rationale'] = 'Only a stable static title is displayed'
        self.assertTrue(gate.check(self.manifest)['delivery_ready'])

    def test_short_continuous_clip_does_not_cover_a_long_declared_action(self):
        clip = self.file('too-short.mov', b'continuous clip unit fixture')
        report = json.loads(Path(self.manifest['files'][0]['technical_report']['path']).read_text())
        report.update(file=clip['path'], sha256=clip['sha256'])
        report['decoded_video_frames'] = 2
        report['expected']['frames'] = 2
        clip['technical_report'] = self.save('short-continuous-report.json', report)
        self.manifest['files'][0]['motion_reviews'][0]['evidence'] = [clip]
        with self.assertRaisesRegex(ValueError, 'actual video'):
            gate.check(self.manifest)

    def test_audio_only_has_no_visual_motion_requirement_but_needs_mix_review(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['product'] = 'audio'
        manifest['checks']['timeline']['required_motion_ranges'] = []
        item = manifest['files'][0]
        item.update(kind='audio', audio='present', technical_report=self.technical(self.media, 'audio', 'present'))
        item.pop('motion_reviews')
        with self.assertRaisesRegex(ValueError, 'mix/listening'):
            gate.check(manifest)
        item['audio_review'] = self.review([self.media, self.source])
        self.assertTrue(gate.check(manifest)['delivery_ready'])

    def test_compatibility_change_requires_actual_revalidation_evidence(self):
        check = self.manifest['checks']['compatibility']
        check['revalidation_required'] = True
        with self.assertRaisesRegex(ValueError, 'revalidation'):
            gate.check(self.manifest)
        check['native_open_review'] = self.review([self.media])
        self.assertTrue(gate.check(self.manifest)['delivery_ready'])

    def artifact_manifest(self, kind):
        manifest = copy.deepcopy(self.manifest)
        artifact = self.srt if kind == 'subtitle' else self.save('draft.json', {'tracks': [], 'materials': {}})
        manifest['product'] = kind
        manifest['checks']['timeline']['targets'] = [self.source, self.srt, self.production, artifact]
        manifest['checks']['timeline']['required_motion_ranges'] = []
        manifest['checks']['compatibility']['targets'] = [artifact]
        checks = {k: 'pass' for k in (('parse', 'timing', 'content') if kind == 'subtitle' else ('parse', 'references', 'timeline'))}
        structure = self.save('structure-' + kind + '.json', {'schema': 'jianying-artifact-check/v1',
            'status': 'pass', 'kind': kind, 'file': artifact['path'], 'file_sha256': artifact['sha256'], 'checks': checks})
        if kind == 'subtitle':
            artifact = self.file('corrected.srt', Path(self.srt['path']).read_bytes())
            data = json.loads(Path(structure['path']).read_text())
            data.update(file=artifact['path'], file_sha256=artifact['sha256'])
            structure = self.save('structure-corrected.json', data)
            manifest['checks']['timeline']['targets'] = [self.source, self.srt, self.production, artifact]
            manifest['checks']['compatibility']['targets'] = [artifact]
        item = {**artifact, 'id': 'main', 'kind': kind, 'role': 'main', 'label': 'Native artifact',
            'layer': 0, 'audio': 'absent', 'alignment_frame': 0, 'disposition': 'new', 'previous_files': [],
            'structure_report': structure, 'content_review': self.review([artifact])}
        manifest['files'] = [item]
        manifest['checks']['visual_references'] = self.visual_review([self.production, artifact])
        return manifest, item, artifact

    def test_subtitle_uses_applicable_bound_structure_checks(self):
        manifest, item, artifact = self.artifact_manifest('subtitle')
        self.assertTrue(gate.check(manifest)['delivery_ready'])
        data = json.loads(Path(item['structure_report']['path']).read_text())
        data['checks']['timing'] = 'unavailable'
        item['structure_report'] = self.save('bad-srt-check.json', data)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            gate.check(manifest)

    def test_draft_json_success_does_not_replace_native_open_evidence(self):
        manifest, item, artifact = self.artifact_manifest('draft')
        with self.assertRaisesRegex(ValueError, 'native-open'):
            gate.check(manifest)
        item['native_open_review'] = self.review([artifact])
        self.assertTrue(gate.check(manifest)['delivery_ready'])

    def test_failed_handoff_record_has_no_links_and_cannot_overwrite_files(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['checks']['assets']['status'] = 'unavailable'
        path = self.save('manifest-failed.json', manifest)['path']
        result = gate.finalize(path, self.root / 'failed.json')
        self.assertFalse(result['delivery_ready'])
        self.assertEqual(result['links'], [])
        self.assertEqual(result['files'], [])
        with self.assertRaisesRegex(ValueError, 'new task work'):
            gate.finalize(path, self.media['path'])

    def test_actual_qtrle_to_existing_technical_check_to_handoff(self):
        binary = Path('/Applications/ChatCut.app/Contents/Resources/app.asar.unpacked/node_modules/ffmpeg-ffprobe-static')
        ffmpeg, ffprobe = shutil.which('ffmpeg') or str(binary / 'ffmpeg'), shutil.which('ffprobe') or str(binary / 'ffprobe')
        if not Path(ffmpeg).is_file() or not Path(ffprobe).is_file():
            self.fail('Existing local FFmpeg/FFprobe required for the real integration test')
        pixels = b''.join(bytes((255, 40, 20, 255 if 4 <= x < 12 and 4 <= y < 12 else 0))
                          for y in range(16) for x in range(16)) * 5
        path = self.root / '真实中文 空格 QTRLE.mov'
        subprocess.run([ffmpeg, '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'rgba',
            '-video_size', '16x16', '-framerate', '5', '-i', 'pipe:0', '-frames:v', '5',
            '-c:v', 'qtrle', '-pix_fmt', 'argb', str(path)], input=pixels, check=True, capture_output=True)
        real = {'path': str(path), 'sha256': gate.sha256(path)}
        args = type('Args', (), dict(file=str(path), kind='overlay', width=16, height=16,
            fps='5', frames=5, audio='absent', alpha_frame=[0], visible_frame=[2],
            previous_file=[], expected_sha256=real['sha256'], ffmpeg=ffmpeg, ffprobe=ffprobe))()
        report = verify.check(args)
        real_source = self.file('real-source-copy.mov', path.read_bytes())
        plan = {'srt': self.srt['path'], 'source': real_source['path'],
            'project': {'fps': '5', 'total_frames': 5},
            'scenes': [{'id': 'one', 'start_frame': 0, 'end_frame': 5, 'renderer': 'ffmpeg',
                        'source_mapping': [{'source_frame': 0, 'timeline_frame': 0}]}], 'sounds': []}
        self.manifest.update(source=real_source, uisfx_mode='production')
        self.replace_plan(self.bind_plan(plan, 'real-production-media', 'production'))
        self.manifest['checks']['assets']['targets'] = [real_source, self.srt]
        self.manifest['checks']['srt_match']['targets'] = [real_source, self.srt, self.manifest['production_plan']]
        self.manifest['checks']['timeline']['targets'] = [real_source, self.srt, self.manifest['production_plan'], real]
        self.manifest['checks']['compatibility']['targets'] = [real]
        self.manifest['checks']['visual_references'] = self.visual_review([self.manifest['production_plan'], real])
        item = self.manifest['files'][0]
        item.update(real, technical_report=self.save('real-technical.json', report),
                    content_review=self.review([real]))
        motion = self.review([real], evidence=[real])
        motion.update(start_frame=0, end_frame=5, method='continuous')
        item['motion_reviews'] = [motion]
        manifest = self.save('real-manifest.json', self.manifest)
        result = gate.finalize(manifest['path'], self.root / 'real-ready.json')
        self.assertTrue(result['delivery_ready'])
        self.assertIn(str(path), result['links'][0])
        command = [sys.executable, str(ROOT / 'scripts/finalize_delivery.py'),
                   '--manifest', manifest['path'], '--out', str(self.root / 'real-cli-ready.json')]
        cli = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertTrue(json.loads(cli.stdout)['delivery_ready'])
        item['motion_reviews'] = []
        failed_manifest = self.save('no-motion.json', self.manifest)['path']
        self.assertFalse(gate.finalize(failed_manifest, self.root / 'no-motion-result.json')['delivery_ready'])
        failed_cli = subprocess.run([sys.executable, str(ROOT / 'scripts/finalize_delivery.py'),
            '--manifest', failed_manifest, '--out', str(self.root / 'failed-cli.json')], capture_output=True, text=True)
        self.assertEqual(failed_cli.returncode, 2)
        self.assertEqual(json.loads(failed_cli.stdout)['links'], [])
        item['motion_reviews'] = [motion]
        self.manifest['operation'] = 'revision'
        item['previous_files'] = [real]
        self.assertFalse(gate.finalize(self.save('old-path.json', self.manifest)['path'], self.root / 'old-path-result.json')['delivery_ready'])
        self.manifest['operation'] = 'initial'
        item['previous_files'] = []
        path.write_bytes(b'changed after the actual technical check')
        self.assertFalse(gate.finalize(self.save('changed.json', self.manifest)['path'], self.root / 'changed-result.json')['delivery_ready'])


if __name__ == '__main__':
    unittest.main()
