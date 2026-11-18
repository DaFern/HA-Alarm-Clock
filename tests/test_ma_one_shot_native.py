"""Opt-in real MA helper/FFmpeg tests; synthetic tones only, no server or speaker.

Run using the isolated MA Python environment with MA_NATIVE_SOURCE pointing at
the source checkout and its FFmpeg directory on PATH. No test doubles are used.
"""

import asyncio
from array import array
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
NATIVE_SOURCE = os.environ.get('MA_NATIVE_SOURCE')


@unittest.skipUnless(NATIVE_SOURCE and shutil.which('ffmpeg'),
                     'Requires explicit MA_NATIVE_SOURCE and real FFmpeg')
class RealFFmpegTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(NATIVE_SOURCE)
        lock = json.loads((ROOT / 'prototypes/ma_one_shot/upstream.json').read_text())
        for rel, expected in lock['sha256'].items():
            if hashlib.sha256((source / rel).read_bytes()).hexdigest() != expected:
                raise RuntimeError('Native MA source hash differs: ' + rel)
        sys.path.insert(0, str(source))
        from music_assistant_models.enums import ContentType
        from music_assistant_models.media_items import AudioFormat
        cls.pcm = AudioFormat(content_type=ContentType.PCM_F32LE, sample_rate=48000,
                              bit_depth=32, channels=2)
        spec = importlib.util.spec_from_file_location('native_one_shot',
                ROOT / 'prototypes/ma_one_shot/adapter.py')
        cls.adapter = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.adapter
        spec.loader.exec_module(cls.adapter)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='ma-real-audio-',
                        dir='/data/v2/cache/opencode')
        self.addCleanup(self.directory.cleanup)
        self.voice = Path(self.directory.name) / 'finite-voice-surrogate.wav'
        # A distinguishable finite tone stands in for a rendered voice clip.
        samples = array('h', (int(0.2 * 32767 * math.sin(2 * math.pi * 880 * n / 48000))
                             for n in range(48000)))
        if sys.byteorder != 'little':
            samples.byteswap()
        with wave.open(str(self.voice), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48000)
            output.writeframes(samples.tobytes())

    async def song(self, *, frames=48000 * 4, closed=None):
        try:
            for start in range(0, frames, 4800):
                chunk = array('f')
                for n in range(start, min(start + 4800, frames)):
                    value = 0.2 * math.sin(2 * math.pi * 220 * n / 48000)
                    chunk.extend((value, value))
                if sys.byteorder != 'little':
                    chunk.byteswap()
                yield chunk.tobytes()
        finally:
            if closed is not None:
                closed.set()

    async def render(self, mixer, **kwargs):
        async with asyncio.timeout(20):
            data = b''.join([chunk async for chunk in mixer.wrap(
                'test-queue', 'session-1', self.song(**kwargs), self.pcm)])
        result = array('f')
        result.frombytes(data)
        if sys.byteorder != 'little':
            result.byteswap()
        return result[::2]

    def magnitude(self, samples, frequency, start, end):
        segment = samples[int(start * 48000):int(end * 48000)]
        real = sum(value * math.cos(2 * math.pi * frequency * n / 48000)
                   for n, value in enumerate(segment))
        imag = sum(value * math.sin(2 * math.pi * frequency * n / 48000)
                   for n, value in enumerate(segment))
        return 2 * math.hypot(real, imag) / len(segment)

    async def test_simultaneous_inputs_finite_voice_full_song_tail_and_no_replay(self):
        mixer = self.adapter.OneShotMixer()
        mixer.arm('test-queue', 'session-1', 'run-1', str(self.voice))
        samples = await self.render(mixer)
        self.assertAlmostEqual(len(samples) / 48000, 4, delta=0.03)
        self.assertAlmostEqual(self.magnitude(samples, 220, 0.2, 0.8), 0.05, delta=0.01)
        self.assertGreater(self.magnitude(samples, 880, 0.2, 0.8), 0.05)
        self.assertLess(self.magnitude(samples, 880, 2, 3), 0.001)
        self.assertAlmostEqual(self.magnitude(samples, 220, 2, 3), 0.05, delta=0.01)
        self.assertLess(max(abs(value) for value in samples), 1)
        replay = await self.render(mixer)
        self.assertAlmostEqual(self.magnitude(replay, 220, 0.2, 0.8), 0.2, delta=0.01)
        self.assertLess(self.magnitude(replay, 880, 0.2, 0.8), 0.001)

    async def test_short_song_is_not_extended_to_voice_duration(self):
        mixer = self.adapter.OneShotMixer()
        mixer.arm('test-queue', 'session-1', 'run-2', str(self.voice))
        samples = await self.render(mixer, frames=12000)
        self.assertAlmostEqual(len(samples) / 48000, 0.25, delta=0.03)

    async def test_voice_delay_is_music_time_not_silence_or_song_extension(self):
        mixer = self.adapter.OneShotMixer()
        mixer.arm('test-queue', 'session-1', 'delayed', str(self.voice),
                  levels=self.adapter.MixLevels(.25, .7, 2))
        samples = await self.render(mixer)
        self.assertAlmostEqual(len(samples) / 48000, 4, delta=.03)
        self.assertAlmostEqual(self.magnitude(samples, 220, .2, .8), .05, delta=.01)
        self.assertLess(self.magnitude(samples, 880, .2, .8), .001)
        self.assertGreater(self.magnitude(samples, 880, 2.2, 2.8), .05)
        self.assertLess(self.magnitude(samples, 880, 3.2, 3.8), .001)

    async def test_owned_music_only_restart_retains_background_gain_without_voice(self):
        mixer = self.adapter.OneShotMixer()
        mixer.bind_owner('test-queue', 'session-1', {
            'run_id': 'run-snoozed', 'item_id': 'test-item', 'music_gain': .25})
        samples = await self.render(mixer)
        self.assertAlmostEqual(self.magnitude(samples, 220, .2, .8), .05, delta=.01)
        self.assertLess(self.magnitude(samples, 880, .2, .8), .001)

    async def test_closing_consumer_releases_real_ffmpeg_and_song(self):
        mixer = self.adapter.OneShotMixer()
        mixer.arm('test-queue', 'session-1', 'run-3', str(self.voice))
        closed = asyncio.Event()
        stream = mixer.wrap('test-queue', 'session-1', self.song(closed=closed), self.pcm)
        async with asyncio.timeout(20):
            await anext(stream)
            await stream.aclose()
        self.assertTrue(closed.is_set())
        self.assertFalse(mixer._active)


if __name__ == '__main__':
    unittest.main(verbosity=2)
