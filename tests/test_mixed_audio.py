"""Sample-level offline tests of the isolated mixer, without HA or real songs."""

from dataclasses import replace
import importlib.util
import io
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

MODULE = Path(__file__).resolve().parents[1] / "prototypes" / "mixed_audio.py"
spec = importlib.util.spec_from_file_location("mixed_audio_prototype", MODULE)
mix = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mix
spec.loader.exec_module(mix)


def write_wav(path, samples, rate=8000, channels=1, width=2):
    with wave.open(str(path), "wb") as wav:
        wav.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        wav.writeframes(struct.pack(f"<{len(samples)}h", *samples) if width == 2 else bytes(samples))


class MixedAudioTests(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.TemporaryDirectory(prefix="alarm-mix-test-", dir="/data/v2/cache/opencode")
        self.addCleanup(self.cache.cleanup)
        self.root = Path(self.cache.name)
        self.music = self.root / "music.wav"
        self.speech = self.root / "speech.wav"
        self.output = self.root / "output.wav"
        write_wav(self.music, [1000] * 80)
        write_wav(self.speech, [2000] * 80)
        self.settings = mix.MixSettings(seconds=0.05, speech_delay=0.01,
            music_gain=0.2, speech_gain=0.5, fade_in=0)

    def render(self, speech=True, settings=None):
        report = mix.render_preview(self.music, self.speech if speech else None,
            self.output, settings or self.settings)
        return report, mix.read_pcm(self.output)

    def test_music_is_present_during_speech_not_paused(self):
        report, audio = self.render()
        self.assertEqual(list(audio.samples[:80]), [200] * 80)
        self.assertEqual(list(audio.samples[80:160]), [1200] * 80)
        self.assertEqual(list(audio.samples[160:]), [200] * 240)
        self.assertEqual(report.speech_frames, 80)
        self.assertEqual(report.clipped_samples, 0)

    def test_speech_does_not_repeat_when_music_loops(self):
        _, audio = self.render()
        self.assertEqual(audio.frames, 400)  # Five song loops, one speech segment.
        self.assertEqual(list(audio.samples).count(1200), 80)

    def test_music_only_restart_begins_at_song_frame_zero(self):
        write_wav(self.music, list(range(80)))
        self.speech.unlink()  # Restart must not even read a briefing file.
        report, audio = self.render(speech=False)
        self.assertEqual(list(audio.samples[:80]), [round(n * 0.2) for n in range(80)])
        self.assertEqual(list(audio.samples[:80]), list(audio.samples[80:160]))
        self.assertEqual(report.speech_frames, 0)

    def test_mono_speech_is_mixed_into_both_music_channels(self):
        write_wav(self.music, [1000, -1000] * 80, channels=2)
        _, audio = self.render()
        self.assertEqual(audio.channels, 2)
        self.assertEqual(list(audio.samples[160:164]), [1200, 800, 1200, 800])

    def test_stereo_speech_is_downmixed_for_mono_song(self):
        write_wav(self.speech, [2000, 4000] * 80, channels=2)
        _, audio = self.render()
        self.assertEqual(audio.samples[80], 1700)

    def test_different_sample_rates_preserve_speech_duration(self):
        write_wav(self.speech, [2000] * 160, rate=16000)
        report, audio = self.render()
        self.assertEqual(report.speech_frames, 80)
        self.assertEqual(audio.samples[80], 1200)
        self.assertEqual(audio.samples[160], 200)

    def test_clipping_is_limited_and_reported_for_both_polarities(self):
        write_wav(self.music, [30000, -30000] * 40)
        write_wav(self.speech, [30000, -30000] * 40)
        settings = replace(self.settings, seconds=0.01, speech_delay=0, music_gain=1, speech_gain=1)
        report, audio = self.render(settings=settings)
        self.assertEqual(list(audio.samples), [32767, -32768] * 40)
        self.assertEqual(report.clipped_samples, 80)

    def test_separate_gains_do_not_change_source_files(self):
        before_music, before_speech = self.music.read_bytes(), self.speech.read_bytes()
        _, audio = self.render(settings=replace(self.settings, music_gain=0.1, speech_gain=0.25))
        self.assertEqual(audio.samples[80], 600)
        self.assertEqual(self.music.read_bytes(), before_music)
        self.assertEqual(self.speech.read_bytes(), before_speech)

    def test_existing_output_and_inputs_are_never_overwritten(self):
        for path in (self.output, self.music, self.speech):
            with self.subTest(path=path.name):
                if not path.exists():
                    path.write_bytes(b"existing output")
                before = path.read_bytes()
                with self.assertRaises(FileExistsError):
                    mix.render_preview(self.music, self.speech, path, self.settings)
                self.assertEqual(path.read_bytes(), before)

    def test_invalid_settings_fail_before_creating_output(self):
        for settings in (
            replace(self.settings, seconds=float("inf")), replace(self.settings, seconds=121),
            replace(self.settings, seconds=0), replace(self.settings, music_gain=-0.1),
            replace(self.settings, speech_gain=float("nan")), replace(self.settings, music_gain=True),
            replace(self.settings, speech_delay=-1), replace(self.settings, fade_in=6),
        ):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                mix.render_preview(self.music, self.speech, self.output, settings)
            self.assertFalse(self.output.exists())

    def test_invalid_or_truncated_wav_is_rejected(self):
        self.speech.write_bytes(self.speech.read_bytes()[:-10])
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.render()
        self.assertFalse(self.output.exists())

    def test_unsupported_bit_depth_is_rejected(self):
        write_wav(self.speech, [128] * 80, width=1)
        with self.assertRaisesRegex(ValueError, "16-bit"):
            self.render()

    def test_empty_wav_is_rejected(self):
        write_wav(self.speech, [])
        with self.assertRaisesRegex(ValueError, "empty"):
            self.render()

    def test_oversized_input_fails_before_creating_output(self):
        with patch.object(mix, "MAX_INPUT_BYTES", 16), self.assertRaisesRegex(ValueError, "limit"):
            self.render()
        self.assertFalse(self.output.exists())

    def test_invalid_sample_rate_is_rejected(self):
        write_wav(self.speech, [2000] * 80, rate=4000)
        with self.assertRaisesRegex(ValueError, "8000"):
            self.render()

    def test_cli_music_only_does_not_require_speech(self):
        with patch("builtins.print"):
            mix.main(["--music", str(self.music), "--music-only", "--output", str(self.output), "--seconds", "0.01"])
        self.assertEqual(mix.read_pcm(self.output).frames, 80)

    def test_cli_invalid_header_has_clear_error_without_output(self):
        self.speech.write_bytes(b"RI")
        with patch("sys.stderr", new_callable=io.StringIO) as stderr, self.assertRaises(SystemExit) as error:
            mix.main(["--music", str(self.music), "--speech", str(self.speech), "--output", str(self.output)])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("WAV header", stderr.getvalue())
        self.assertFalse(self.output.exists())

    def test_fade_starts_quietly(self):
        _, audio = self.render(settings=replace(self.settings, fade_in=0.005))
        self.assertEqual(audio.samples[0], 0)
        self.assertEqual(audio.samples[20], 100)
        self.assertEqual(audio.samples[40], 200)

    def test_speech_longer_than_excerpt_is_bounded_without_repeating(self):
        report, audio = self.render(settings=replace(self.settings, seconds=0.015))
        self.assertEqual(audio.frames, 120)
        self.assertEqual(report.speech_frames, 40)

    def test_block_boundary_preserves_timing(self):
        report, audio = self.render(settings=replace(self.settings, seconds=0.3))
        self.assertEqual(audio.frames, 2400)
        self.assertEqual(report.speech_frames, 80)
        self.assertEqual(audio.samples[2047], 200)
        self.assertEqual(audio.samples[2048], 200)

    def test_both_frequencies_exist_simultaneously_in_output(self):
        rate = 8000
        write_wav(self.music, [round(4000 * math.sin(2 * math.pi * 400 * n / rate)) for n in range(800)])
        write_wav(self.speech, [round(4000 * math.sin(2 * math.pi * 800 * n / rate)) for n in range(800)])
        _, audio = self.render(settings=replace(self.settings, seconds=0.1, speech_delay=0))
        def amplitude(frequency):
            return abs(2 / 800 * sum(sample * math.sin(2 * math.pi * frequency * n / rate)
                for n, sample in enumerate(audio.samples)))
        self.assertAlmostEqual(amplitude(400), 800, delta=2)
        self.assertAlmostEqual(amplitude(800), 2000, delta=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
