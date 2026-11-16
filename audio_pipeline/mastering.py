"""Auto-balance and clean-up mastering pass for a player's recorded take.

useRecording.ts (frontend) records the instrumental and the live mic as two
separate tracks instead of one pre-mixed stream (see
docs/superpowers/specs/2026-07-30-auto-balance-recording-design.md). This
module takes those two tracks and produces a single mastered wav: aligned to
the same start time, the vocal denoised/compressed/highpassed, both tracks
loudness-balanced against each other (vocal louder), then mixed and limited
so the result can't clip.

master_recording() (added in a later task) is the single entry point
scripts/server.py calls; the rest of this module is its implementation,
ordered in the same sequence the audio actually flows through: align ->
clean the vocal -> loudness-normalize each track -> mix -> limit.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ffmpeg
import soundfile as sf

from audio_pipeline.loudness import measure_loudness as _measure_loudness
from audio_pipeline.loudness import normalize_loudness as _apply_loudnorm
from audio_pipeline.transcode import transcode_to_wav

# Positive = the vocal (mic) track lags the instrumental in a raw two-track recording.
# The mic capture path (getUserMedia -> hardware -> driver buffering) has real warm-up
# latency the instrumental's already-decoded <audio> element source doesn't, so the
# singer's actual voice lands later in a raw recording than when they actually sang it --
# see the "Recording start offset" section of
# docs/superpowers/specs/2026-07-30-auto-balance-recording-design.md.
#
# This single global guess (tuned 0.0 -> 0.5 -> 0.2 across two real-user listening tests) never
# held across different mics/audio interfaces, each with their own real hardware capture latency.
# The fix isn't a better guess -- it's not guessing at all: `master_recording` now measures the
# actual offset directly from each take's own two tracks (see `_estimate_start_offset`), which
# adapts automatically to whatever mic was used with no calibration step required. An earlier
# version of this fix instead forwarded the frontend's click-track mic-latency calibration
# (`frontend/src/game/calibration.ts`) as a per-request override, reasoning it was already
# measuring "this same" latency per-device -- but that calibration measures speaker-output +
# *human clap-reaction time* + mic-input latency (see `useCalibration.ts`'s docstring), and the
# reaction-time component doesn't apply here at all: both tracks in a raw two-track recording are
# captured directly (mic buffer / decoded <audio> element), with no human reacting to a cue in the
# loop. Reusing that number systematically overcorrected -- confirmed by a real recording still
# sounding too-early-shifted after wiring it through. `master_recording` still accepts that value
# as `recording_offset_seconds`, now demoted to a fallback for when the direct per-take measurement
# can't get a confident read (e.g. a near-silent take). This constant is the last-resort fallback
# below that: a request with no confident measurement *and* no calibration on file yet.
_RECORDING_OFFSET_SECONDS = 0.2

# How far in either direction _estimate_start_offset will look for the real lag. Generous relative
# to any plausible mic/interface hardware latency (which runs tens to a couple hundred ms) so it
# comfortably covers that case, without being so wide that a spurious rhythmic coincidence far from
# the true lag can outscore it.
_MAX_AUTO_OFFSET_SECONDS = 1.5


def _correct_start_offset(
    vocal_path: Path,
    instrumental_path: Path,
    output_dir: Path,
    offset_seconds: float = _RECORDING_OFFSET_SECONDS,
) -> tuple[Path, Path]:
    """Trim ``offset_seconds`` off whichever track leads, so both start at the
    same real moment. Positive ``offset_seconds`` means the vocal lags (the
    common case, see the module docstring) -- trims that many seconds off the
    *front* of the vocal track. Negative means the vocal leads -- trims off
    the instrumental's front instead. Zero is a no-op. A track that needs no
    trim is returned as its original path, with no read or write round-trip.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def trim_front(path: Path, seconds: float, name: str) -> Path:
        samplerate = sf.info(str(path)).samplerate
        data, _ = sf.read(path, start=int(round(seconds * samplerate)))
        trimmed_path = output_dir / name
        sf.write(trimmed_path, data, samplerate)
        return trimmed_path

    if offset_seconds > 0:
        vocal_path = trim_front(vocal_path, offset_seconds, "vocal_aligned.wav")
    elif offset_seconds < 0:
        instrumental_path = trim_front(instrumental_path, -offset_seconds, "instrumental_aligned.wav")
    return Path(vocal_path), Path(instrumental_path)


