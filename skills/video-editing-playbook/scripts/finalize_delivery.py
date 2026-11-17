#!/usr/bin/env python3
"""Read-only handoff gate: bind existing checks to the exact files linked to the user."""
import argparse
from fractions import Fraction
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

MEDIA = {'overlay', 'video', 'audio'}
PRODUCT_MAIN = {'overlay': {'overlay'}, 'final_video': {'video'}, 'audio': {'audio'},
                'subtitle': {'subtitle'}, 'draft': {'draft'},
                'hybrid': {'overlay', 'video', 'subtitle', 'draft'}}


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + ' needs concrete text')
    return value.strip()


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(name + ' must be an integer >= ' + str(minimum))
    return value


@lru_cache(maxsize=2048)
def cached_digest(path, device, inode, size, modified_ns):
    return sha256(path)


def reference(value, force=False):
    if not isinstance(value, dict):
        raise ValueError('File/evidence references need path and SHA-256')
    raw = Path(text(value.get('path'), 'Reference path')).expanduser()
    if not raw.is_absolute():
        raise ValueError('Use absolute paths for files and evidence')
    path = raw.resolve(strict=True)
    expected = text(value.get('sha256'), 'Reference SHA-256')
    if not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('Reference SHA-256 must be 64 lowercase hex characters')
    stat = path.stat()
    actual = sha256(path) if force else cached_digest(str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    if not path.is_file() or not stat.st_size or actual != expected:
        raise ValueError('File/evidence missing, empty or changed: ' + str(path))
    return {'path': str(path), 'sha256': expected}


def ref_key(value):
    return value['path'], value['sha256']


def read_record(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError('Check reports must be JSON objects')
    return value


@lru_cache(maxsize=1)
def uisfx_module():
    path = Path(__file__).resolve().parents[2] / 'koubo-cut/scripts/uisfx.py'
    spec = importlib.util.spec_from_file_location('handoff_existing_uisfx_gate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def production_context(manifest, plan_ref, srt_ref, source_ref, project):
    mode = manifest.get('uisfx_mode')
    if mode not in ('scene', 'draft', 'production'):
        raise ValueError('UISFX mode must be scene, draft or production for the actual production plan')
    reference(plan_ref, force=True)
    sfx = uisfx_module()
    plan = sfx.load_context(plan_ref['path'], mode)
    actual_srt = Path(plan['srt']).expanduser().resolve(strict=True)
    if str(actual_srt) != srt_ref['path'] or sha256(actual_srt) != srt_ref['sha256']:
        raise ValueError('Production plan SRT differs from the current handoff SRT')
    context_project = plan['project'] if mode in ('scene', 'production') else plan
    if (Fraction(str(context_project['fps'])) != Fraction(str(project['fps'])) or
            context_project['total_frames'] != project['total_frames']):
        raise ValueError('Production plan FPS/total_frames differ from the final handoff timeline')
    for key in ('width', 'height'):
        if key in context_project and key in project and context_project[key] != project[key]:
            raise ValueError('Production plan dimensions differ from the final handoff project')
    source_path = plan.get('source') if mode == 'production' else plan.get('video') if mode == 'draft' else None
    if source_path is not None:
        actual_source = Path(source_path).expanduser().resolve(strict=True)
        if str(actual_source) != source_ref['path'] or sha256(actual_source) != source_ref['sha256']:
            raise ValueError('Production plan source differs from the current handoff source')
    return sfx.validate_selection(plan, mode)


def review(value, manifest, targets, name):
    if not isinstance(value, dict) or value.get('status') != 'pass':
        raise ValueError(name + ' must pass with observations')
    text(value.get('finding'), name + ' finding')
    evidence = value.get('evidence')
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(name + ' needs readable evidence')
    for item in evidence:
        reference(item)
    recorded = [reference(item) for item in value.get('targets', [])]
    same_version = all(value.get(k) == manifest[k] for k in ('job_id', 'version_id'))
    if same_version:
        if not {ref_key(t) for t in targets}.issubset({ref_key(t) for t in recorded}):
            raise ValueError(name + ' targets do not bind the current inputs/files')
    else:
        text(value.get('reuse_reason'), name + ' reuse reason')
        if not {t['sha256'] for t in targets}.issubset({t['sha256'] for t in recorded}):
            raise ValueError(name + ' reused observations do not match current content hashes')
    return evidence


def anchors(value, project, name):
    items = value.get('anchors')
    if not isinstance(items, list) or not items:
        raise ValueError(name + ' needs observed source/timeline/SRT anchors')
    for item in items:
        frame = integer(item.get('timeline_frame'), 'Anchor timeline frame')
        integer(item.get('source_frame'), 'Anchor source frame')
        if frame >= project['total_frames']:
            raise ValueError('Anchor lies outside the final timeline')
        text(item.get('srt_cue'), 'Anchor SRT cue')
        text(item.get('finding'), 'Anchor observation')
        if not item.get('evidence'):
            raise ValueError('Each observed anchor needs evidence')
        for ref in item['evidence']:
            reference(ref)


def visual_reference_review(manifest, targets):
    value = manifest['checks'].get('visual_references')
    review(value, manifest, targets, 'Visual-reference review')
    scope = value.get('scope')
    if scope not in ('researched', 'reused', 'not_required'):
        raise ValueError('Visual-reference scope must be researched, reused or not_required')
    materials = value.get('materials')
    if scope == 'not_required':
        text(value.get('reason'), 'Visual-reference not-required reason')
        if materials != []:
            raise ValueError('Visual-reference not_required needs an empty materials list')
        return {'scope': scope, 'material_count': 0, 'sources': []}
    if not isinstance(materials, list) or not materials:
        raise ValueError('Visual-reference review needs the actual material nouns and purposes')
    for item in materials:
        if not isinstance(item, dict):
            raise ValueError('Visual-reference materials must be objects')
        for key in ('noun', 'purpose'):
            text(item.get(key), 'Visual-reference material ' + key)
    if scope == 'reused':
        text(value.get('reuse_reason'), 'Visual-reference reuse reason')
    searches = value.get('searches')
    if not isinstance(searches, dict):
        raise ValueError('Visual-reference review needs Pinterest and Cosmos search records')
    for site in ('pinterest', 'cosmos'):
        search = searches.get(site)
        if not isinstance(search, dict) or search.get('status') != 'pass':
            raise ValueError('Visual-reference ' + site + ' search must pass')
        text(search.get('method'), 'Visual-reference search method')
        if site == 'cosmos' and search['method'] != 'mcp':
            raise ValueError('Visual-reference Cosmos MCP search cannot be replaced by browser access')
        queries = search.get('queries')
        if not isinstance(queries, list) or not queries:
            raise ValueError('Visual-reference ' + site + ' needs actual search queries')
        for query in queries:
            text(query, 'Visual-reference query')
        evidence = search.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            raise ValueError('Visual-reference ' + site + ' needs readable search evidence')
        for item in evidence:
            reference(item)
    selected = value.get('selected_references')
    if not isinstance(selected, list) or not selected:
        raise ValueError('Visual-reference review needs selected references and actual image evidence')
    for item in selected:
        if not isinstance(item, dict):
            raise ValueError('Visual-reference selections must be objects')
        url = urlparse(text(item.get('url'), 'Visual-reference source URL'))
        if url.scheme not in ('http', 'https') or not url.netloc:
            raise ValueError('Visual-reference source needs a web URL')
        text(item.get('takeaway'), 'Visual-reference design takeaway')
        evidence = item.get('image_evidence')
        if not isinstance(evidence, list) or not evidence:
            raise ValueError('Visual-reference needs actual image evidence, not URLs alone')
        for raw in evidence:
            ref = reference(raw)
            if Path(ref['path']).suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif', '.bmp', '.tif', '.tiff'):
                raise ValueError('Visual-reference image evidence must be a saved image or screenshot')
    text(value.get('design_rules'), 'Visual-reference design rules')
    text(value.get('comparison'), 'Visual-reference formal-output comparison')
    return {'scope': scope, 'material_count': len(materials), 'sources': ['pinterest', 'cosmos_mcp']}


def range_bounds(value, total):
    a = integer(value.get('start_frame'), 'Range start')
    b = integer(value.get('end_frame'), 'Range end', 1)
    if not a < b <= total:
        raise ValueError('Review range is outside the final timeline')
    return a, b


def technical(item, file_ref, project):
    ref = reference(item.get('technical_report'))
    report = read_record(ref['path'])
    if (report.get('schema') != 'jianying-delivery-technical/v1' or
            report.get('status') != 'technical_pass' or report.get('full_decode') != 'pass'):
        raise ValueError('Media needs its successful complete-decode technical report')
    path = str(Path(text(report.get('file'), 'Technical file')).expanduser().resolve())
    if path != file_ref['path'] or report.get('sha256') != file_ref['sha256']:
        raise ValueError('Technical report refers to another file/version')
    expected = report.get('expected', {})
    kind = item['kind']
    if (expected.get('kind') != kind or Fraction(str(expected.get('fps'))) != Fraction(str(project['fps'])) or
            expected.get('frames') != project['total_frames'] or expected.get('audio') != item['audio']):
        raise ValueError('Technical report does not match the declared kind/audio/final timeline')
    if kind != 'audio':
        if any(expected.get(k) != project[k] for k in ('width', 'height')):
            raise ValueError('Technical report dimensions differ from the final project')
        if report.get('decoded_video_frames') != project['total_frames']:
            raise ValueError('Technical report decoded frame count differs from the final timeline')
    streams = report.get('streams', [])
    if sum(s.get('codec_type') == 'video' for s in streams) != (kind != 'audio'):
        raise ValueError('Technical report video streams do not match the delivery')
    if sum(s.get('codec_type') == 'audio' for s in streams) != (item['audio'] == 'present'):
        raise ValueError('Technical report audio streams do not match the delivery')
    if kind == 'overlay' and not report.get('alpha_samples'):
        raise ValueError('Overlay technical report needs actual Alpha samples')


def structural(item, file_ref, manifest):
    kind = item['kind']
    ref = reference(item.get('structure_report'))
    report = read_record(ref['path'])
    if (report.get('schema') != 'jianying-artifact-check/v1' or report.get('status') != 'pass' or
            report.get('kind') != kind or report.get('file_sha256') != file_ref['sha256'] or
            str(Path(text(report.get('file'), 'Artifact file')).resolve()) != file_ref['path']):
        raise ValueError('Artifact structure report does not bind this file/kind')
    checks = ('parse', 'timing', 'content') if kind == 'subtitle' else ('parse', 'references', 'timeline')
    if any(report.get('checks', {}).get(k) != 'pass' for k in checks):
        raise ValueError('Required artifact structure checks are incomplete')
    if kind == 'subtitle':
        if Path(file_ref['path']).suffix.lower() != '.srt' or not re.search(
                r'\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}',
                Path(file_ref['path']).read_text(encoding='utf-8-sig')):
            raise ValueError('Subtitle delivery needs a readable timestamped SRT')
    else:
        if Path(file_ref['path']).suffix.lower() == '.json':
            data = json.loads(Path(file_ref['path']).read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict) or not data:
                raise ValueError('Draft JSON must contain its actual non-empty project structure')
        review(item.get('native_open_review'), manifest, [file_ref], 'Draft native-open review')


def continuous_evidence(refs, item, file_ref, duration):
    for raw in refs:
        evidence = reference(raw)
        if Path(evidence['path']).suffix.lower() not in ('.mov', '.mp4', '.mkv', '.webm'):
            continue
        report_ref = raw.get('technical_report')
        if ref_key(evidence) == ref_key(file_ref):
            report_ref = item.get('technical_report')
        if report_ref is None:
            continue
        report = read_record(reference(report_ref)['path'])
        reported_file = str(Path(text(report.get('file'), 'Continuous evidence file')).resolve())
        if (report.get('schema') == 'jianying-delivery-technical/v1' and
                report.get('status') == 'technical_pass' and report.get('full_decode') == 'pass' and
                reported_file == evidence['path'] and report.get('sha256') == evidence['sha256'] and
                type(report.get('decoded_video_frames')) is int and report['decoded_video_frames'] >= 2 and
                any(s.get('codec_type') == 'video' for s in report.get('streams', []))):
            rate = Fraction(str(report.get('expected', {}).get('fps')))
            if rate > 0 and Fraction(report['decoded_video_frames'], 1) / rate >= duration:
                return
    raise ValueError('Continuous motion review needs an actual video bound to a successful technical report, not a still')


def check(manifest):
    if not isinstance(manifest, dict) or manifest.get('schema') != 'jianying-handoff/v1':
        raise ValueError('Use jianying-handoff/v1')
    for key in ('job_id', 'version_id'):
        text(manifest.get(key), key)
    if manifest.get('operation') not in ('initial', 'revision', 'redo'):
        raise ValueError('Operation must be initial, revision or redo')
    product = manifest.get('product')
    if product not in PRODUCT_MAIN:
        raise ValueError('Declare the actual delivery product')
    project = manifest['project']
    if not isinstance(project, dict) or not isinstance(manifest.get('checks'), dict):
        raise ValueError('Project and checks must be objects')
    integer(project.get('total_frames'), 'Project total_frames', 1)
    if Fraction(str(project.get('fps'))) <= 0:
        raise ValueError('Project FPS must be positive')
    source, srt = reference(manifest['source']), reference(manifest['srt'])
    inputs = [source, srt] + [reference(v) for v in manifest.get('assets', [])]
    plan_ref = reference(manifest['production_plan'])
    uisfx = production_context(manifest, plan_ref, srt, source, project)
    items = manifest.get('files')
    if not isinstance(items, list) or not items:
        raise ValueError('There are no formal delivery files')
    file_refs = [reference(item) for item in items]
    if len({v['path'] for v in file_refs}) != len(file_refs):
        raise ValueError('Delivery files must have unique paths')
    ids = [text(item.get('id'), 'File id') for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError('File ids must be unique')
    main = [item for item in items if item.get('role') == 'main']
    if len(main) != 1 or main[0].get('kind') not in PRODUCT_MAIN[product]:
        raise ValueError('Product needs exactly one matching main file')
    if product in ('audio', 'subtitle') and any(item.get('kind') != product for item in items):
        raise ValueError('Audio-only/subtitle-only products cannot silently add other media kinds')
    checks = manifest['checks']
    review(checks.get('assets'), manifest, inputs, 'Asset review')
    review(checks.get('timeline'), manifest, inputs + [plan_ref] + file_refs, 'Timeline/composite review')
    review(checks.get('srt_match'), manifest, [source, srt, plan_ref], 'SRT-match review')
    anchors(checks['timeline'], project, 'Timeline review')
    anchors(checks['srt_match'], project, 'SRT-match review')
    compatibility = checks.get('compatibility')
    review(compatibility, manifest, file_refs, 'Compatibility review')
    for key in ('current_version', 'basis_version', 'change_assessment'):
        text(compatibility.get(key), 'Compatibility ' + key)
    if not isinstance(compatibility.get('profile'), dict) or not compatibility['profile']:
        raise ValueError('Record the actual compatibility profile')
    if type(compatibility.get('revalidation_required')) is not bool:
        raise ValueError('Record whether compatibility revalidation is required')
    if compatibility['revalidation_required']:
        review(compatibility.get('native_open_review'), manifest, file_refs, 'Required compatibility revalidation')
    required_motion = checks['timeline'].get('required_motion_ranges')
    if not isinstance(required_motion, list):
        raise ValueError('Declare motion risk ranges, or [] for no video motion')
    if any(not isinstance(v, dict) for v in required_motion):
        raise ValueError('Motion risk ranges must be objects')
    if not required_motion and any(v.get('kind') in ('overlay', 'video') for v in items):
        text(checks['timeline'].get('motion_rationale'), 'Static-video/no-motion rationale')
    results = []
    all_previous = [reference(ref) for item in items for ref in item.get('previous_files', [])]
    protected_refs = inputs + [plan_ref] + all_previous
    protected_paths = {ref['path'] for ref in protected_refs}
    for item, file_ref in zip(items, file_refs):
        kind = item.get('kind')
        if kind not in MEDIA | {'subtitle', 'draft'}:
            raise ValueError('Unknown formal file kind')
        if item.get('role') not in ('main', 'auxiliary') or item.get('audio') not in ('present', 'absent'):
            raise ValueError('Declare main/auxiliary role and present/absent audio')
        integer(item.get('layer'), 'Layer')
        if item.get('alignment_frame') != 0:
            raise ValueError('Formal layers must align at 00:00')
        label = ' '.join(text(item.get('label'), 'File label').split())
        disposition = item.get('disposition')
        previous = [reference(v) for v in item.get('previous_files', [])]
        if disposition == 'new':
            if file_ref['path'] in protected_paths:
                raise ValueError('New delivery must preserve source and previous delivery paths')
            if any(Path(file_ref['path']).samefile(ref['path']) for ref in protected_refs):
                raise ValueError('New delivery resolves to the same file as a source, plan or previous delivery')
            if manifest['operation'] in ('revision', 'redo') and item['role'] == 'main' and not previous:
                raise ValueError('Revision/redo main file must identify the preserved previous file')
            if manifest['operation'] in ('revision', 'redo') and item['role'] == 'auxiliary':
                if item.get('layer_change') == 'updated':
                    if not previous:
                        raise ValueError('Updated auxiliary must identify its preserved previous layer')
                elif item.get('layer_change') == 'added':
                    if previous:
                        raise ValueError('Added auxiliary is a first addition and must not claim a previous identity')
                else:
                    raise ValueError('New revision/redo auxiliary must declare layer_change added or updated')
        elif disposition == 'reused' and item['role'] == 'auxiliary':
            text(item.get('reuse_reason'), 'Auxiliary reuse reason')
        else:
            raise ValueError('Main delivery must be new; only verified auxiliary files may be reused')
        review(item.get('content_review'), manifest, [file_ref], 'Formal content review ' + item['id'])
        if kind in MEDIA:
            if kind != 'audio':
                integer(project.get('width'), 'Project width', 1)
                integer(project.get('height'), 'Project height', 1)
            if kind == 'audio' and item['audio'] != 'present':
                raise ValueError('Audio file must declare its audio')
            technical(item, file_ref, project)
        else:
            if item['audio'] != 'absent':
                raise ValueError('Subtitle/draft files do not declare a media audio stream')
            structural(item, file_ref, manifest)
        if item['audio'] == 'present':
            review(item.get('audio_review'), manifest, [file_ref, source], 'Same-range mix/listening review')
        own_motion = [v for v in required_motion if v.get('file_id') == item['id']]
        if own_motion and kind not in ('overlay', 'video'):
            raise ValueError('Motion ranges may target only video files')
        for required in own_motion:
            a, b = range_bounds(required, project['total_frames'])
            if required.get('risk') not in ('high', 'low'):
                raise ValueError('Motion risk must be high or low')
            covered = False
            for observed in item.get('motion_reviews', []):
                x, y = range_bounds(observed, project['total_frames'])
                if x <= a and y >= b:
                    method = observed.get('method')
                    if method not in ('continuous', 'keyframes') or (required['risk'] == 'high' and method != 'continuous'):
                        continue
                    refs = review(observed, manifest, [file_ref], 'Motion review')
                    if method == 'continuous':
                        continuous_evidence(refs, item, file_ref,
                                            Fraction(y-x, 1) / Fraction(str(project['fps'])))
                    covered = True
                    break
            if not covered:
                raise ValueError('Declared motion risk range lacks adequate continuous/keyframe review')
        results.append({**file_ref, 'id': item['id'], 'label': label, 'kind': kind,
                        'role': item['role'], 'layer': item['layer'], 'audio': item['audio'],
                        'alignment_frame': 0, 'disposition': disposition, 'previous_files': previous,
                        **({'layer_change': item['layer_change']} if 'layer_change' in item else {}),
                        **({'reuse_reason': item['reuse_reason']} if disposition == 'reused' else {}),
                        'link': '[' + label.replace('[', '\\[').replace(']', '\\]') + '](<' + file_ref['path'] + '>)'})
    if any(v.get('file_id') not in ids for v in required_motion):
        raise ValueError('Motion risk range refers to an unknown file')
    visual_references = visual_reference_review(manifest, [plan_ref] + file_refs)
    # Recheck each unique evidence/input/output once before exposing links.
    pending = [manifest]
    all_refs = {}
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value:
                all_refs[(value['path'], value['sha256'])] = value
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    for ref in all_refs.values():
        reference(ref, force=True)
    production_context(manifest, plan_ref, srt, source, project)
    return {'schema': 'jianying-handoff-ready/v1', 'job_id': manifest['job_id'],
            'version_id': manifest['version_id'], 'operation': manifest['operation'], 'product': product,
            'delivery_ready': True, 'files': sorted(results, key=lambda v: v['layer']),
            'production_plan': plan_ref, 'uisfx_selection': {'mode': manifest['uisfx_mode'], **uisfx},
            'visual_references': visual_references,
            'links': [v['link'] for v in sorted(results, key=lambda v: v['layer'])],
            'user_performs': ['import', 'placement', 'replacement'], 'post_import_review': False,
            'native_editor_mutated': False, 'user_acceptance': 'not_assessed',
            'review_truth': 'agent_observations_not_independently_performed_by_helper'}


def finalize(manifest_path, output):
    source = Path(manifest_path).expanduser().resolve(strict=True)
    out = Path(output).expanduser().resolve()
    skills = Path(__file__).resolve().parents[2]
    if out == source or out.is_relative_to(skills) or out.exists():
        raise ValueError('Choose a new task work/ handoff record, not an existing file or skill path')
    source_bytes = source.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    manifest = json.loads(source_bytes)
    if not isinstance(manifest, dict):
        raise ValueError('Handoff manifest must be a JSON object')
    protected = [v.get('path') for v in manifest.get('files', [])]
    protected += [manifest.get(k, {}).get('path') for k in ('source', 'srt')]
    if str(out) in {str(Path(p).expanduser().resolve()) for p in protected if p}:
        raise ValueError('Handoff record must not overwrite media or inputs')
    try:
        result = check(manifest)
        if sha256(source) != source_sha:
            raise ValueError('Handoff manifest changed during verification')
    except (ValueError, KeyError, TypeError, OSError, ZeroDivisionError) as error:
        result = {'schema': 'jianying-handoff-ready/v1', 'delivery_ready': False,
                  'errors': [str(error)], 'files': [], 'links': [], 'post_import_review': False}
    result['manifest'] = {'path': str(source), 'sha256': source_sha}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        result = finalize(args.manifest, args.out)
    except (ValueError, OSError, TypeError) as error:
        print(json.dumps({'delivery_ready': False, 'errors': [str(error)], 'links': []}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['delivery_ready'] else 2


if __name__ == '__main__':
    sys.exit(main())
