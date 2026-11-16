"""Prepare an exact, local CRI song cue for the native MP4 writer.

The game adapter must supply the selected cue and its authored timing. This
module does not guess a song from an AWB ordinal, live ID, or the current time.
Only the selected song stream is supported; runtime SE/voices are not mixed.
"""
from array import array
from contextlib import closing
from dataclasses import dataclass
from fractions import Fraction
import math
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
from typing import Callable
import wave

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_PCM_BYTES = 96 * 1024 * 1024
MAX_SECONDS = 1200
MAX_CHUNK_FRAMES = 8192
_SLOT = threading.BoundedSemaphore(1)


def _fraction(value, name):
    if isinstance(value, Fraction):
        result = value
    elif type(value) is int or type(value) is float and math.isfinite(value):
        result = Fraction(str(value))
    else:
        raise ValueError("Invalid MV audio " + name + ".")
    if abs(result) > MAX_SECONDS:
        raise ValueError("MV audio " + name + " exceeds the preparation limit.")
    return result


def _sample(value):
    # Nearest sample, with half samples rounded away from zero. Never use a
    # binary-float timestamp to accumulate audio positions over the song.
    sign = -1 if value < 0 else 1
    value = abs(value)
    return sign * ((2 * value.numerator + value.denominator) // (2 * value.denominator))


@dataclass(frozen=True)
class MusicSelection:
    """Verified game selection, with times relative to export video time zero.

    At ``start_time`` the song starts at ``source_offset``. Positive start
    times retain a silent lead-in; a negative start trims the earlier song.
    ``gain`` is the selected song's static linear gain, supplied by the game
    adapter. Loops, pitch changes and changing bus mixes require another path.
    """
    sheet: str
    cue: str | int
    start_time: Fraction
    source_offset: Fraction
    gain: float
    music_id: int | None = None

    def __post_init__(self):
        if (not isinstance(self.sheet, str) or not 1 <= len(self.sheet) <= 240
                or "\0" in self.sheet):
            raise ValueError("The selected MV cue sheet is invalid.")
        if not ((isinstance(self.cue, str) and 1 <= len(self.cue) <= 240 and "\0" not in self.cue)
                or (type(self.cue) is int and 0 <= self.cue <= 0xffffffff)):
            raise ValueError("The selected MV song cue is invalid.")
        object.__setattr__(self, "start_time", _fraction(self.start_time, "start time"))
        object.__setattr__(self, "source_offset", _fraction(self.source_offset, "source offset"))
        if self.source_offset < 0:
            raise ValueError("The selected MV song source offset is negative.")
        if type(self.gain) not in (int, float) or not 0 <= self.gain <= 4:
            raise ValueError("The selected MV song gain is invalid.")
        if self.music_id is not None and (type(self.music_id) is not int or self.music_id < 0):
            raise ValueError("The selected MV music identity is invalid.")


def _clock(frame_count, fps_numerator, fps_denominator):
    if (type(frame_count) is not int or not 1 <= frame_count <= MAX_SECONDS * 120
            or type(fps_numerator) is not int or not 1 <= fps_numerator <= 120000
            or type(fps_denominator) is not int or not 1 <= fps_denominator <= 1001):
        raise ValueError("The MV export clock is invalid.")
    duration = Fraction(frame_count * fps_denominator, fps_numerator)
    if not 0 < duration <= MAX_SECONDS or not 1 <= Fraction(fps_numerator, fps_denominator) <= 120:
        raise ValueError("The MV export clock exceeds the preparation limit.")
    return duration


def _selected_stream(acb, awb, selection):
    """Follow the exact cue reference and preflight output before decoding."""
    from webtools.core import cri_audio_decode as cri
    if (not isinstance(acb, bytes) or not isinstance(awb, (bytes, type(None)))
            or len(acb) + len(awb or b"") > MAX_SOURCE_BYTES):
        raise ValueError("The selected MV audio exceeds its source memory limit.")
    catalog = cri.inspect_cues(acb)
    if catalog["sheet"] != selection.sheet:
        raise ValueError("The selected MV cue sheet does not match its asset.")
    key = "name" if isinstance(selection.cue, str) else "id"
    matches = [cue for cue in catalog["cues"] if cue[key] == selection.cue]
    if len(matches) != 1:
        raise ValueError("The selected MV song cue is missing or ambiguous.")
    cue = matches[0]
    if len(cue["waveforms"]) != 1:
        raise ValueError(cue.get("error") or "The selected MV song requires an unsupported layered mix.")
    waveform = cue["waveforms"][0]
    root, _, _ = cri._acb(acb)
    bank = awb if waveform["streaming"] else root.get("AwbFile")
    if not isinstance(bank, bytes):
        raise ValueError("The selected MV song requires its local audio bank.")
    entries = [entry for entry in cri.awb_entries(bank) if entry["id"] == waveform["awbId"]]
    if len(entries) != 1:
        raise ValueError("The selected MV song waveform is missing or ambiguous.")
    entry = entries[0]
    # Inspect only the bounded header. The existing decoder validates the
    # complete codec stream, encryption key, delay and padding independently.
    header = bank[entry["start"]:min(entry["start"] + 32, entry["end"])]
    signature = bytes(value & 0x7f for value in header[:4])
    if signature == b"HCA\0" and len(header) >= 24 and bytes(v & 0x7f for v in header[8:12]) == b"fmt\0":
        channels = header[12]
        rate = int.from_bytes(header[13:16], "big")
        frames = (int.from_bytes(header[16:20], "big") * 1024
                  - int.from_bytes(header[20:22], "big") - int.from_bytes(header[22:24], "big"))
    elif header.startswith(b"\x80\0") and len(header) >= 16:
        channels, rate = header[7], int.from_bytes(header[8:12], "big")
        frames = int.from_bytes(header[12:16], "big")
    else:
        raise ValueError("The selected MV song uses an unsupported codec header.")
    if (channels not in (1, 2) or rate not in (44100, 48000) or not 0 < frames <= MAX_SECONDS * rate
            or frames * channels * 2 > MAX_PCM_BYTES):
        raise ValueError("The selected MV song exceeds the supported PCM format or size.")
    return cue, entry, rate, channels, frames


class PreparedAudio:
    """Own one private decoded session and supply bounded interleaved PCM.

    The manifest contains no filesystem path. Retrying the same first_sample
    is safe: the writer consumes a chunk only after accepting it. Close on
    success, cancellation or failure to remove only this session's files.
    """
    def __init__(self, directory, reader, manifest, selection, should_stop):
        self._directory = directory
        self._reader = reader
        self._manifest = manifest
        self._selection = selection
        self._should_stop = should_stop
        self._lock = threading.Lock()

    @property
    def manifest(self):
        return dict(self._manifest)

    def read_chunk(self, first_sample: int, frame_count: int = MAX_CHUNK_FRAMES) -> bytes:
        if (type(first_sample) is not int or first_sample < 0 or type(frame_count) is not int
                or not 1 <= frame_count <= MAX_CHUNK_FRAMES):
            raise ValueError("The requested MV PCM chunk is invalid.")
        with self._lock:
            if self._reader is None:
                raise ValueError("The prepared MV audio session is closed.")
            if self._should_stop():
                raise InterruptedError("MV audio preparation was cancelled.")
            meta = self._manifest
            if first_sample > meta["sampleCount"]:
                raise ValueError("The requested MV PCM chunk starts beyond the export.")
            count = min(frame_count, meta["sampleCount"] - first_sample)
            width = meta["bytesPerFrame"]
            result = bytearray(count * width)
            leading = min(count, max(0, meta["startSample"] - first_sample))
            source_at = max(0, first_sample + leading - meta["startSample"] + meta["sourceOffsetFrames"])
            available = min(count - leading, max(0, meta["sourceFrameCount"] - source_at))
            if available:
                self._reader.setpos(source_at)
                pcm = self._reader.readframes(available)
                if len(pcm) != available * width:
                    raise ValueError("The prepared MV song PCM was truncated.")
                if self._selection.gain != 1:
                    values = array("h")
                    values.frombytes(pcm)
                    if sys.byteorder != "little":
                        values.byteswap()
                    values = array("h", (max(-32768, min(32767, round(v * self._selection.gain))) for v in values))
                    if sys.byteorder != "little":
                        values.byteswap()
                    pcm = values.tobytes()
                result[leading * width:(leading + available) * width] = pcm
            return bytes(result)

    def close(self):
        with self._lock:
            if self._reader is not None:
                self._reader.close()
                self._reader = None
            self._directory.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def prepare_audio(*, repo_root: Path, catalog_path: Path, selection: MusicSelection,
                  temporary_root: Path, video_frame_count: int, fps_numerator: int,
                  fps_denominator: int = 1, should_stop: Callable[[], bool] = lambda: False) -> PreparedAudio:
    """Read the exact sound mapping locally; decode through signed iOS codecs.

    Paths are supplied by the host, never by the page request. The catalog must
    be inside the selected runtime repository's GL/JP database directory. No
    missing source is downloaded. Native AAC uses the returned rate/channels
    and sampleCount, which is ceil(video duration * sampleRate).
    """
    from webtools.core import game_models as game, game_motion_audio as audio
    from elichika_ios.codecs import decode_cue
    if not isinstance(selection, MusicSelection):
        raise ValueError("A verified MV song selection is required.")
    duration = _clock(video_frame_count, fps_numerator, fps_denominator)
    root = Path(repo_root).resolve()
    catalog = Path(catalog_path).resolve()
    if (not any(catalog.is_relative_to(root / "assets/db" / region) for region in ("gl", "jp"))
            or not catalog.name.startswith(("asset_a_", "asset_i_")) or catalog.suffix != ".db" or not catalog.is_file()):
        raise ValueError("The MV song catalog is outside the selected runtime.")
    temporary_root = Path(temporary_root)
    if temporary_root.is_symlink() or temporary_root.resolve() != temporary_root or not temporary_root.is_dir():
        raise ValueError("MV audio needs an existing private temporary directory.")
    if not _SLOT.acquire(blocking=False):
        raise ValueError("Another MV song is being prepared.")
    session = reader = None
    try:
        if should_stop():
            raise InterruptedError("MV audio preparation was cancelled.")
        with closing(game._readonly(catalog)) as db:
            rows = db.execute("SELECT acb_pack_name,awb_pack_name FROM m_asset_sound WHERE sheet_name=? LIMIT 2", (selection.sheet,)).fetchall()
            if len(rows) != 1:
                raise ValueError("The selected MV cue sheet is missing or ambiguous in the local catalog.")
            acb_descriptor = audio._pack(db, rows[0][0])
            awb_descriptor = audio._pack(db, rows[0][1]) if rows[0][1] not in (None, "", "0") else None
        if acb_descriptor["size"] + (awb_descriptor["size"] if awb_descriptor else 0) > MAX_SOURCE_BYTES:
            raise ValueError("The selected MV audio exceeds its source memory limit.")
        class Job:
            def should_stop(self):
                return should_stop()
        deadline = time.monotonic() + 30
        extractor = game._extractor()
        acb = audio._read_pack(root, acb_descriptor, download=False, extractor=extractor, job=Job(), deadline=deadline)
        awb = (audio._read_pack(root, awb_descriptor, download=False, extractor=extractor, job=Job(), deadline=deadline)
               if awb_descriptor else None)
        cue, entry, rate, channels, declared_frames = _selected_stream(acb, awb, selection)
        sample_count = math.ceil(duration * rate)
        if sample_count * channels * 2 > MAX_PCM_BYTES:
            raise ValueError("The MV export exceeds the PCM preparation limit.")
        reserve = declared_frames * channels * 2 + 1024 * 1024
        if shutil.disk_usage(temporary_root).free < reserve:
            raise ValueError("There is not enough temporary space for the selected MV song.")
        session = tempfile.TemporaryDirectory(prefix=".mv-audio-", dir=temporary_root)
        decoded_path = Path(session.name) / "song.wav"
        decoded = decode_cue(acb, awb, selection.cue, decoded_path)
        del acb, awb
        if should_stop():
            raise InterruptedError("MV audio preparation was cancelled.")
        if (decoded["cue"] != cue["name"] or decoded["cueId"] != cue["id"] or decoded["waveId"] != entry["id"]
                or decoded_path.stat().st_size > MAX_PCM_BYTES + 4096):
            raise ValueError("The decoded MV song does not match the selected cue.")
        reader = wave.open(str(decoded_path), "rb")
        frames = reader.getnframes()
        if (reader.getframerate() != rate or reader.getnchannels() != channels or reader.getsampwidth() != 2
                or reader.getcomptype() != "NONE" or not 0 < frames <= declared_frames):
            raise ValueError("The decoded MV song PCM does not match its codec header.")
        start = _sample(selection.start_time * rate)
        offset = _sample(selection.source_offset * rate)
        first_source = offset + max(0, -start)
        first_output = max(0, start)
        if min(frames - first_source, sample_count - first_output) <= 0:
            raise ValueError("The selected MV song has no samples within the export clock.")
        manifest = {"schema": 1, "format": "s16le", "sampleRate": rate, "channels": channels,
                    "bytesPerFrame": channels * 2, "sampleCount": sample_count, "sourceFrameCount": frames,
                    "startSample": start, "sourceOffsetFrames": offset, "gain": selection.gain,
                    "sheet": selection.sheet, "cue": cue["name"], "cueId": cue["id"], "waveId": entry["id"],
                    "musicId": selection.music_id, "mix": "selected_song_stream",
                    "videoFrameCount": video_frame_count, "fpsNumerator": fps_numerator, "fpsDenominator": fps_denominator}
        prepared = PreparedAudio(session, reader, manifest, selection, should_stop)
        session = reader = None
        return prepared
    finally:
        if reader is not None:
            reader.close()
        if session is not None:
            session.cleanup()
        _SLOT.release()
