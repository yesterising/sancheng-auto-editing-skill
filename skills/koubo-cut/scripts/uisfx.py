#!/usr/bin/env python3
"""Offline UISFX catalog and context-decided event preparation. No semantic auto-map."""
import argparse
import array
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / 'assets/uisfx'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def catalog():
    source = read_json(BANK/'SOURCE.json')
    if source['audio_license'] != 'CC0-1.0':
        raise ValueError('Only installed CC0 audio is accepted')
    for name, key in [('manifest.json', 'manifest_sha256'), ('LICENSE-AUDIO', 'license_sha256')]:
        if sha256(BANK/name) != source[key]:
            raise ValueError('Installed metadata checksum mismatch: '+name)
    manifest = read_json(BANK/'manifest.json')
    if manifest['license']['audio'] != 'CC0-1.0':
        raise ValueError('Manifest audio license is not CC0-1.0')
    return manifest, source, {a['pack']+'/'+a['cue']: a for a in manifest['assets']}


def source_file(asset, source):
    relative = asset['files']['mp3']['path']
    path = (BANK/relative).resolve()
    if not path.is_relative_to(BANK.resolve()) or not path.is_file():
        raise ValueError('Missing installed audio; no network fallback: '+relative)
    if path.stat().st_size != asset['files']['mp3']['bytes'] or sha256(path) != source['audio_sha256'][relative]:
        raise ValueError('Audio checksum mismatch: '+relative)
    return path


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value


