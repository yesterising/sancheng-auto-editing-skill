#!/usr/bin/env python3
"""Check final media locally; never import it or certify editorial/native acceptance."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def run(args):
    result = subprocess.run([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode or result.stderr.strip():
        raise ValueError(result.stderr.decode(errors='replace')[-3000:] or 'Media command failed')
    return result.stdout


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def check(args):
    media = Path(args.file).expanduser().resolve(strict=True)
    previous = sorted({str(Path(p).expanduser().resolve()) for p in getattr(args, 'previous_file', [])})
    if str(media) in previous:
        raise ValueError('Revision or redo requires a new delivery path; preserve the previous file')
    if not media.is_file() or media.stat().st_size == 0:
        raise ValueError('Formal media must be a readable non-empty file')
    sha = digest(media)
    if args.expected_sha256 and sha != args.expected_sha256:
        raise ValueError('Formal media differs from the recorded SHA-256')
    rate = Fraction(args.fps)
    if rate <= 0 or args.frames <= 0:
        raise ValueError('Expected FPS and frame count must be positive')
    duration = Fraction(args.frames, 1) / rate
    info = json.loads(run([args.ffprobe, '-v', 'error', '-show_streams', '-show_format',
                           '-of', 'json', media]))
    videos = [s for s in info['streams'] if s['codec_type'] == 'video']
    audios = [s for s in info['streams'] if s['codec_type'] == 'audio']
    if len(videos) != (0 if args.kind == 'audio' else 1) or len(audios) != (1 if args.audio == 'present' else 0):
        raise ValueError('Unexpected video/audio stream count')
    if args.kind == 'audio' and args.audio != 'present':
        raise ValueError('Audio delivery requires an audio stream')
    for stream in videos + audios:
        # A zero start is required, allowing only one media timestamp tick.
        tick = Fraction(stream['time_base'])
        if abs(Fraction(stream.get('start_time', info['format'].get('start_time', '0')))) > tick:
            raise ValueError('Media stream must start at 00:00')
        actual = Fraction(stream['duration']) if 'duration' in stream else Fraction(info['format']['duration'])
        # Compressed audio may include one codec packet of padding; video remains frame-exact below.
        tolerance = 1 / rate if stream['codec_type'] == 'video' else max(1 / rate, Fraction(1024, int(stream['sample_rate'])))
        if abs(actual - duration) > tolerance:
            raise ValueError('Media stream duration differs from the full timeline')
    video = videos[0] if videos else None
    if video:
        if (video['width'], video['height']) != (args.width, args.height):
            raise ValueError('Video dimensions differ from the project')
        if Fraction(video['avg_frame_rate']) != rate or Fraction(video['r_frame_rate']) != rate:
            raise ValueError('Video FPS differs from the locked constant frame rate')
        if not args.visible_frame:
            raise ValueError('Record visible-content sample frames for video delivery')
    if args.kind == 'overlay' and not args.alpha_frame:
        raise ValueError('Overlay delivery requires actual transparent sample frames')
    progress = run([args.ffmpeg, '-v', 'error', '-xerror', '-err_detect', 'explode', '-i', media,
                    '-map', '0:v?', '-map', '0:a?', '-fps_mode', 'passthrough',
                    '-progress', 'pipe:1', '-nostats', '-f', 'null', '-']).decode()
    decoded = [int(line.split('=', 1)[1]) for line in progress.splitlines() if line.startswith('frame=')]
    if video and (not decoded or decoded[-1] != args.frames):
        raise ValueError('Fully decoded video frame count differs from the project')
    samples = []
    for frame in sorted(set(args.alpha_frame + args.visible_frame)):
        if not video or not 0 <= frame < args.frames:
            raise ValueError('Sample frame is outside this video')
        # Inspect original alpha bytes at full resolution, without a composited preview.
        raw = run([args.ffmpeg, '-v', 'error', '-xerror', '-i', media, '-vf',
                   f'select=eq(n\\,{frame}),format=rgba', '-frames:v', '1',
                   '-pix_fmt', 'rgba', '-f', 'rawvideo', 'pipe:1'])
        if len(raw) != args.width * args.height * 4:
            raise ValueError('Sample did not decode a complete frame')
        alpha = raw[3::4]
        if frame in args.alpha_frame and min(alpha) == 255:
            raise ValueError('Expected transparent sample is completely opaque')
        if frame in args.visible_frame and max(alpha) == 0:
            raise ValueError('Expected visible sample is completely transparent')
        samples.append({'frame': frame, 'alpha_min': min(alpha), 'alpha_max': max(alpha)})
    if args.kind == 'overlay':
        formats = json.loads(run([args.ffprobe, '-v', 'error', '-show_pixel_formats', '-of', 'json']))
        pixel = next((p for p in formats['pixel_formats'] if p['name'] == video.get('pix_fmt')), {})
        if not pixel.get('flags', {}).get('alpha'):
            raise ValueError('Overlay video has no encoded alpha channel')
    if digest(media) != sha:
        raise ValueError('Formal media changed during verification')
    return {'schema': 'jianying-delivery-technical/v1', 'status': 'technical_pass',
            'file': str(media), 'sha256': sha, 'bytes': media.stat().st_size, 'previous_files': previous,
            'expected': {'kind': args.kind, 'width': args.width, 'height': args.height,
                         'fps': str(rate), 'frames': args.frames, 'audio': args.audio},
            'streams': info['streams'], 'format': info['format'],
            'full_decode': 'pass', 'decoded_video_frames': decoded[-1] if decoded else None,
            'alpha_samples': samples, 'visual_review': 'not_assessed',
            'audio_review': 'not_assessed' if audios else 'not_applicable',
            'jianying_native_compatibility': 'not_assessed', 'user_acceptance': 'not_assessed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', required=True)
    parser.add_argument('--kind', choices=('overlay', 'video', 'audio'), required=True)
    for key in ('width', 'height'):
        parser.add_argument('--' + key, type=int)
    parser.add_argument('--fps', required=True)
    parser.add_argument('--frames', type=int, required=True)
    parser.add_argument('--audio', choices=('present', 'absent'), required=True)
    parser.add_argument('--alpha-frame', type=int, action='append', default=[])
    parser.add_argument('--visible-frame', type=int, action='append', default=[])
    parser.add_argument('--expected-sha256')
    parser.add_argument('--previous-file', action='append', default=[],
                        help='Previous formal delivery; revisions and redos must use a different path')
    for key in ('ffmpeg', 'ffprobe', 'out'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    out = Path(args.out).expanduser().resolve()
    skill_root = Path(__file__).resolve().parents[2]
    if out == Path(args.file).expanduser().resolve() or out.is_relative_to(skill_root):
        parser.error('Write verification records to task work/, never over media or into skills')
    if out.exists():
        parser.error('Use a new verification record path')
    try:
        result = check(args)
    except (ValueError, KeyError, TypeError, OSError, ZeroDivisionError) as error:
        result = {'schema': 'jianying-delivery-technical/v1', 'status': 'failed',
                  'file': str(Path(args.file).expanduser().resolve()), 'error': str(error)}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'status': result['status'], 'report': str(out), 'error': result.get('error')}, ensure_ascii=False))
    return 0 if result['status'] == 'technical_pass' else 2


if __name__ == '__main__':
    sys.exit(main())
