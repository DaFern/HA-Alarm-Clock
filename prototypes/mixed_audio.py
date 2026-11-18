"""Offline single-song mixer proof. No HA imports, network access or playback."""

from __future__ import annotations

import argparse
from array import array
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sys
import wave

MAX_INPUT_BYTES = 32 * 1024 * 1024
BLOCK_FRAMES = 2048


@dataclass(frozen=True)
class PcmAudio:
    rate: int
    channels: int
    samples: array

    @property
    def frames(self):
        return len(self.samples) // self.channels


@dataclass(frozen=True)
class MixSettings:
    seconds: float = 30.0
    speech_delay: float = 2.0
    music_gain: float = 0.15
    speech_gain: float = 0.7
    fade_in: float = 0.1

    def validate(self):
        for name, low, high in (
            ("seconds", 0.001, 120), ("speech_delay", 0, 120),
            ("music_gain", 0, 1), ("speech_gain", 0, 1), ("fade_in", 0, 5),
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be finite and between {low} and {high}")


@dataclass
class RenderReport:
    frames: int = 0
    clipped_samples: int = 0
    speech_frames: int = 0
    rate: int = 0
    channels: int = 0


def read_pcm(path: Path) -> PcmAudio:
    """Read bounded, uncompressed 16-bit mono/stereo WAV; never decode or fetch URLs."""
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Input exceeds the prototype's 32 MiB limit")
    with wave.open(str(path), "rb") as wav:
        rate, channels = wav.getframerate(), wav.getnchannels()
        if wav.getcomptype() != "NONE" or wav.getsampwidth() != 2:
            raise ValueError("Prototype inputs must be uncompressed 16-bit PCM WAV")
        if channels not in (1, 2) or not 8000 <= rate <= 96000:
            raise ValueError("Use mono/stereo WAV at 8000–96000 Hz")
        frames = wav.getnframes()
        byte_count = frames * channels * 2
        if not frames or byte_count > MAX_INPUT_BYTES:
            raise ValueError("WAV is empty or declares too much audio")
        raw = wav.readframes(frames)
        if len(raw) != byte_count:
            raise ValueError("WAV data is truncated")
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return PcmAudio(rate, channels, samples)


def _speech_sample(speech: PcmAudio, position: float, channel: int, output_channels: int):
    """Linear interpolation for the proof, with mono/stereo conversion."""
    frame = int(position)
    next_frame = min(frame + 1, speech.frames - 1)
    fraction = position - frame

    def at(index):
        if output_channels == 1 and speech.channels == 2:
            return (speech.samples[index * 2] + speech.samples[index * 2 + 1]) / 2
        return speech.samples[index * speech.channels + (channel if speech.channels == 2 else 0)]

    return at(frame) * (1 - fraction) + at(next_frame) * fraction


def mixed_chunks(music: PcmAudio, speech: PcmAudio | None, settings: MixSettings, report: RenderReport):
    """Loop music only; speech is finite and is never wrapped or repeated."""
    settings.validate()
    total_frames = round(settings.seconds * music.rate)
    if not total_frames:
        raise ValueError("Duration is shorter than one sample frame")
    delay_frames = round(settings.speech_delay * music.rate)
    fade_frames = round(settings.fade_in * music.rate)
    report.rate, report.channels = music.rate, music.channels
    block = array("h")
    for frame in range(total_frames):
        music_frame = frame % music.frames
        voice_position = (frame - delay_frames) * speech.rate / music.rate if speech else -1
        speaking = speech is not None and 0 <= voice_position < speech.frames
        if speaking:
            report.speech_frames += 1
        fade = min(1, frame / fade_frames) if fade_frames else 1
        for channel in range(music.channels):
            value = music.samples[music_frame * music.channels + channel] * settings.music_gain
            if speaking:
                value += _speech_sample(speech, voice_position, channel, music.channels) * settings.speech_gain
            sample = round(value * fade)
            limited = max(-32768, min(32767, sample))
            report.clipped_samples += limited != sample
            block.append(limited)
        report.frames += 1
        if len(block) == BLOCK_FRAMES * music.channels:
            if sys.byteorder != "little":
                block.byteswap()
            yield block.tobytes()
            block = array("h")
    if block:
        if sys.byteorder != "little":
            block.byteswap()
        yield block.tobytes()


def render_preview(music_path: Path, speech_path: Path | None, output: Path,
                   settings: MixSettings = MixSettings()) -> RenderReport:
    """Write one finite WAV proof; fail rather than overwrite any existing file."""
    settings.validate()
    music = read_pcm(music_path)
    speech = read_pcm(speech_path) if speech_path is not None else None
    report = RenderReport()
    with output.open("xb") as destination:
        with wave.open(destination, "wb") as wav:
            wav.setparams((music.channels, 2, music.rate, 0, "NONE", "not compressed"))
            for chunk in mixed_chunks(music, speech, settings, report):
                wav.writeframesraw(chunk)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--music", type=Path, required=True, help="Local 16-bit PCM WAV song")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--speech", type=Path, help="Local 16-bit PCM WAV briefing")
    mode.add_argument("--music-only", action="store_true", help="Snooze restart proof: song starts at frame zero, no briefing")
    parser.add_argument("--output", type=Path, required=True, help="New output WAV; existing files are never overwritten")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--speech-delay", type=float, default=2)
    parser.add_argument("--music-gain", type=float, default=0.15)
    parser.add_argument("--speech-gain", type=float, default=0.7)
    args = parser.parse_args(argv)
    settings = MixSettings(args.seconds, args.speech_delay, args.music_gain, args.speech_gain)
    try:
        report = render_preview(args.music, args.speech, args.output, settings)
    except (OSError, ValueError, EOFError, wave.Error) as err:
        parser.exit(2, f"Mix not completed: {str(err) or 'Invalid or incomplete WAV header'}\n")
    print(json.dumps(asdict(report)))


if __name__ == "__main__":
    main()