def _estimate_start_offset(
    vocal_path: Path, instrumental_path: Path, max_offset_seconds: float = _MAX_AUTO_OFFSET_SECONDS
) -> float | None:
    """Measures the real start offset between *this specific take's* vocal and instrumental
    tracks directly, by cross-correlating their onset-strength envelopes over a window of
    candidate lags. Works with no clap, no calibration step, and no audible instrumental bleed in
    the vocal track (e.g. a singer on headphones) -- it doesn't need the two tracks to share actual
    audio content, only correlated *rhythm*: a singer's vocal onsets track the instrumental's beat
    (that's what singing along means), just picked up through a differently-delayed capture path.
    That correlation peak is exactly the real lag between the two tracks, measured fresh for every
    take on whatever mic/interface was actually used.

    Returns ``None`` rather than a low-confidence guess when the best-scoring lag doesn't stand out
    clearly from the rest of the window (e.g. a near-silent take with no real onset structure to
    correlate) -- callers should fall back to a fixed value instead of trusting noise.
    """
    import librosa  # local import: only this offset-measurement path needs it
    import numpy as np

    y_vocal, sr = librosa.load(str(vocal_path), sr=None, mono=True)
    y_instrumental, _ = librosa.load(str(instrumental_path), sr=sr, mono=True)

    bleed_offset = _bleed_offset(y_vocal, y_instrumental, sr, max_offset_seconds)
    if bleed_offset is not None:
        return bleed_offset

    hop_length = 512
    onset_vocal = librosa.onset.onset_strength(y=y_vocal, sr=sr, hop_length=hop_length)
    onset_instrumental = librosa.onset.onset_strength(y=y_instrumental, sr=sr, hop_length=hop_length)

    if np.std(onset_vocal) == 0 or np.std(onset_instrumental) == 0:
        return None
    # Zero-mean, unit-variance envelopes so the score curve swings around zero and a real
    # alignment shows up as a peak instead of riding on the envelopes' constant offset.
    onset_vocal = (onset_vocal - onset_vocal.mean()) / onset_vocal.std()
    onset_instrumental = (onset_instrumental - onset_instrumental.mean()) / onset_instrumental.std()

    max_lag_frames = max(1, int(round(max_offset_seconds * sr / hop_length)))
    lags = np.arange(-max_lag_frames, max_lag_frames + 1)
    scores = np.empty(len(lags))

    for i, lag in enumerate(lags):
        # Positive lag = the vocal's onsets came `lag` frames after the instrumental's (the vocal
        # lags), matching this module's offset sign convention -- slide the vocal envelope back by
        # `lag` frames before scoring how well it lines up with the instrumental's.
        if lag >= 0:
            a, b = onset_vocal[lag:], onset_instrumental
        else:
            a, b = onset_vocal, onset_instrumental[-lag:]
        n = min(len(a), len(b))
        scores[i] = float(np.dot(a[:n], b[:n])) / n if n > 0 else 0.0

    best_index = int(np.argmax(scores))
    peak = scores[best_index]
    overlap = min(len(onset_vocal), len(onset_instrumental)) - abs(int(lags[best_index]))
    # Significance gate: for unrelated z-scored envelopes the normalised correlation is ~N(0, 1/n),
    # so peak * sqrt(n) is a z-score. Unrelated or near-silent takes stay around 3 even at the
    # best of the window; a real rhythmic match scores well above 5.
    if peak <= 0 or overlap <= 0 or peak * np.sqrt(overlap) < 5:
        return None

    # Rhythmic music makes the curve repeat every beat, so several lags score almost the same.
    # Rhythm alone can't tell them apart; among those near-ties take the one closest to the
    # typical hardware latency prior rather than whichever won by noise.
    from scipy.signal import find_peaks

    peaks, _ = find_peaks(scores)
    candidates = [p for p in peaks if scores[p] >= 0.6 * peak] or [best_index]
    lag_seconds = lags * hop_length / sr
    chosen = min(candidates, key=lambda p: abs(lag_seconds[p] - _RECORDING_OFFSET_SECONDS))
    offset = float(lag_seconds[chosen])
    # Parabolic interpolation through the peak and its neighbours: sub-frame precision, since one
    # onset frame is ~12 ms.
    # Centroid of the peak's upper half: steadier than a 3-point parabola on a noisy, broad peak.
    lo = hi = chosen
    while lo > 0 and scores[lo - 1] >= 0.6 * scores[chosen] and chosen - lo < 2:
        lo -= 1
    while hi < len(scores) - 1 and scores[hi + 1] >= 0.6 * scores[chosen] and hi - chosen < 2:
        hi += 1
    w = scores[lo : hi + 1]
    offset = float(np.dot(w, lag_seconds[lo : hi + 1]) / w.sum())
    return offset


