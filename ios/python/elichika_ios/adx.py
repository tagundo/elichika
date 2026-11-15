"""Bounded standard CRI ADX (encoding 3) PCM decoder.

This implements the public ADX 4-bit residual and second-order high-pass
predictor format used by the existing FFmpeg fallback. It accepts the same
18-byte/32-sample unencrypted blocks and rejects other encodings explicitly.
"""
import math
import struct
import time
import wave

MAX_PCM_BYTES = 256 * 1024 * 1024


def decode(stream, output, timeout=90):
    if not isinstance(stream, bytes) or not 24 <= len(stream) <= 128 * 1024 * 1024:
        raise ValueError("ADX input is empty, truncated or exceeds the input limit")
    marker, header = struct.unpack_from(">HH", stream)
    header += 4
    encoding, block_size, bits, channels = stream[4:8]
    rate, frames, cutoff = struct.unpack_from(">IIH", stream, 8)
    if (marker != 0x8000 or not 24 <= header <= len(stream) or stream[header - 6:header] != b"(c)CRI"
            or encoding != 3 or block_size != 18 or bits != 4 or not 1 <= channels <= 8
            or not 8000 <= rate <= 192000 or not 0 < frames * channels * 2 <= MAX_PCM_BYTES
            or stream[19] != 0 or not 0 <= cutoff < rate // 2):
        raise ValueError("ADX encoding, encryption or playback metadata is unsupported")
    blocks = (frames + 31) // 32
    a = math.sqrt(2) - math.cos(2 * math.pi * cutoff / rate)
    b = math.sqrt(2) - 1
    c = (a - math.sqrt((a + b) * (a - b))) / b
    # The original FFmpeg decoder rounds single-precision filter coefficients.
    def coefficient(value):
        return round(struct.unpack("f", struct.pack("f", value))[0])
    first, second = coefficient(c * 2 * 4096), coefficient(-(c * c) * 4096)
    history = [[0, 0] for _ in range(channels)]
    deadline = time.monotonic() + timeout
    actual_frames = 0
    with wave.open(str(output), "wb") as destination:
        destination.setnchannels(channels)
        destination.setsampwidth(2)
        destination.setframerate(rate)
        for block in range(blocks):
            if time.monotonic() >= deadline:
                raise TimeoutError("ADX decoding exceeded its time limit")
            count = min(32, frames - block * 32)
            frame_start = header + block * channels * block_size
            # Encoders commonly include the EOF block in the header's sample
            # count. The original fallback stops before that sentinel.
            if frame_start + 2 <= len(stream) and stream[frame_start] & 0x80:
                break
            if frame_start + channels * block_size > len(stream):
                raise ValueError("ADX waveform has truncated blocks")
            pcm = bytearray(count * channels * 2)
            for channel in range(channels):
                start = header + (block * channels + channel) * block_size
                scale = int.from_bytes(stream[start:start + 2], "big")
                if scale & 0x8000:
                    raise ValueError("ADX waveform ends before its declared sample count")
                previous, before = history[channel]
                for sample in range(32):
                    packed = stream[start + 2 + sample // 2]
                    residual = (packed & 15) if sample & 1 else packed >> 4
                    if residual >= 8:
                        residual -= 16
                    value = residual * scale + ((first * previous + second * before) >> 12)
                    value = max(-32768, min(32767, value))
                    before, previous = previous, value
                    if sample < count:
                        struct.pack_into("<h", pcm, (sample * channels + channel) * 2, value)
                history[channel] = [previous, before]
            destination.writeframesraw(pcm)
            actual_frames += count
    return {"backend": "elichika-adx", "decoder": "elichika-adx", "rate": rate,
            "sampleRate": rate, "channels": channels, "frames": actual_frames, "duration": actual_frames / rate}
