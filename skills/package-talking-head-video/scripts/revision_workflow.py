#!/usr/bin/env python3
"""Local formal-output review and one-attempt Jianying replacement receipts.

This helper never controls Jianying, rewrites drafts, or uploads media.
The agent inspects the extracted evidence and uses an observed editor interface.
"""
import argparse
from array import array
import html
import json
import math
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import scene_pack as sp

POLICY = sp.ROOT.parent / 'video-editing-playbook/assets/workflow-policy.json'


def external(path):
    path = Path(path).resolve()
    if path.is_relative_to(sp.ROOT.parent):
        raise ValueError('Use the project work/output directory')
    return path


def build_record(filename):
    record = sp.read_json(filename)
    if record.get('editor') != 'jianying':
        raise ValueError('Only Jianying deliveries are supported')
    media = sp.local_file(record['output'], Path(filename).resolve().parent)
    if sp.digest(Path(media).read_bytes()) != record['sha256']:
        raise ValueError('Formal output changed since its build record')
    record['output'] = media
    return record


def probe(media, ffprobe):
    return json.loads(sp.run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', media]))


def merged(ranges):
    result = []
    for start, end in sorted(ranges):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def changed_ranges(current, previous, ffprobe, audio_scope_fallbacks=None):
    # Compare recorded immutable build keys, not files re-hashed at both versions.
    old = {s['id']: s for s in previous['scenes']} if previous else {}
    visual = [[s['start_frame'], s['end_frame']] for s in current['scenes']
              if old.get(s['id'], {}).get('key') != s['key']]
    audio = []
    before = previous.get('sound_events', []) if previous else []
    after = current['sound_events']
    if before != after:
        rate = Fraction(current['fps'])
        # Keep ffprobe in the call contract, but never probe mutable historical sources.
        for version, events in (('previous', before), ('current', after)):
            for event in events:
                if event in before and event in after:
                    continue
                if 'effective_range_frames' in event:
                    bounds = event['effective_range_frames']
                    if not isinstance(bounds, list) or len(bounds) != 2:
                        raise ValueError('Recorded effective sound range must contain two frame bounds')
                    start = sp.integer(bounds[0], 'effective sound start')
                    end = sp.integer(bounds[1], 'effective sound end', 1)
                    if not start < end <= current['frames']:
                        raise ValueError('Recorded effective sound range falls outside the timeline')
                else:
                    sp.integer(event['at_frame'], 'sound anchor')
                    sp.integer(event['peak_offset_frames'], 'sound peak offset')
                    start = math.floor(Fraction(sp.sound_delay_samples(event, rate), 48000)*rate)
                    end = current['frames']
                    if not 0 <= start < end:
                        raise ValueError('Historical sound onset falls outside the timeline')
                    if audio_scope_fallbacks is not None:
                        audio_scope_fallbacks.append({'version': version, 'path': event['path'],
                            'range_frames': [start, end],
                            'reason': 'Build has no recorded effective sound range; review from known onset to timeline end without probing the historical source'})
                audio.append([start, end])
    if previous and 'sound_events' not in previous:
        raise ValueError('Rebuild the previous version to record exact sound review scope')
    return merged(visual), merged(audio)


def review_points(scene, fps):
    start, end = scene['start_frame'], scene['end_frame']
    settle = min(end-1, start+scene['params'].get('enter_frames', max(1, round(float(Fraction(fps))*.2))))
    points = {start, settle, (start+end-1)//2, end-1}
    windows = []
    context = max(1, math.ceil(Fraction(fps)/5))
    ids = sp.consumed_events(scene) if scene['recipe'] != 'custom-html' else scene.get('events', {})
    for eid in ids:
        event = scene['events'][eid]
        frame = event['frame']
        points.update(f for f in (frame-1, frame, frame+1) if start <= f < end)
        windows.append({'scene': scene['id'], 'event_id': eid, 'frame': frame,
            'basis': event['basis'], 'range_frames': [max(start, frame-context), min(end, frame+context+1)]})
    return sorted(points), windows


def sample(planfile, buildfile, directory, ffmpeg, ffprobe, previous=None, prior=None):
    plan = sp.load_plan(planfile)  # SRT remains the first production input check.
    current = build_record(buildfile)
    if current.get('plan_sha256') != sp.digest(Path(planfile).read_bytes()):
        raise ValueError('Build record does not match this scene plan')
    old = build_record(previous) if previous else None
    if old and any(old[k] != current[k] for k in ('width', 'height', 'frames', 'fps')):
        raise ValueError('Changed project timing/specification needs a new full review scope')
    round_number = 0
    if prior:
        prior_record = sp.read_json(prior)
        if prior_record.get('next_action') != 'revise':
            raise ValueError('Prior review does not permit another automatic repair')
        if not old or old['sha256'] != prior_record['formal_sha256']:
            raise ValueError('Repair must compare against the immediately reviewed formal version')
        round_number = prior_record['repair_round'] + 1
    if round_number > sp.read_json(POLICY)['max_automatic_repair_rounds']:
        raise ValueError('Automatic repair limit reached')
    audio_scope_fallbacks = []
    visual, audio = changed_ranges(current, old, ffprobe, audio_scope_fallbacks)
    out = external(directory)
    out.mkdir(parents=True, exist_ok=False)
    info = probe(current['output'], ffprobe)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    p = plan['project']
    if (video['width'], video['height']) != (p['width'], p['height']):
        raise ValueError('Formal output dimensions differ from the plan')
    if Fraction(video['avg_frame_rate']) != Fraction(p['fps']) or int(video['nb_frames']) != p['total_frames']:
        raise ValueError('Formal output FPS/frame count differs from the plan')
    if video.get('pix_fmt') not in ('argb', 'rgba', 'bgra', 'yuva444p10le', 'yuva444p12le'):
        raise ValueError('Formal overlay does not expose an alpha pixel format')
    rate = Fraction(p['fps'])
    samples, event_windows = [], []
    for scene in plan['scenes']:
        points, windows = review_points(scene, p['fps'])
        for start, end in visual:
            a, b = max(start, scene['start_frame']), min(end, scene['end_frame'])
            if b <= a:
                continue
            event_windows.extend(w for w in windows if a <= w['frame'] < b)
            for frame in (f for f in points if a <= f < b):
                png = out / f'frame-{frame:09d}.png'
                sp.run([ffmpeg, '-n', '-v', 'error', '-i', current['output'], '-vf',
                        f'select=eq(n\\,{frame})', '-frames:v', '1', '-fps_mode', 'vfr', png])
                samples.append({'frame': frame, 'scene': scene['id'], 'path': str(png)})
    for i, window in enumerate(event_windows):
        a, b = window['range_frames']; clip = out/f'event-{i:03d}.mov'
        sp.run([ffmpeg, '-n', '-v', 'error', '-i', current['output'], '-vf',
            f'trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS',
            '-an', '-c:v', 'qtrle', '-pix_fmt', 'argb', clip])
        window['path'] = str(clip)
    contact = out/'contact-sheet.html'
    contact.write_text('<!doctype html><meta charset="utf-8"><title>正式文件改动区间</title>'
        '<style>body{background:#151922;color:white;font:16px sans-serif}main{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}'
        'figure{margin:0}img{width:100%;background:repeating-conic-gradient(#333 0% 25%,#666 0% 50%) 0/20px 20px}figcaption{padding:8px}</style><main>'+
        ''.join('<figure><img src="'+Path(s['path']).as_uri()+'"><figcaption>'+html.escape(s['scene'])+
            ' · frame '+str(s['frame'])+'</figcaption></figure>' for s in samples)+'</main>', encoding='utf-8')
    has_audio = any(s['codec_type'] == 'audio' for s in info['streams'])
    audio_samples = []
    if has_audio:
        for i, (start, end) in enumerate(merged(visual + audio)):
            wav = out / f'audio-{i:03d}.wav'
            sp.run([ffmpeg, '-n', '-v', 'error', '-ss', str(float(Fraction(start, 1)/rate)),
                    '-i', current['output'], '-t', str(float(Fraction(end-start, 1)/rate)),
                    '-vn', '-c:a', 'pcm_s16le', wav])
            audio_samples.append({'range': [start, end], 'path': str(wav)})
    result = {'schema': 'jianying-local-review/v1', 'formal_output': current['output'],
              'formal_sha256': current['sha256'], 'repair_round': round_number,
              'visual_ranges': visual, 'audio_changed_ranges': audio,
              'audio_scope_fallbacks': audio_scope_fallbacks, 'frames': samples,
              'event_windows': event_windows, 'contact_sheet': str(contact),
              'audio_samples': audio_samples, 'technical_status': 'pass',
              'visual_status': 'not_assessed', 'audio_status': 'not_assessed' if audio_samples else 'not_applicable',
              'user_acceptance': 'not_assessed', 'next_action': 'inspect_evidence'}
    sp.write_new(out/'review.json', result)
    return result


def assess(reviewfile, findingsfile, output):
    review, findings = sp.read_json(reviewfile), sp.read_json(findingsfile)
    if sp.digest(Path(review['formal_output']).read_bytes()) != review['formal_sha256']:
        raise ValueError('Reviewed formal output changed')
    required = []
    for kind, samples in [('visual', review['frames']), ('audio', review['audio_samples'])]:
        status = findings.get(kind+'_status', 'not_assessed')
        allowed = ('pass', 'issues', 'unavailable') if samples else ('not_applicable',)
        if status not in allowed:
            raise ValueError(kind + ' needs an explicit evidence-based assessment')
        if samples:
            required.append(kind)
    observations = findings.get('observations', [])
    for kind in required:
        if findings[kind+'_status'] == 'unavailable':
            if not findings.get(kind+'_limitation'):
                raise ValueError('Record why evidence could not be inspected')
        else:
            samples = review['frames'] if kind == 'visual' else review['audio_samples']
            groups = {}
            for sample in samples:
                group = sample['scene'] if kind == 'visual' else tuple(sample['range'])
                groups.setdefault(group, set()).add(sample['path'])
            for evidence in groups.values():
                if not any(o.get('kind') == kind and o.get('evidence') in evidence and o.get('finding') for o in observations):
                    raise ValueError('Assessment needs observations for each changed scene/audio range')
    if findings.get('visual_status') == 'pass':
        for window in review.get('event_windows', []):
            nearby = {s['path'] for s in review['frames'] if s['scene'] == window['scene'] and abs(s['frame']-window['frame']) <= 1}
            nearby.add(window['path'])
            if not any(o.get('kind') == 'visual' and o.get('evidence') in nearby and o.get('finding') for o in observations):
                raise ValueError('Assessment needs observation at event ' + window['event_id'])
    issues = any(findings[k+'_status'] == 'issues' for k in required)
    unavailable = any(findings[k+'_status'] == 'unavailable' for k in required)
    action = 'stop_and_report' if unavailable else 'verify_delivery'
    if issues:
        action = 'revise' if review['repair_round'] < sp.read_json(POLICY)['max_automatic_repair_rounds'] else 'stop_and_report'
    result = {**review, **{k: v for k, v in findings.items() if k in (
        'visual_status', 'audio_status', 'visual_limitation', 'audio_limitation', 'observations')},
        'next_action': action, 'user_acceptance': 'not_assessed'}
    sp.write_new(output, result)
    return result


def sound_check(buildfile, ffmpeg, ffprobe, output):
    current = build_record(buildfile)
    has_audio = any(s['codec_type'] == 'audio' for s in probe(current['output'], ffprobe)['streams'])
    rate = Fraction(current['fps']); cues = current['sound_events']; checks = []
    for cue in cues:
        start, end = cue['effective_range_frames']
        record = {'path': cue['path'], 'anchor_frame': cue['at_frame'], 'range_frames': [start, end]}
        if not has_audio:
            checks.append({**record, 'status': 'missing_audio'}); continue
        if cue['gain'] == 0:
            checks.append({**record, 'status': 'intentional_zero_gain'}); continue
        r = subprocess.run([str(ffmpeg), '-v', 'error', '-ss', str(float(start/rate)),
            '-i', current['output'], '-t', str(float((end-start)/rate)), '-map', '0:a:0',
            '-ac', '1', '-ar', '48000', '-f', 'f32le', 'pipe:1'], capture_output=True)
        if r.returncode:
            checks.append({**record, 'status': 'unavailable', 'error': r.stderr.decode(errors='replace')[-500:]}); continue
        samples = array('f'); samples.frombytes(r.stdout)
        peak = max((abs(x) for x in samples), default=0)
        overlap = any(other is not cue and max(start,other['effective_range_frames'][0]) < min(end,other['effective_range_frames'][1]) for other in cues)
        checks.append({**record, 'peak': peak, 'status': 'ambiguous_overlap' if overlap else
                       'present' if peak > 1/32768 else 'no_energy'})
    result = {'schema':'sancheng-sfx-diagnostic/v1','formal_output':current['output'],
        'formal_sha256':current['sha256'],'checks':checks,'audibility':'not_assessed',
        'scope':'Energy in the rendered overlay SFX track only; overlaps cannot prove individual cues. Mix with source speech still needs listening.'}
    sp.write_new(output,result)
    return result


def begin_replacement(oldfile, newfile, targetfile, requestfile, ledger):
    old, new = build_record(oldfile), build_record(newfile)
    for key in ('width', 'height', 'frames', 'fps'):
        if old[key] != new[key]:
            raise ValueError('Replacement must preserve project specifications and timing')
    target, request = sp.read_json(targetfile), sp.read_json(requestfile)
    observed_path = target.get('media_path')
    if (target.get('editor') != 'jianying' or not isinstance(observed_path, str) or
            str(Path(observed_path).expanduser().resolve()) != old['output']):
        raise ValueError('Observed Jianying target must reference the exact old delivery')
    target['media_path'] = old['output']
    for key in ('project', 'material_id', 'observation'):
        if not isinstance(target.get(key), str) or not target[key].strip():
            raise ValueError('Record the observed project, media identity and UI/tool evidence')
    if not isinstance(target.get('placement'), dict):
        raise ValueError('Record existing placement/timing, or {} if not on the timeline')
    mode = target.get('replacement_mode', 'material')
    if mode not in ('material', 'clip'):
        raise ValueError('Unknown replacement mode; use material or clip')
    if mode == 'clip' and (len(target['placement']) != 1 or
            not isinstance(target.get('clip_locator'), str) or not target['clip_locator'].strip()):
        raise ValueError('Clip replacement requires one located timeline clip')
    if request.get('source') != 'user_message' or not request.get('id') or not request.get('feedback'):
        raise ValueError('A specific explicit user revision request is required')
    if (sp.read_json(POLICY).get('replacement_requires_explicit_editor_action', True) and
            (request.get('editor_action_authorized') is not True or
             request.get('editor_action') not in ('replace', 'relink') or
             not isinstance(request.get('authorization_quote'), str) or
             not request['authorization_quote'].strip() or
             request['authorization_quote'] not in request['feedback'])):
        raise ValueError('Explicit user authorization for the editor replacement action is required; ordinary revision delivers files')
    if old['sha256'] == new['sha256']:
        raise ValueError('No changed formal output to replace')
    root = external(ledger)
    root.mkdir(parents=True, exist_ok=True)
    claim = root/sp.digest(str(request['id']).encode())
    claim.mkdir()  # Atomic one-attempt claim; interrupted/failed attempts stay consumed.
    result = {'schema': 'jianying-replacement-attempt/v1', 'request': request, 'target': target,
              'old_output': old['output'], 'old_sha256': old['sha256'],
              'new_output': new['output'], 'new_sha256': new['sha256'],
              'status': 'in_progress', 'attempts': 1, 'native_mutation_performed_by_helper': False,
              'claim': str(claim), 'next_action': 'one_observed_native_replace_or_relink'}
    sp.write_new(claim/'attempt.json', result)
    return result


def finish_replacement(claimpath, observationfile):
    claim = external(claimpath)
    attempt = sp.read_json(claim/'attempt.json')
    observation = sp.read_json(observationfile)
    if observation.get('status') not in ('succeeded', 'failed', 'partial', 'unknown', 'unavailable'):
        raise ValueError('Record the observed replacement outcome')
    if not observation.get('evidence'):
        raise ValueError('Outcome needs native UI/tool evidence')
    if observation['status'] == 'succeeded':
        observed_path = observation.get('media_path')
        target = attempt['target']
        if target.get('replacement_mode', 'material') == 'clip':
            # Jianying's native Replace Clip creates a new media material.
            # A UI locator describes the observed clip; it is not a private UUID.
            same_target = (observation.get('clip_locator') == target['clip_locator'] and
                           isinstance(observation.get('material_id'), str) and
                           bool(observation['material_id'].strip()))
        else:
            same_target = observation.get('material_id') == target['material_id']
        if (not isinstance(observed_path, str) or str(Path(observed_path).expanduser().resolve()) != attempt['new_output'] or
                observation.get('placement') != target['placement'] or not same_target):
            raise ValueError('Success requires the same target/timing and the new media reference')
        if sp.digest(Path(attempt['new_output']).read_bytes()) != attempt['new_sha256']:
            raise ValueError('New delivery changed after the attempt began')
    result = {**attempt, 'status': observation['status'], 'observation': observation,
              'next_action': 'report_and_stop', 'native_outcome': 'agent_recorded_not_independently_verified'}
    sp.write_new(claim/'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('policy')
    review = sub.add_parser('sample')
    for key in ('plan', 'build', 'out-dir', 'ffmpeg', 'ffprobe'):
        review.add_argument('--'+key, required=True)
    review.add_argument('--previous-build'); review.add_argument('--prior-review')
    assessment = sub.add_parser('assess')
    for key in ('review', 'findings', 'out'):
        assessment.add_argument('--'+key, required=True)
    audio = sub.add_parser('sound-check')
    for key in ('build', 'ffmpeg', 'ffprobe', 'out'):
        audio.add_argument('--'+key, required=True)
    begin = sub.add_parser('begin-replacement')
    for key in ('old-build', 'new-build', 'target', 'request', 'ledger'):
        begin.add_argument('--'+key, required=True)
    finish = sub.add_parser('finish-replacement')
    finish.add_argument('--claim', required=True); finish.add_argument('--observation', required=True)
    args = parser.parse_args()
    if args.command == 'policy': result = sp.read_json(POLICY)
    elif args.command == 'sample':
        result = sample(args.plan, args.build, args.out_dir, args.ffmpeg, args.ffprobe,
                        args.previous_build, args.prior_review)
    elif args.command == 'assess': result = assess(args.review, args.findings, args.out)
    elif args.command == 'sound-check': result = sound_check(args.build, args.ffmpeg, args.ffprobe, args.out)
    elif args.command == 'begin-replacement':
        result = begin_replacement(args.old_build, args.new_build, args.target, args.request, args.ledger)
    else: result = finish_replacement(args.claim, args.observation)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try: main()
    except (ValueError, KeyError, TypeError, OSError, StopIteration) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