def _bleed_offset(y_vocal, y_instrumental, sr: int, max_offset_seconds: float) -> float | None:
    """Sample-accurate lag of the instrumental's speaker bleed inside the mic track, via
    PHAT-weighted cross-correlation. Bleed travels the same output+input latency path as the voice,
    so its lag is the take's offset. Returns ``None`` when there is no clear bleed peak (e.g. a
    headphone take), leaving the rhythm-only path to decide."""
    import numpy as np

    n = min(len(y_vocal), len(y_instrumental))
    if n == 0:
        return None
    max_lag = min(n - 1, int(round(max_offset_seconds * sr)))
    size = 1 << int(np.ceil(np.log2(n + max_lag)))
    cross = np.fft.rfft(y_vocal[:n], size) * np.conj(np.fft.rfft(y_instrumental[:n], size))
    magnitude = np.abs(cross)
    # Regularised PHAT: whiten so the direct-path peak is sharp, but don't amplify empty bins.
    cross /= magnitude + 1e-3 * (np.max(magnitude) + 1e-12)
    corr = np.fft.irfft(cross, size)
    # Index k holds lag k (vocal lags); negative lags wrap to the end.
    window = np.concatenate([corr[size - max_lag:], corr[: max_lag + 1]])
    best = int(np.argmax(window))
    peak = window[best]
    guard = max(1, int(0.002 * sr))
    rest = np.delete(window, slice(max(0, best - guard), best + guard + 1))
    if peak <= 0 or rest.size == 0 or peak < 8 * np.std(rest):
        return None
    # Room reflections arrive after the direct sound and can out-score it, so take the earliest
    # lag that is nearly as strong as the best one: that is the direct speaker-to-mic path.
    return float((int(np.argmax(window >= 0.9 * peak)) - max_lag) / sr)


_HIGHPASS_HZ = 90


_DENOISE_STRENGTH_DB = 6

