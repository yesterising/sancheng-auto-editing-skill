#!/usr/bin/env python3
"""Local graphics recipes, immutable revisions, and per-scene alpha render cache."""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
import tempfile
import wave
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPES = ROOT / 'assets/sancheng-recipes.json'
TEMPLATE = ROOT / 'assets/scene-template.html'
RENDERER = ROOT.parent / 'sancheng-broll-animation/scripts/render_alpha.mjs'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def local_file(value, base):
    if not isinstance(value, str) or re.match(r'^[a-zA-Z]+://', value) or '\n' in value:
        raise ValueError('Expected a local file path')
    path = Path(value).expanduser()
    path = (base / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_file():
        raise ValueError('Missing local file: ' + str(path))
    return str(path)


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(name + ' must be an integer >= ' + str(minimum))
    return value


def number(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(name + ' is outside its finite range')


COMMON_PARAMS = {'zone', 'font_size', 'enter_frames', 'accent', 'stroke_width', 'stroke_color', 'image_fit'}


def candidates(task, available):
    result = {'task': task, 'candidates': [], 'rejected': []}
    for recipe in read_json(RECIPES)['recipes']:
        if task and task not in recipe['semantics']:
            continue
        missing = sorted(set(recipe['required_assets'])-set(available))
        result['rejected' if missing else 'candidates'].append({**recipe,
            'missing_assets': missing, 'reason': '缺少真实输入' if missing else '用途匹配且所需素材键齐备；仍需核实际素材、布局与授权'})
    return result


def consumed_events(scene):
    recipe = next(r for r in read_json(RECIPES)['recipes'] if r['id'] == scene['recipe'])
    used = {}
    for key, count in recipe['event_params'].items():
        if key not in scene['params']:
            continue
        values = scene['params'][key]
        ids = [values] if count == 1 else values
        expected = len(scene['params'][count]) if isinstance(count, str) else count
        if (not isinstance(ids, list) or len(ids) != expected or
                any(not isinstance(i, str) or i not in scene.get('events', {}) for i in ids) or
                len(set(ids)) != len(ids)):
            raise ValueError(scene['id'] + ': unresolved/duplicate event references in ' + key)
        frames = [scene['events'][i]['frame'] for i in ids]
        if any(a >= b for a, b in zip(frames, frames[1:])):
            raise ValueError(key + ' events must be strictly ordered')
        for eid in ids:
            used.setdefault(eid, []).append(key)
    return used


def geometry(scene):
    value = read_json(scene['assets']['geometry'])
    if value.get('schema') != 'sancheng-evidence/v1':
        raise ValueError('Unknown evidence geometry schema')
    if value.get('image_sha256') != digest(Path(scene['assets']['image']).read_bytes()):
        raise ValueError('Evidence image hash changed; recapture its geometry')
    width, height = integer(value['width'], 'image width', 1), integer(value['height'], 'image height', 1)
    targets = value.get('targets')
    if not isinstance(targets, dict) or not targets:
        raise ValueError('Evidence needs measured target rectangles')
    for target, rect in targets.items():
        if not isinstance(rect, list) or len(rect) != 4:
            raise ValueError('Invalid target rectangle: ' + str(target))
        for v in rect: number(v, 'target coordinate', 0, max(width, height))
        x, y, w, h = rect
        if w <= 0 or h <= 0 or x+w > width or y+h > height:
            raise ValueError('Evidence target outside image: ' + str(target))
    return value


def scene_data(plan, scene):
    p = plan['project']
    data = {'width': p['width'], 'height': p['height'], 'fps': float(Fraction(p['fps'])),
        'frames': scene['end_frame']-scene['start_frame'], 'recipe': scene['recipe'],
        'params': scene['params'], 'accent': p['accent'], 'foreground': p['foreground'],
        'font': {**p['font'], 'url': Path(p['font']['file']).as_uri()},
        'assets': {k: Path(v).as_uri() for k, v in scene['assets'].items()},
        'events': {eid: scene['events'][eid]['frame']-scene['start_frame'] for eid in consumed_events(scene)}}
    if 'geometry' in scene['assets']:
        data['geometry'] = geometry(scene)
    return data


def load_plan(filename):
    base = Path(filename).resolve().parent
    plan = read_json(filename)
    # SRT is checked before probing fonts or scene assets.
    try:
        plan['srt'] = local_file(plan['srt'], base)
        srt = Path(plan['srt']).read_text(encoding='utf-8-sig')
        ends = re.findall(r'-->\s*(\d+):(\d+):(\d+)[,.](\d{3})', srt)
        if not ends:
            raise ValueError('no timed cues')
    except (KeyError, ValueError, UnicodeError) as error:
        raise ValueError('A readable matching SRT is required: ' + str(error)) from error
    if plan.get('schema') != 'sancheng-scenes/v1':
        raise ValueError('Unknown scene plan schema')
    p = plan['project']
    if p.get('editor') != 'jianying':
        raise ValueError('This workflow requires editor=jianying')
    for key in ('width', 'height', 'total_frames'):
        integer(p[key], key, 1)
    rate = Fraction(str(p['fps']))
    if rate <= 0 or rate > 240:
        raise ValueError('Invalid FPS')
    last_ms = max(((int(h)*60+int(m))*60+int(s))*1000+int(ms) for h, m, s, ms in ends)
    if Fraction(last_ms, 1000) > Fraction(p['total_frames']+1, 1) / rate:
        raise ValueError('SRT exceeds the final timeline; resolve timing before rendering')
    p['font']['file'] = local_file(p['font']['file'], base)
    integer(p['font']['weight'], 'font weight', 1)
    if not p['font'].get('family'):
        raise ValueError('Record the actual font family')
    for key in ('accent', 'foreground'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', p.get(key, '')):
            raise ValueError('Explicit #RRGGBB ' + key + ' required')
    recipes = {r['id']: r for r in read_json(RECIPES)['recipes']}
    scenes = plan['scenes']
    ids, cursor = set(), 0
    for scene in scenes:
        sid = scene['id']
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', sid) or sid in ids:
            raise ValueError('Scene IDs must be unique stable identifiers')
        ids.add(sid)
        start = integer(scene['start_frame'], 'start_frame')
        end = integer(scene['end_frame'], 'end_frame', 1)
        if start != cursor or end <= start:
            raise ValueError('Main scenes must be ordered and contiguous from frame 0')
        cursor = end
        recipe = recipes.get(scene['recipe'])
        if recipe is None:
            raise ValueError('Unknown recipe: ' + str(scene['recipe']))
        params = scene.setdefault('params', {})
        assets = scene.setdefault('assets', {})
        for key in recipe['required_params']:
            if key not in params:
                raise ValueError(sid + ': missing parameter ' + key)
        for key in recipe['required_assets']:
            if key not in assets:
                raise ValueError(sid + ': missing asset ' + key)
        for key, value in assets.items():
            assets[key] = local_file(value, base)
        events = scene.get('events', {})
        if not isinstance(events, dict):
            raise ValueError('events must map stable IDs to absolute frame and basis')
        for eid, event in events.items():
            if not re.fullmatch(r'[a-zA-Z0-9_-]+', eid) or not isinstance(event, dict):
                raise ValueError('Invalid event ID/record')
            frame = integer(event['frame'], 'event frame')
            if not start <= frame < end or not isinstance(event.get('basis'), str) or not event['basis'].strip():
                raise ValueError('Event needs current SRT/observed basis and an in-scene frame')
        needs = scene.get('needs', [])
        if not isinstance(needs, list) or any(not isinstance(n, str) for n in needs):
            raise ValueError('needs must list the semantic tasks of this scene')
        if set(needs)-set(recipe['semantics']):
            note = scene.get('coverage_note')
            if not isinstance(note, str) or not note.strip():
                raise ValueError(sid + ': coverage needs an explanation or a suitable recipe')
        if scene['recipe'] != 'custom-html':
            unknown = set(params)-set(recipe['editable_params'])-COMMON_PARAMS
            if unknown:
                raise ValueError(sid + ': unimplemented parameters: ' + ', '.join(sorted(unknown)))
        consumed_events(scene)
        if scene['recipe'] == 'custom-html':
            scene['html'] = local_file(scene['html'], base)
        else:
            zone = params.get('zone')
            if not isinstance(zone, list) or len(zone) != 4:
                raise ValueError(sid + ': explicit measured zone [x,y,w,h] required')
            for v in zone:
                number(v, 'zone', 0, 1)
            x, y, w, h = zone
            if w <= 0 or h <= 0 or x+w > 1.000001 or y+h > 1.000001:
                raise ValueError('Zone lies outside the frame')
            for box in p.get('protected_regions', []):
                bx, by, bw, bh = box
                if min(x+w, bx+bw) > max(x, bx) and min(y+h, by+bh) > max(y, by):
                    raise ValueError(sid + ': zone overlaps a protected face/subtitle region')
        for key in ('title', 'result', 'proof_label', 'before_label', 'after_label'):
            if key in params and (not isinstance(params[key], str) or not params[key].strip() or '\n' in params[key]):
                raise ValueError(key + ' must be nonempty single-line text')
        if 'enter_frames' in params:
            integer(params['enter_frames'], 'enter_frames', 1)
            if params['enter_frames'] >= end-start:
                raise ValueError('Entry must leave time for reading')
        for key in ('font_size', 'proof_font_size'):
            if key in params:
                number(params[key], key, 1, max(p['width'], p['height']))
        if 'stroke_width' in params: number(params['stroke_width'], 'stroke_width', 0.5, 32)
        for color in ('accent', 'stroke_color'):
            if color in params and not re.fullmatch(r'#[0-9a-fA-F]{6}', params[color]):
                raise ValueError('Explicit #RRGGBB ' + color + ' required')
        if params.get('image_fit', 'contain') not in ('contain', 'cover'):
            raise ValueError('image_fit must be contain or explicitly chosen cover')
        if scene['recipe'] == 'evidence-focus':
            for key in ('focus_x', 'focus_y'):
                number(params[key], key, 0, 1)
            number(params['zoom'], 'zoom', 1, 8)
        for key in ('items', 'steps', 'conclusions'):
            if key in params:
                values = params[key]
                if not isinstance(values, list) or not 2 <= len(values) <= 6 or any(not isinstance(v, str) or not v.strip() or '\n' in v for v in values):
                    raise ValueError(key + ' requires 2–6 single-line labels')
        if scene['recipe'] in ('source-conclusions', 'detail-overview'):
            if params.get('image_fit', 'contain') != 'contain':
                raise ValueError('Measured evidence recipes require image_fit=contain to preserve target coordinates')
            g = geometry(scene)
            targets = params.get('target_ids', [params.get('focus_target')])
            if (not isinstance(targets, list) or not targets or
                    any(not isinstance(t, str) or t not in g['targets'] for t in targets)):
                raise ValueError('Unknown measured evidence target')
            if scene['recipe'] == 'source-conclusions' and len(targets) != len(params['conclusions']):
                raise ValueError('Each conclusion needs its actual evidence target')
        if 'zoom' in params: number(params['zoom'], 'zoom', 1, 8)
        deps = scene.setdefault('depends_on', [])
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
            raise ValueError('depends_on must contain scene IDs')
    if not scenes or cursor != p['total_frames']:
        raise ValueError('Scenes must cover the complete final timeline')
    for scene in scenes:
        if any(d not in ids for d in scene['depends_on']):
            raise ValueError('Unknown scene dependency')
    for sound in plan.setdefault('sounds', []):
        sound['path'] = local_file(sound['path'], base)
        at = integer(sound['at_frame'], 'sound anchor')
        peak = integer(sound['peak_offset_frames'], 'sound peak offset')
        if at < peak or at >= p['total_frames']:
            raise ValueError('Sound anchor/peak falls outside the timeline')
        number(sound['gain'], 'sound gain', 0, 4)
    canonical(plan)  # Reject NaN/Infinity anywhere, including custom parameters.
    fingerprints(plan)  # Also validates dependency cycles.
    return plan


def fingerprints(plan):
    common = {'project': plan['project'], 'srt_hash': digest(Path(plan['srt']).read_bytes()),
              'font_hash': digest(Path(plan['project']['font']['file']).read_bytes()),
              'engine_hash': digest(Path(__file__).read_bytes()+TEMPLATE.read_bytes()+RECIPES.read_bytes()+RENDERER.read_bytes())}
    scenes = {s['id']: s for s in plan['scenes']}
    result, visiting = {}, set()

    def visit(sid):
        if sid in visiting:
            raise ValueError('Cyclic scene dependencies')
        if sid in result:
            return result[sid]
        visiting.add(sid)
        s = scenes[sid]
        files = {k: digest(Path(v).read_bytes()) for k, v in s['assets'].items()}
        if 'html' in s:
            files['html'] = digest(Path(s['html']).read_bytes())
        dependencies = {d: visit(d) for d in s['depends_on']}
        result[sid] = digest(canonical({'common': common, 'scene': s, 'files': files, 'dependencies': dependencies}))
        visiting.remove(sid)
        return result[sid]
    for sid in scenes:
        visit(sid)
    return result


def changed(before, after):
    a, b = fingerprints(before), fingerprints(after)
    dirty = [s['id'] for s in after['scenes'] if a.get(s['id']) != b[s['id']]]
    return {'changed': dirty, 'reusable': [s['id'] for s in after['scenes'] if s['id'] not in dirty],
            'ranges': [[s['start_frame'], s['end_frame']] for s in after['scenes'] if s['id'] in dirty],
            'sound_changed': before['sounds'] != after['sounds']}


def write_new(path, value):
    target = Path(path).resolve()
    if target.is_relative_to(ROOT.parent):
        raise ValueError('Project artifacts belong in the current project work/output directory')
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def revise(planfile, patchfile, output):
    before = load_plan(planfile)
    patch = read_json(patchfile)
    if set(patch) - {'reason', 'scenes', 'sounds'} or not isinstance(patch.get('reason'), str) or not patch['reason'].strip():
        raise ValueError('Revision needs a reason; project settings, timing and SRT stay locked')
    after = copy.deepcopy(before)
    lookup = {s['id']: s for s in after['scenes']}
    seen = set()
    for change in patch.get('scenes', []):
        sid = change['id']
        if sid not in lookup or sid in seen or set(change)-{'id', 'params', 'assets', 'recipe', 'html', 'depends_on', 'events', 'needs', 'coverage_note'}:
            raise ValueError('Unknown/duplicate scene or attempted timing/ID change')
        seen.add(sid)
        for k, v in change.items():
            if k == 'id':
                continue
            if k in ('params', 'assets', 'events'):
                lookup[sid].setdefault(k, {}).update(v)
            else:
                lookup[sid][k] = v
    if 'sounds' in patch:
        after['sounds'] = patch['sounds']
    # Relative paths in a patch resolve against the patch file, not the output file.
    base = Path(patchfile).resolve().parent
    for change in patch.get('scenes', []):
        scene = lookup[change['id']]
        for key in change.get('assets', {}):
            scene['assets'][key] = local_file(scene['assets'][key], base)
        if 'html' in change:
            scene['html'] = local_file(scene['html'], base)
    if 'sounds' in patch:
        for sound in after['sounds']:
            sound['path'] = local_file(sound['path'], base)
    with tempfile.TemporaryDirectory(prefix='sancheng-plan-') as temp:
        probe = Path(temp)/'plan.json'
        probe.write_bytes(canonical(after))
        after = load_plan(probe)
    delta = changed(before, after)
    if not delta['changed'] and not delta['sound_changed']:
        raise ValueError('Revision changes no render inputs')
    after.setdefault('history', []).append({'parent_sha256': digest(Path(planfile).read_bytes()),
        'reason': patch['reason'], 'status': 'requested', **delta})
    write_new(output, after)
    return {'output': str(Path(output).resolve()), **delta, 'acceptance': 'not_assessed'}


def run(argv):
    r = subprocess.run([str(x) for x in argv], capture_output=True, text=True)
    if r.returncode:
        raise ValueError((r.stderr or r.stdout)[-5000:])
    return r.stdout


def require_uisfx_selection(plan):
    path = ROOT.parent/'koubo-cut/scripts/uisfx.py'
    spec = importlib.util.spec_from_file_location('scene_uisfx_gate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_selection(plan, 'scene')


def sound_delay_samples(sound, rate):
    return round(float(Fraction(sound['at_frame']-sound['peak_offset_frames'], 1)/rate)*48000)


def sound_event_records(sounds, rate, total_frames):
    records = []
    for sound in sounds:
        # UISFX prepares PCM WAV; preserve the actual source duration in this build.
        with wave.open(sound['path'], 'rb') as stream:
            duration = Fraction(stream.getnframes(), stream.getframerate())
        start = Fraction(sound_delay_samples(sound, rate), 48000)
        records.append({**sound, 'sha256': digest(Path(sound['path']).read_bytes()),
                        'effective_range_frames': [math.floor(start*rate),
                            min(total_frames, math.ceil((start+duration)*rate))]})
    return records


def build(planfile, cache, output, ffmpeg, playwright_from, node='node', browser=None):
    plan = load_plan(planfile)
    selection = require_uisfx_selection(plan)
    out, cache = Path(output).resolve(), Path(cache).resolve()
    if out.suffix.lower() != '.mov' or out.exists():
        raise ValueError('Choose a new .mov output filename')
    if cache.is_relative_to(ROOT.parent) or out.is_relative_to(ROOT.parent):
        raise ValueError('Use project work/ for cache and outputs/ for delivery')
    ffmpeg = local_file(ffmpeg, Path.cwd())
    playwright_from = local_file(playwright_from, Path.cwd())
    identity = digest(canonical({'ffmpeg': [ffmpeg, Path(ffmpeg).stat().st_size, Path(ffmpeg).stat().st_mtime_ns],
                                 'node': run([node, '--version']).strip(), 'playwright_from': playwright_from}))
    if browser:
        browser = local_file(browser, Path.cwd())
        identity = digest(canonical([identity, browser, Path(browser).stat().st_size, Path(browser).stat().st_mtime_ns]))
    keys, p = fingerprints(plan), plan['project']
    rate = Fraction(str(p['fps']))
    cache.mkdir(parents=True, exist_ok=True)
    results, clips = [], []
    for scene in plan['scenes']:
        key = digest((keys[scene['id']]+identity).encode())
        entry = cache/key
        clip, marker = entry/'render.mov', entry/'render.json'
        reusable = False
        if clip.is_file() and marker.is_file():
            record = read_json(marker)
            reusable = record.get('key') == key and record.get('sha256') == digest(clip.read_bytes())
        if not reusable:
            with tempfile.TemporaryDirectory(prefix='.scene-', dir=cache) as temp:
                temp = Path(temp)
                if scene['recipe'] == 'custom-html':
                    html = Path(scene['html'])
                else:
                    data = scene_data(plan, scene)
                    text = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
                    html = temp/'index.html'
                    html.write_text(TEMPLATE.read_text().replace('__SCENE_DATA__', text), encoding='utf-8')
                frames = scene['end_frame']-scene['start_frame']
                stdout = run([node, RENDERER, '--html', html, '--output', temp/'render.mov',
                    '--width', p['width'], '--height', p['height'], '--fps', str(rate),
                    '--duration', format(float(Fraction(frames, 1)/rate), '.12f'),
                    '--ffmpeg', ffmpeg, '--playwright-from', playwright_from]+(['--browser', browser] if browser else []))
                record = json.loads(stdout.strip().splitlines()[-1])
                if record.get('frames') != frames:
                    raise ValueError('Rendered frame count differs from scene contract')
                entry.mkdir(exist_ok=True)
                (temp/'render.mov').replace(clip)
                marker.write_bytes(canonical({'key': key, 'sha256': digest(clip.read_bytes()), 'frames': frames,
                                              'layout_report': record.get('layout_report')}))
        clips.append(clip)
        results.append({'id': scene['id'], 'status': 'reused' if reusable else 'rendered', 'key': key,
                        'start_frame': scene['start_frame'], 'end_frame': scene['end_frame'],
                        'layout_report': record.get('layout_report'),
                        'events': {eid: {**scene['events'][eid], 'consumers': fields}
                                   for eid, fields in consumed_events(scene).items()}})
    out.parent.mkdir(parents=True, exist_ok=True)
    sound_events = sound_event_records(plan['sounds'], rate, p['total_frames'])
    with tempfile.TemporaryDirectory(prefix='.assemble-', dir=cache) as temp:
        temp = Path(temp)
        listing = temp/'concat.txt'
        listing.write_text(''.join("file '"+str(c).replace("'", "'\\''")+"'\n" for c in clips))
        video = temp/'visual.mov'
        run([ffmpeg, '-n', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', listing, '-map', '0:v', '-c:v', 'copy', '-an', video])
        if plan['sounds']:
            args = [ffmpeg, '-n', '-v', 'error', '-i', video]
            filters, labels = [], []
            for i, sound in enumerate(plan['sounds'], 1):
                args += ['-i', sound['path']]
                delay = sound_delay_samples(sound, rate)
                filters.append(f'[{i}:a]aresample=48000,volume={sound["gain"]},adelay={delay}S:all=1[a{i}]')
                labels.append(f'[a{i}]')
            duration = format(float(Fraction(p['total_frames'], 1)/rate), '.12f')
            filters.append(''.join(labels)+f'amix=inputs={len(labels)}:normalize=0,apad,atrim=duration={duration}[mix]')
            run(args+['-filter_complex', ';'.join(filters), '-map', '0:v', '-map', '[mix]', '-c:v', 'copy', '-c:a', 'pcm_s16le', out])
        else:
            # Link/copy exclusively; never overwrite an earlier imported delivery.
            with out.open('xb') as target, video.open('rb') as source:
                import shutil
                shutil.copyfileobj(source, target)
    report = {'schema': 'sancheng-build/v1', 'editor': 'jianying', 'output': str(out),
              'plan_sha256': digest(Path(planfile).read_bytes()), 'width': p['width'], 'height': p['height'],
              'sound_events': sound_events,
              'uisfx_selection': {**plan['uisfx_selection'], **selection},
              'sha256': digest(out.read_bytes()), 'frames': p['total_frames'], 'fps': str(rate),
              'alpha_codec': 'qtrle/argb', 'sounds': len(plan['sounds']), 'scenes': results,
              'acceptance': 'not_assessed', 'imported_to_jianying': False}
    write_new(str(out)+'.build.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('recipes')
    catalog = sub.add_parser('candidates')
    catalog.add_argument('--task', default='')
    catalog.add_argument('--assets', default='')
    validate = sub.add_parser('validate'); validate.add_argument('--plan', required=True)
    diff = sub.add_parser('diff'); diff.add_argument('--before', required=True); diff.add_argument('--after', required=True)
    edit = sub.add_parser('revise')
    for k in ('plan', 'patch', 'out'):
        edit.add_argument('--'+k, required=True)
    render = sub.add_parser('build')
    for k in ('plan', 'cache', 'output', 'ffmpeg', 'playwright-from'):
        render.add_argument('--'+k, required=True)
    render.add_argument('--node', default='node')
    render.add_argument('--browser')
    a = parser.parse_args()
    if a.command == 'recipes':
        result = read_json(RECIPES)
    elif a.command == 'candidates':
        result = candidates(a.task, [v for v in a.assets.split(',') if v])
    elif a.command == 'validate':
        p = load_plan(a.plan)
        result = {'ok': True, 'scenes': len(p['scenes']), 'frames': p['project']['total_frames'], 'editor': 'jianying',
                  'uisfx_selection': require_uisfx_selection(p)}
    elif a.command == 'diff':
        result = changed(load_plan(a.before), load_plan(a.after))
    elif a.command == 'revise':
        result = revise(a.plan, a.patch, a.out)
    else:
        result = build(a.plan, a.cache, a.output, a.ffmpeg, a.playwright_from, a.node, a.browser)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, ZeroDivisionError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
