"""Small, deterministic alarm sounds generated in memory, not downloaded."""

import io
import math
import struct
import wave


def make_tone(name: str) -> bytes:
    """Generate eight seconds of modest-amplitude mono WAV audio."""
    rate = 16000
    frequencies = {"chime": (523, 659, 784), "bell": (440, 880, 1320), "digital": (740, 940)}
    notes = frequencies[name]
    frames = bytearray()
    for sample in range(rate * 8):
        t = sample / rate
        phase = t % 1
        envelope = min(phase / 0.015, 1) * max(0, 1 - phase / 0.65)
        frequency = notes[int(t) % len(notes)]
        signal = math.sin(2 * math.pi * frequency * t)
        frames.extend(struct.pack("<h", int(signal * envelope * 6500)))
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)
    return output.getvalue()