def _clean_vocal(input_path: Path, output_dir: Path) -> Path:
    """Highpass (removes rumble/handling noise below ``_HIGHPASS_HZ``), denoise
    (ffmpeg's built-in ``afftdn`` -- no extra model download, see this
    feature's design spec for why not ``arnndn``), and compress
    (``acompressor``, evens out quiet/loud parts) the vocal track. Loudness
    balancing against the instrumental happens separately (see
    ``_apply_loudnorm``, added in a later task).

    ``afftdn`` runs well below its default strength (``nr=12``) and with noise tracking on
    (``tn=1``): the mic stream recorded by useRecording.ts already has the browser's own
    real-time ``noiseSuppression``/``autoGainControl`` applied (see useMicPitch.ts/
    useRecording.ts), so this is a light second pass, not the only line of defense (see this
    feature's design spec) -- running it at full static strength on top of already-denoised audio
    was stacking two denoise passes and smearing/muffling the vocal (reported as the recording
    sounding "blurry"/"unclear"). ``tn=1`` continuously re-estimates the noise profile instead of
    assuming one fixed profile for the whole take, which holds up better against a real take's
    varying room tone/silence-vs-voicing than the static default.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "vocal_cleaned.wav"

    try:
        (
            ffmpeg.input(str(input_path))
            .filter("highpass", f=_HIGHPASS_HZ)
            .filter("afftdn", nr=_DENOISE_STRENGTH_DB, tn=1)
            .filter("acompressor")
            .output(str(output_path))
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise RuntimeError(f"ffmpeg failed to clean vocal {input_path}: {stderr}") from exc

    return output_path


_VOCAL_TARGET_LUFS = -14
# Vocal raised from -16 -- feedback was the voice needed to sit louder in the mix. Widens the gap
# over the instrumental (still -18, unchanged) from 2 LU to 4 LU.
_INSTRUMENTAL_TARGET_LUFS = -18
_VOCAL_NOISE_FLOOR_LUFS = -42
_LIMITER_CEILING = 0.95


def _mix_and_limit(vocal_path: Path, instrumental_path: Path, output_path: Path) -> Path:
    """Mixes the two loudness-normalized tracks and applies a final limiter so
    the vocal's loudness boost can't clip the combined output. ``normalize=0``
    on ``amix`` keeps the loudnorm targets intact -- amix's own default
    (``normalize=1``) would auto-scale both inputs down by input count,
    undoing the deliberate vocal-vs-instrumental balance.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    vocal_stream = ffmpeg.input(str(vocal_path))
    instrumental_stream = ffmpeg.input(str(instrumental_path))

    try:
        (
            ffmpeg.filter([vocal_stream, instrumental_stream], "amix", inputs=2, duration="longest", normalize=0)
            .filter("alimiter", limit=_LIMITER_CEILING, level=0)
            .output(str(output_path))
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as exc:
        stderr_text = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise RuntimeError(f"ffmpeg failed to mix vocal and instrumental into {output_path}: {stderr_text}") from exc

    return output_path


def master_recording(
    vocal_path: str | Path,
    instrumental_path: str | Path,
    output_dir: str | Path,
    recording_offset_seconds: float | None = None,
) -> Path:
    """Auto-balance and clean up a player's recorded take -- the single entry
    point scripts/server.py calls. ``vocal_path``/``instrumental_path`` are
    the two separately-recorded tracks from useRecording.ts, in any
    container/codec ffmpeg can read (in practice, webm/opus).
    The actual start alignment is measured directly from this take's own two tracks (see
    ``_estimate_start_offset``) -- no guess or borrowed calibration figure needed, since it adapts
    to whatever mic/interface was really used. ``recording_offset_seconds``, when given, is used
    only as a fallback for when that direct measurement isn't confident (e.g. a near-silent take)
    -- in practice the requesting browser's own mic-latency calibration (see
    ``_RECORDING_OFFSET_SECONDS``'s docstring). ``None`` falls back past that to the module
    constant. Returns the path to the mastered wav (start-aligned, vocal cleaned and balanced
    louder than the instrumental, mixed, limited against clipping).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # The vocal and instrumental chains are independent ffmpeg subprocesses until the final mix, so
    # run each pair side by side (threads suffice: the work happens in ffmpeg, outside the GIL).
    with ThreadPoolExecutor(max_workers=1) as pool:
        vocal_future = pool.submit(transcode_to_wav, vocal_path, output_dir)
        instrumental_wav = transcode_to_wav(instrumental_path, output_dir)
        vocal_wav = vocal_future.result()

    offset_seconds = _estimate_start_offset(vocal_wav, instrumental_wav)
    if offset_seconds is None:
        offset_seconds = _RECORDING_OFFSET_SECONDS if recording_offset_seconds is None else recording_offset_seconds

    aligned_vocal_path, aligned_instrumental_path = _correct_start_offset(
        vocal_wav, instrumental_wav, output_dir, offset_seconds
    )
    def vocal_chain() -> Path:
        cleaned_vocal_path = _clean_vocal(aligned_vocal_path, output_dir)
        return _apply_loudnorm(
            cleaned_vocal_path, output_dir / "vocal_normalized.wav", _VOCAL_TARGET_LUFS,
            min_input_lufs=_VOCAL_NOISE_FLOOR_LUFS,  # a mic that only caught noise must not be boosted
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        vocal_future = pool.submit(vocal_chain)
        normalized_instrumental_path = _apply_loudnorm(
            aligned_instrumental_path, output_dir / "instrumental_normalized.wav", _INSTRUMENTAL_TARGET_LUFS
        )
        normalized_vocal_path = vocal_future.result()

    mastered_path = output_dir / "mastered.wav"
    _mix_and_limit(normalized_vocal_path, normalized_instrumental_path, mastered_path)
    return mastered_path


def measure_start_offset(vocal_path: str | Path, instrumental_path: str | Path) -> float:
    """Measures the real start offset between a raw two-track recording's
    vocal and instrumental tracks, for tuning ``_RECORDING_OFFSET_SECONDS``
    (see that constant's docstring and scripts/measure_recording_offset.py,
    which wraps this for one-off manual calibration against a real
    recording).

    Expects a take where the singer claps once, sharply, right on the song's
    first strong instrumental hit -- the clap is the vocal track's first
    onset; that instrumental hit is the instrumental track's first onset.
    Returns ``vocal_onset - instrumental_onset`` (positive = the vocal lags,
    matching ``_RECORDING_OFFSET_SECONDS``'s sign convention).
    """
    import librosa  # local import: only this one-off calibration path needs it

    def first_onset_seconds(path: str | Path) -> float:
        y, sr = librosa.load(str(path), sr=None, mono=True)
        onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units="frames")
        if len(onset_frames) == 0:
            raise ValueError(f"No onset detected in {path}")
        return float(librosa.frames_to_time(onset_frames[0], sr=sr))

    return first_onset_seconds(vocal_path) - first_onset_seconds(instrumental_path)