def finite(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(name+' outside finite range')
    return value


def validate_plan(plan, assets):
    if plan.get('schema') != 'uisfx-events/v1':
        raise ValueError('Expected uisfx-events/v1')
    rate = Fraction(str(plan['fps']))
    if not 0 < rate <= 240:
        raise ValueError('Invalid FPS')
    total = integer(plan['total_frames'], 'total_frames', 1)
    if not isinstance(plan.get('events'), list):
        raise ValueError('events must be a list')
    ids = set()
    for event in plan['events']:
        eid = event.get('id', '')
        if not isinstance(eid, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', eid) or eid in ids:
            raise ValueError('Event IDs must be unique stable identifiers')
        ids.add(eid)
        for key in ('visual_action', 'speech_context', 'purpose', 'reason'):
            if not isinstance(event.get(key), str) or not event[key].strip():
                raise ValueError(f'{eid}: concrete {key} is required')
        anchor = integer(event.get('anchor_frame'), 'anchor_frame')
        if anchor >= total:
            raise ValueError(eid+': anchor outside timeline')
        if event.get('decision') == 'silence':
            if any(k in event for k in ('sound_id', 'source_anchor_ms', 'gain')):
                raise ValueError(eid+': silence must not contain sound selection')
            continue
        if event.get('decision') != 'sound':
            raise ValueError(eid+': choose sound or silence explicitly')
        if event.get('sound_id') not in assets:
            raise ValueError(eid+': unknown sound_id; no guessed fallback')
        asset = assets[event['sound_id']]
        if asset['loop']:
            raise ValueError(eid+': loops require a separately planned duration; one-shots only here')
        offset = finite(event.get('source_anchor_ms'), 'source_anchor_ms', 0, asset['duration']*1000)
        if anchor < round(Fraction(str(offset))*rate/1000):
            raise ValueError(eid+': audio would start before frame zero')
        if event.get('anchor_kind') not in ('contact', 'settle', 'speech_stress', 'reveal', 'motion_start'):
            raise ValueError(eid+': record the actual anchor_kind')
        finite(event.get('gain'), 'gain', 0.001, 4)
    return rate


def audio_profile(path):
    """Technical hints, not judgments about fit or substitutes for listening."""
    with wave.open(str(path), 'rb') as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (2, 2, 48000):
            raise ValueError('Expected 48 kHz stereo PCM16 WAV')
        samples = array.array('h', stream.readframes(stream.getnframes()))
    if sys.byteorder != 'little':
        samples.byteswap()
    windows = [sum(x*x for x in samples[i:i+960])/max(1, len(samples[i:i+960]))
               for i in range(0, len(samples), 960)]
    peak = max(windows, default=0)
    onset = next((i for i, energy in enumerate(windows) if energy >= peak*.01 and energy > 0), 0)
    return {'duration_ms': round(len(samples)/96, 3), 'onset_hint_ms': onset*10,
            'energy_peak_hint_ms': windows.index(peak)*10 if windows else 0,
            'sample_peak': round(max((abs(s) for s in samples), default=0)/32768, 6),
            'hints_only': True}


def ffmpeg_path():
    configured = os.environ.get('KOUBO_FFMPEG')
    executable = configured or shutil.which('ffmpeg')
    if not executable or not Path(executable).is_file():
        raise ValueError('Load koubo-cut/runtime.env; existing FFmpeg is required, no installation fallback')
    return str(executable)


def decode(source, target, ffmpeg):
    subprocess.run([ffmpeg, '-n', '-v', 'error', '-i', str(source), '-map', '0:a:0',
                    '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(target)], check=True)


def prepare(plan, out_dir):
    _, source, assets = catalog()
    rate = validate_plan(plan, assets)
    out = Path(out_dir).expanduser().resolve()
    if out.is_relative_to(ROOT.parent.resolve()):
        raise ValueError('Project output must be outside installed skills')
    if out.exists():
        raise FileExistsError('Use a new output directory: '+str(out))
    chosen = {e['sound_id'] for e in plan['events'] if e['decision'] == 'sound'}
    # Validate every source before making project files. Silence never calls FFmpeg.
    paths = {sid: source_file(assets[sid], source) for sid in chosen}
    ffmpeg = ffmpeg_path() if chosen else None
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.uisfx-', dir=out.parent) as temporary:
        stage = Path(temporary)/'prepared'
        stage.mkdir()
        profiles = {}
        for sid in sorted(chosen):
            name = sid.replace('/', '--')+'.wav'
            decode(paths[sid], stage/name, ffmpeg)
            profiles[sid] = audio_profile(stage/name)
        sounds, draft_sounds, decisions = [], [], []
        for event in plan['events']:
            decision = dict(event)
            if event['decision'] == 'sound':
                sid = event['sound_id']
                peak_frames = round(Fraction(str(event['source_anchor_ms']))*rate/1000)
                duration_ms = profiles[sid]['duration_ms']
                if event['source_anchor_ms'] >= duration_ms:
                    raise ValueError(event['id']+': source anchor exceeds decoded duration')
                decision['provenance'] = {'repository': source['repository'], 'commit': source['commit'],
                    'audio_license': source['audio_license'], 'source_sha256': sha256(paths[sid])}
                decision['audio_profile'] = profiles[sid]
                decision['frame_rounding_error_ms'] = round(float(peak_frames/rate*1000)-event['source_anchor_ms'], 4)
                sound = {**decision, 'path': str(out/(sid.replace('/', '--')+'.wav')),
                         'at_frame': event['anchor_frame'], 'peak_offset_frames': peak_frames,
                         'prepared_sha256': sha256(stage/(sid.replace('/', '--')+'.wav'))}
                sounds.append(sound)
                draft_sounds.append({'file': sound['path'],
                    'time': float(Fraction(sound['at_frame']-peak_frames, 1)/rate), 'vol': event['gain']})
            decisions.append(decision)
        report = {'schema': 'uisfx-resolved/v1', 'fps': str(rate), 'total_frames': plan['total_frames'],
                  'sounds': sounds, 'draft_sounds': draft_sounds, 'decisions': decisions,
                  'source_commit': source['commit'], 'imported_to_jianying': False}
        (stage/'resolved.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        stage.rename(out)
    return report


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def context_digest(plan, mode):
    # Bind the decision to current visuals and speech, independent of audio scheduling metadata.
    context = {k:v for k,v in plan.items() if k not in ('sounds', 'uisfx_selection', 'history')}
    files = [Path(plan['srt'])]
    if mode == 'scene':
        files.append(Path(plan['project']['font']['file']))
        for scene in plan['scenes']:
            files.extend(Path(p) for p in scene['assets'].values())
            if 'html' in scene:
                files.append(Path(scene['html']))
    elif mode == 'production':
        # The real producer owns its renderer/layout/source-map fields; bind all of them.
        context = {k:v for k,v in plan.items() if k != 'uisfx_selection'}
        files.append(Path(plan['source']))
        files.extend(Path(p) for p in plan.get('assets', {}).values())
        font = plan['project'].get('font')
        if isinstance(font, dict) and 'file' in font:
            files.append(Path(font['file']))
        for scene in plan['scenes']:
            files.extend(Path(p) for p in scene.get('assets', {}).values())
    else:
        video = Path(plan['video'])
        context = {**context, 'source_video_stat': [video.stat().st_size, video.stat().st_mtime_ns]}
    payload = {'mode':mode, 'plan':context, 'files':{str(p.resolve()):sha256(p) for p in files}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def check_review(plan, mode, report):
    def fail(message):
        raise ValueError('UISFX selection: '+message)
    if report.get('schema') != 'uisfx-resolved/v1':
        fail('prepare a resolved decision report first')
    _, source, assets = catalog()
    rate = validate_plan({'schema':'uisfx-events/v1', 'fps':report['fps'],
                         'total_frames':report['total_frames'], 'events':report['decisions']}, assets)
    project = plan['project'] if mode in ('scene', 'production') else plan
    if rate != Fraction(str(project['fps'])) or report['total_frames'] != project['total_frames']:
        fail('decision timing differs from current project')
    if mode == 'draft':
        duration = sum(Fraction(str(s['end']))-Fraction(str(s['src'])) for s in plan['segments'])
        if abs(duration-rate**-1*project['total_frames']) > rate**-1:
            fail('draft duration differs from reviewed timing')
    if not report['decisions'] or report['source_commit'] != source['commit']:
        fail('a nonempty current UISFX review is required, including when choosing silence')
    ranges = []
    scene_ranges = ({s['id']:(s['start_frame'], s['end_frame']) for s in plan['scenes']}
                    if mode in ('scene', 'production') else {})
    for event in report['decisions']:
        start = integer(event.get('start_frame'), 'review start_frame')
        end = integer(event.get('end_frame'), 'review end_frame', 1)
        if not start <= event['anchor_frame'] < end <= project['total_frames']:
            fail('decision anchor/range falls outside the reviewed interval')
        if mode in ('scene', 'production'):
            bounds = scene_ranges.get(event.get('scene_id'))
            if bounds is None or not bounds[0] <= start < end <= bounds[1]:
                fail('each decision must identify and stay inside its actual scene')
        ranges.append((start, end))
    cursor = 0
    for start, end in sorted(ranges):
        if start > cursor:
            fail('sound/silence decisions must cover the complete timeline')
        cursor = max(cursor, end)
    if cursor != project['total_frames']:
        fail('sound/silence decisions must cover the complete timeline')
    chosen = {e['id']:e for e in report['decisions'] if e['decision'] == 'sound'}
    if len(chosen) != len(report['sounds']):
        fail('sound decisions and prepared sounds differ')
    seen = set()
    for sound in report['sounds']:
        event = chosen.get(sound.get('id'))
        if event is None or sound['id'] in seen:
            fail('prepared sound has no unique decision')
        seen.add(sound['id'])
        if (sound['sound_id'], sound['at_frame'], sound['peak_offset_frames'], sound['gain']) != (
                event['sound_id'], event['anchor_frame'], round(Fraction(str(event['source_anchor_ms']))*rate/1000), event['gain']):
            fail('prepared sound differs from its context decision')
        source_file(assets[sound['sound_id']], source)
        if sha256(sound['path']) != sound.get('prepared_sha256'):
            fail('prepared audio changed; prepare and review again')
    def signature(sound, draft=False):
        if draft:
            path = Path(sound['file'])
            if not path.is_absolute():
                path = Path(plan['sfx_dir'])/path
            return [str(path.resolve()), sound['time'], sound.get('vol', .7)]
        return [str(Path(sound['path']).resolve()), sound['at_frame'], sound['peak_offset_frames'], sound['gain']]
    expected = ([{'file':s['path'], 'time':float(Fraction(s['at_frame']-s['peak_offset_frames'], 1)/rate),
                  'vol':s['gain']} for s in report['sounds']] if mode == 'draft' else report['sounds'])
    actual_rows = sorted(signature(s, mode == 'draft') for s in plan.get('sounds', []))
    expected_rows = sorted(signature(s, mode == 'draft') for s in expected)
    if actual_rows != expected_rows:
        fail('scheduled sounds differ from reviewed sounds')
    return {'status':'completed', 'sound_events':len(chosen),
            'silence_decisions':len(report['decisions'])-len(chosen)}


def validate_selection(plan, mode='scene'):
    selection = plan.get('uisfx_selection')
    if not isinstance(selection, dict) or selection.get('schema') != 'uisfx-selection/v1' or selection.get('status') != 'completed':
        raise ValueError('UISFX selection is required: run prepare and bind, even for silence')
    if selection.get('mode') != mode or selection.get('context_sha256') != context_digest(plan, mode):
        raise ValueError('UISFX selection is stale: current visuals or SRT changed; review and bind again')
    receipt = Path(selection['receipt']).expanduser()
    if not receipt.is_absolute() or not receipt.is_file() or sha256(receipt) != selection.get('receipt_sha256'):
        raise ValueError('UISFX selection receipt is missing or changed; review and bind again')
    return check_review(plan, mode, read_json(receipt))


def production_file(value, base):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Production inputs must declare a real local file path')
    path = Path(value).expanduser()
    path = (path if path.is_absolute() else base/path).resolve()
    if not path.is_file():
        raise ValueError('Production input file is missing: '+str(path))
    with path.open('rb') as stream:
        stream.read(1)
    return str(path)


def production_context(plan, base):
    # Match the SRT-first boundary without importing a renderer or native-draft runtime.
    try:
        plan['srt'] = production_file(plan['srt'], base)
        text = Path(plan['srt']).read_text(encoding='utf-8-sig')
        ends = re.findall(r'-->\s*(\d+):(\d+):(\d+)[,.](\d{3})', text)
        if not ends:
            raise ValueError('no timed cues')
    except (KeyError, ValueError, OSError, UnicodeError) as error:
        raise ValueError('A readable matching SRT is required: '+str(error)) from error
    project = plan.get('project')
    if not isinstance(project, dict):
        raise ValueError('Production project must contain FPS and total_frames')
    total = integer(project['total_frames'], 'total_frames', 1)
    rate = Fraction(str(project['fps']))
    if not 0 < rate <= 240:
        raise ValueError('Invalid FPS')
    last_ms = max(((int(h)*60+int(m))*60+int(s))*1000+int(ms) for h,m,s,ms in ends)
    if Fraction(last_ms, 1000) > Fraction(total+1, 1)/rate:
        raise ValueError('SRT exceeds the final timeline; resolve timing before binding')
    plan['source'] = production_file(plan.get('source'), base)
    font = project.get('font')
    if isinstance(font, dict) and 'file' in font:
        font['file'] = production_file(font['file'], base)
    scenes = plan.get('scenes')
    if not isinstance(scenes, list) or not scenes:
        raise ValueError('Production scenes must cover the complete timeline')
    ids, cursor = set(), 0
    for scene in scenes:
        sid = scene.get('id')
        if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', sid) or sid in ids:
            raise ValueError('Scene IDs must be unique stable identifiers')
        ids.add(sid)
        start = integer(scene['start_frame'], 'start_frame')
        end = integer(scene['end_frame'], 'end_frame', 1)
        if start != cursor or not start < end <= total:
            raise ValueError('Production scenes must be ordered and contiguous from frame 0')
        cursor = end
    if cursor != total:
        raise ValueError('Production scenes must cover the complete timeline')
    for owner in [plan] + scenes:
        assets = owner.get('assets', {})
        if not isinstance(assets, dict):
            raise ValueError('Production assets must map names to real local file paths')
        for key, value in assets.items():
            assets[key] = production_file(value, base)
    if not isinstance(plan.get('sounds'), list):
        raise ValueError('Production plan must declare its explicit sounds list, including [] for silence')
    return plan


def load_context(context_file, mode):
    if mode == 'scene':
        adapter = load_module('uisfx_scene_context', ROOT.parent/'package-talking-head-video/scripts/scene_pack.py')
        plan = adapter.load_plan(context_file)  # SRT is checked first; old plans can still be read for revision.
    elif mode == 'production':
        plan = production_context(read_json(context_file), Path(context_file).resolve().parent)
    elif mode == 'draft':
        plan = read_json(context_file)
        adapter = load_module('uisfx_draft_context', ROOT/'scripts/build_draft.py')
        adapter.validate_plan(plan, require_selection=False)
    else:
        raise ValueError('Unknown UISFX context mode')
    return plan


def bind_selection(context_file, receipt_file, mode, output):
    plan = load_context(context_file, mode)
    report = read_json(receipt_file)
    summary = check_review(plan, mode, report)
    plan['uisfx_selection'] = {'schema':'uisfx-selection/v1', 'status':'completed', 'mode':mode,
        'receipt':str(Path(receipt_file).resolve()), 'receipt_sha256':sha256(receipt_file),
        'context_sha256':context_digest(plan, mode)}
    target = Path(output).expanduser().resolve()
    if target.is_relative_to(ROOT.parent.resolve()):
        raise ValueError('Project output must be outside installed skills')
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return {'output':str(target), **summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('catalog', help='Acoustic discovery only; no text-to-sound mapping')
    listing.add_argument('--pack')
    listing.add_argument('--category')
    listing.add_argument('--include-loops', action='store_true')
    inspection = commands.add_parser('inspect', help='Inspect one real candidate before choosing its source anchor')
    inspection.add_argument('--id', required=True)
    compilation = commands.add_parser('prepare', help='Prepare context-decided events for existing scene_pack')
    compilation.add_argument('--plan', required=True)
    compilation.add_argument('--out-dir', required=True)
    binding = commands.add_parser('bind', help='Required sound/silence review bound to the current editing plan')
    binding.add_argument('--context', required=True)
    binding.add_argument('--receipt', required=True)
    binding.add_argument('--mode', choices=['scene', 'draft', 'production'], default='scene')
    binding.add_argument('--out', required=True)
    checking = commands.add_parser('check', help='Required selection check before native tracks or media import')
    checking.add_argument('--context', required=True)
    checking.add_argument('--mode', choices=['scene', 'draft', 'production'], default='scene')
    commands.add_parser('verify', help='Verify installed metadata and every MP3 checksum, offline')
    args = parser.parse_args()
    if args.command in ('catalog', 'inspect', 'verify'):
        manifest, source, assets = catalog()
    if args.command == 'catalog':
        if args.pack and args.pack not in {p['name'] for p in manifest['packs']}:
            raise ValueError('Unknown pack')
        if args.category and args.category not in {c['id'] for c in manifest['categories']}:
            raise ValueError('Unknown category')
        cues = {c['name']: c for c in manifest['cues']}
        selected = [{'id': sid, 'description': cues[a['cue']]['description'],
                     'duration': a['duration'], 'category': a['category'], 'loop': a['loop'],
                     'path': str(BANK/a['files']['mp3']['path'])}
                    for sid, a in assets.items() if (not args.pack or a['pack'] == args.pack)
                    and (not args.category or a['category'] == args.category)
                    and (args.include_loops or not a['loop'])]
        result = {'audio_license': source['audio_license'], 'packs': manifest['packs'],
                  'categories': manifest['categories'], 'count': len(selected), 'assets': selected}
    elif args.command == 'inspect':
        if args.id not in assets:
            raise ValueError('Unknown sound_id')
        path = source_file(assets[args.id], source)
        with tempfile.TemporaryDirectory(prefix='uisfx-inspect-') as temporary:
            wav = Path(temporary)/'candidate.wav'
            decode(path, wav, ffmpeg_path())
            result = {'id': args.id, 'path': str(path), 'audio_profile': audio_profile(wav),
                      'audio_license': source['audio_license'], 'source_sha256': sha256(path)}
    elif args.command == 'verify':
        for asset in assets.values():
            source_file(asset, source)
        result = {'verified': len(assets), 'one_shots': sum(not a['loop'] for a in assets.values()),
                  'loops': sum(a['loop'] for a in assets.values()), 'commit': source['commit'],
                  'audio_license': source['audio_license'], 'network_used': False}
    elif args.command == 'bind':
        result = bind_selection(args.context, args.receipt, args.mode, args.out)
    elif args.command == 'check':
        result = validate_selection(load_context(args.context, args.mode), args.mode)
    else:
        result = prepare(read_json(args.plan), args.out_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, ZeroDivisionError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
