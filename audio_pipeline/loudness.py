"""Two-pass loudness normalization via ffmpeg's `loudnorm` filter.

Shared by mastering.py (balances a player's recorded take before mixdown)
and pipeline.py (brings a freshly separated instrumental up to a normal
playback level). A Demucs/BS-RoFormer stem has no consistent loudness
target -- it's just whatever amplitude the separation model happened to
output, which can be far quieter than a commercially mastered track (see
NOTES.md's "Instrumental playback is too quiet" entry).
"""
import json
import os
import re
from pathlib import Path

import ffmpeg

_LOUDNORM_TP = -1.5
_LOUDNORM_LRA = 11


def measure_loudness(input_path: str | Path, target_i: float) -> dict:
    """First pass of ffmpeg's two-pass loudnorm: measures the real loudness
    stats ffmpeg needs to normalize accurately on the second pass (see
    ``normalize_loudness``), instead of relying on loudnorm's single-pass
    mode, which is a rougher, real-time-only estimate. Output audio is
    discarded (``-f null``) -- only the stats loudnorm prints to stderr as
    JSON matter.
    """
    try:
        _, stderr = (
            ffmpeg.input(str(input_path))
            .filter("loudnorm", i=target_i, tp=_LOUDNORM_TP, lra=_LOUDNORM_LRA, print_format="json")
            .output(os.devnull, format="null")
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as exc:
        stderr_text = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise RuntimeError(f"ffmpeg failed to measure loudness of {input_path}: {stderr_text}") from exc

    stderr_text = stderr.decode(errors="replace")
    match = re.search(r"\{[^{}]*\}", stderr_text, re.DOTALL)
    if not match:
        raise RuntimeError(f"ffmpeg loudnorm did not report measured stats for {input_path}")
    return json.loads(match.group(0))


def normalize_loudness(
    input_path: str | Path, output_path: str | Path, target_i: float, *, min_input_lufs: float = -70
) -> Path:
    """Second pass: normalizes ``input_path`` to ``target_i`` LUFS using the
    stats ``measure_loudness`` already measured, writing the result to
    ``output_path``. Input measuring below ``min_input_lufs`` is treated as
    silence/noise and resampled without gain.
    """
    stats = measure_loudness(input_path, target_i)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Digital silence / near-silence measures as -inf (or below loudnorm's valid
    # -99..0 range); there is nothing to normalize, so just resample unchanged.
    try:
        silent = float(stats["input_i"]) < min_input_lufs
    except (TypeError, ValueError):
        silent = True
    if silent:
        try:
            ffmpeg.input(str(input_path)).output(str(output_path), ar=44100).overwrite_output().run(
                capture_stdout=True, capture_stderr=True
            )
        except ffmpeg.Error as exc:
            stderr_text = exc.stderr.decode(errors="replace") if exc.stderr else ""
            raise RuntimeError(f"ffmpeg failed to resample {input_path}: {stderr_text}") from exc
        return output_path

    # loudnorm silently falls back to dynamic mode (squashing verses vs choruses)
    # when linear gain would break the peak ceiling. Apply the plain linear gain
    # ourselves and let a limiter catch only the peaks.
    gain_db = target_i - float(stats["input_i"])
    # alimiter limit is linear sample peak; keep ~1 dB margin below the TP ceiling
    # for inter-sample peaks. shortcut: sample-peak limiter, not true-peak.
    limit = 10 ** ((_LOUDNORM_TP - 1.0) / 20)
    try:
        (
            ffmpeg.input(str(input_path))
            .filter("volume", f"{gain_db}dB")
            .filter("alimiter", limit=limit, level="disabled", attack=0.1, release=1)
            .output(str(output_path), ar=44100)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as exc:
        stderr_text = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise RuntimeError(f"ffmpeg failed to normalize loudness of {input_path}: {stderr_text}") from exc

    return output_path
