"""Real local codec fixtures; no Jianying UI, source media, network, or cloud calls."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_delivery', ROOT / 'scripts/verify_delivery.py')
vd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vd)
BIN = Path('/Applications/ChatCut.app/Contents/Resources/app.asar.unpacked/node_modules/ffmpeg-ffprobe-static')
FFMPEG = shutil.which('ffmpeg') or str(BIN / 'ffmpeg')
FFPROBE = shutil.which('ffprobe') or str(BIN / 'ffprobe')


class DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path(FFMPEG).is_file() or not Path(FFPROBE).is_file():
            raise RuntimeError('Existing local FFmpeg/FFprobe required for real fixture tests')
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        for name, background, foreground in [('overlay', 0, 255), ('opaque', 255, 255), ('blank', 0, 0)]:
            pixels = bytearray()
            for y in range(16):
                for x in range(16):
                    alpha = foreground if 4 <= x < 12 and 4 <= y < 12 else background
                    pixels.extend((255, 20, 20, alpha))
            subprocess.run([FFMPEG, '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'rgba',
                            '-video_size', '16x16', '-framerate', '5', '-i', 'pipe:0',
                            '-frames:v', '5', '-c:v', 'qtrle', '-pix_fmt', 'argb', cls.root / (name + '.mov')],
                           input=bytes(pixels) * 5, check=True, capture_output=True)
        subprocess.run([FFMPEG, '-v', 'error', '-i', cls.root / 'opaque.mov', '-c:v', 'mpeg4',
                        '-pix_fmt', 'yuv420p', cls.root / 'no-alpha.mp4'], check=True, capture_output=True)
        subprocess.run([FFMPEG, '-v', 'error', '-i', cls.root / 'overlay.mov', '-c', 'copy',
                        '-output_ts_offset', '0.4', cls.root / 'shifted.mov'], check=True, capture_output=True)
        subprocess.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                        '-c:a', 'pcm_s16le', cls.root / 'sound.wav'], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def args(self, name='overlay.mov', **overrides):
        values = dict(file=str(self.root / name), kind='overlay', width=16, height=16, fps='5',
                      frames=5, audio='absent', alpha_frame=[0, 4], visible_frame=[2],
                      expected_sha256=None, previous_file=[], ffmpeg=FFMPEG, ffprobe=FFPROBE)
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_actual_transparent_media_fully_decodes(self):
        result = vd.check(self.args())
        self.assertEqual(result['status'], 'technical_pass')
        self.assertEqual(result['decoded_video_frames'], 5)
        self.assertEqual(result['alpha_samples'][0]['alpha_min'], 0)
        self.assertEqual(result['alpha_samples'][0]['alpha_max'], 255)
        self.assertEqual(result['jianying_native_compatibility'], 'not_assessed')
        self.assertEqual(result['visual_review'], 'not_assessed')

    def test_alpha_channel_alone_does_not_prove_transparency(self):
        with self.assertRaisesRegex(ValueError, 'completely opaque'):
            vd.check(self.args('opaque.mov'))

    def test_ordinary_mp4_cannot_be_transparent_delivery(self):
        with self.assertRaisesRegex(ValueError, 'opaque|alpha channel'):
            vd.check(self.args('no-alpha.mp4'))

    def test_blank_layer_does_not_count_as_visible_content(self):
        with self.assertRaisesRegex(ValueError, 'completely transparent'):
            vd.check(self.args('blank.mov'))

    def test_wrong_final_frame_count_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'frame count'):
            vd.check(self.args(frames=6, alpha_frame=[0]))

    def test_project_dimensions_and_exact_fps_are_required(self):
        for changes in ({'width': 32}, {'fps': '6'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                vd.check(self.args(**changes))

    def test_missing_required_audio_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'stream count'):
            vd.check(self.args(audio='present'))

    def test_audio_only_delivery_uses_same_timeline(self):
        result = vd.check(self.args('sound.wav', kind='audio', width=None, height=None,
                                    audio='present', alpha_frame=[], visible_frame=[]))
        self.assertEqual(result['status'], 'technical_pass')
        self.assertIsNone(result['decoded_video_frames'])

    def test_nonzero_media_start_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'start at 00:00'):
            vd.check(self.args('shifted.mov'))

    def test_audio_cannot_stop_before_full_timeline(self):
        with self.assertRaisesRegex(ValueError, 'duration'):
            vd.check(self.args('sound.wav', kind='audio', width=None, height=None, frames=10,
                               audio='present', alpha_frame=[], visible_frame=[]))

    def test_corrupt_file_is_not_accepted(self):
        corrupt = self.root / 'corrupt.mov'
        corrupt.write_bytes((self.root / 'overlay.mov').read_bytes()[:100])
        with self.assertRaises(ValueError):
            vd.check(self.args('corrupt.mov'))

    def test_stale_build_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            vd.check(self.args(expected_sha256='0' * 64))

    def test_expected_transparent_and_visible_ranges_cannot_be_omitted(self):
        for changes in ({'alpha_frame': []}, {'visible_frame': []}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                vd.check(self.args(**changes))

    def test_sample_outside_video_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            vd.check(self.args(alpha_frame=[5]))

    def test_revision_cannot_reuse_the_previous_delivery_path(self):
        with self.assertRaisesRegex(ValueError, 'new delivery path'):
            vd.check(self.args(previous_file=[str(self.root / 'overlay.mov')]))

    def test_new_file_records_its_previous_delivery_without_editing_it(self):
        previous = self.root / 'previous.mov'
        previous.write_bytes((self.root / 'overlay.mov').read_bytes())
        before = vd.digest(previous)
        result = vd.check(self.args(previous_file=[str(previous)]))
        self.assertEqual(result['previous_files'], [str(previous.resolve())])
        self.assertEqual(vd.digest(previous), before)


if __name__ == '__main__':
    unittest.main()
