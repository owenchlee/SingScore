// Mic/speaker latency calibration -- the same "play a click, have the user tap/clap on beat"
// approach UltraStar and similar games use. `useCalibration` schedules a click track and records
// detected tap/clap times, both already expressed in one AudioContext's own `currentTime` clock;
// the pure functions here turn those two timestamp lists into a single correction (seconds) that
// `useMicPitch` folds into every pitch sample's timestamp.

// A tap/clap more than this far from a given beat isn't a response to that beat -- either a missed
// beat (no tap counted) or noise unrelated to any beat (dropped rather than force-matched).
const MAX_MATCH_WINDOW_SECONDS = 0.4

// Fewer matched beats than this isn't enough data to trust -- the run is reported as inconclusive
// (null) rather than saving a wild guess.
const MIN_MATCHED_BEATS = 4

/** Greedily pairs each scheduled beat with the nearest not-yet-used tap within
 * `maxMatchWindowSeconds`, in beat order. Returns the per-beat (tap - beat) offsets for whichever
 * beats found a match -- a positive offset means the tap arrived late relative to the beat, which
 * is the expected sign of real speaker-output + mic-input + processing latency. */
export function pairBeatsToTaps(
  beatTimes: number[],
  tapTimes: number[],
  maxMatchWindowSeconds = MAX_MATCH_WINDOW_SECONDS,
): number[] {
  const usedTapIndices = new Set<number>()
  const offsets: number[] = []

  for (const beat of beatTimes) {
    let bestIndex = -1
    let bestDistance = Infinity
    for (let i = 0; i < tapTimes.length; i++) {
      if (usedTapIndices.has(i)) continue
      const distance = Math.abs(tapTimes[i] - beat)
      if (distance < bestDistance) {
        bestDistance = distance
        bestIndex = i
      }
    }
    if (bestIndex !== -1 && bestDistance <= maxMatchWindowSeconds) {
      usedTapIndices.add(bestIndex)
      offsets.push(tapTimes[bestIndex] - beat)
    }
  }

  return offsets
}

export interface CalibrationResult {
  offsetSeconds: number
  matchedBeats: number
  totalBeats: number
}

// Plausible range for the true latency: early (anticipating) clappers down to MIN, Bluetooth-class
// output plus clap timing up to MAX. Only candidate offsets inside it are considered.
const MIN_LATENCY_SECONDS = -0.2
const MAX_LATENCY_SECONDS = 0.8

// Last-resort tie-break target: the middle of the common real-world span (about -0.1 s anticipation to
// 0.5 s Bluetooth). When a late start or missed last beat makes two one-beat-apart offsets fit equally
// well, the one nearer this wins.
const TYPICAL_LATENCY_SECONDS = 0.2

// A tap within this of (beat + candidate offset) supports that candidate -- wide enough for human
// clap jitter, narrow enough not to bridge to a neighbouring beat.
const SUPPORT_WINDOW_SECONDS = 0.1

// Final pairing window around (beat + chosen offset): the usual match window, now re-centred.
const REFINE_WINDOW_SECONDS = MAX_MATCH_WINDOW_SECONDS

// Matched offsets farther than this from the median are stray or double taps, not clap jitter.
const INLIER_WINDOW_SECONDS = SUPPORT_WINDOW_SECONDS

// Variance of the per-beat (nearest tap - beat) offsets supporting `candidate`. A one-beat alias that
// borrows a stray tap fits more loosely than the true latency's jitter-only cluster.
function supportSpread(beatTimes: number[], tapTimes: number[], candidate: number): number {
  const offsets: number[] = []
  for (const b of beatTimes) {
    let best = Infinity
    for (const t of tapTimes) {
      if (Math.abs(t - b - candidate) < Math.abs(best - candidate)) best = t - b
    }
    if (Math.abs(best - candidate) <= SUPPORT_WINDOW_SECONDS) offsets.push(best)
  }
  const mean = offsets.reduce((sum, o) => sum + o, 0) / offsets.length
  return offsets.reduce((sum, o) => sum + (o - mean) ** 2, 0) / offsets.length
}

// Spreads closer than this are the same taps shifted by exactly one beat (float noise), not a real
// difference in fit -- fall through to the typical-latency tie-break.
const SPREAD_TIE_EPSILON = 1e-9

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid]
}

/** Estimates one latency for the whole run instead of pairing each beat with its nearest tap: once
 * the latency exceeds half the beat spacing, nearest-tap pairing locks onto the NEXT beat and comes
 * out a full beat wrong. Every (tap - beat) difference in the plausible range is a candidate; the one
 * the most beats agree with wins. Ties go first to the candidate that explains more taps (the
 * one-beat-earlier alias leaves the last beat's tap unexplained), then to the tighter fit (an alias
 * that borrows a stray tap scatters more than clap jitter), then to the one nearer
 * `TYPICAL_LATENCY_SECONDS` (a late start or missed last beat can make one-beat aliases fit equally). The offsets matched around it are reduced to their median --
 * resistant to a single mistimed tap the same way `smoothMidi` resists a pitch outlier (see
 * `game/pitch.ts`). Returns null when fewer than `MIN_MATCHED_BEATS` beats matched. */
export function computeCalibrationResult(
  beatTimes: number[],
  tapTimes: number[],
): CalibrationResult | null {
  let bestOffset = Infinity
  let bestSupport = 0
  let bestExplained = 0
  let bestSpread = Infinity
  for (const beat of beatTimes) {
    for (const tap of tapTimes) {
      const candidate = tap - beat
      if (candidate < MIN_LATENCY_SECONDS || candidate > MAX_LATENCY_SECONDS) continue
      const support = beatTimes.filter((b) =>
        tapTimes.some((t) => Math.abs(t - b - candidate) <= SUPPORT_WINDOW_SECONDS),
      ).length
      const explained = tapTimes.filter((t) =>
        beatTimes.some((b) => Math.abs(t - b - candidate) <= SUPPORT_WINDOW_SECONDS),
      ).length
      if (support < bestSupport || (support === bestSupport && explained < bestExplained)) continue
      const spread = supportSpread(beatTimes, tapTimes, candidate)
      const better =
        support > bestSupport ||
        explained > bestExplained ||
        spread < bestSpread - SPREAD_TIE_EPSILON ||
        (spread <= bestSpread + SPREAD_TIE_EPSILON &&
          Math.abs(candidate - TYPICAL_LATENCY_SECONDS) <
            Math.abs(bestOffset - TYPICAL_LATENCY_SECONDS))
      if (better) {
        bestSupport = support
        bestExplained = explained
        bestSpread = spread
        bestOffset = candidate
      }
    }
  }
  if (bestSupport < MIN_MATCHED_BEATS) return null

  let offsetSeconds = bestOffset
  let offsets: number[] = []
  // Two passes: the winning candidate may sit at the edge of its cluster; re-centre on the median.
  for (let pass = 0; pass < 2; pass++) {
    const center = offsetSeconds
    offsets = pairBeatsToTaps(
      beatTimes.map((b) => b + center),
      tapTimes,
      REFINE_WINDOW_SECONDS,
    ).map((o) => o + center)
    if (offsets.length < MIN_MATCHED_BEATS) return null
    offsetSeconds = median(offsets)
  }
  // Clap jitter is roughly Gaussian, so the mean of the inliers is a tighter estimate than the median.
  const inliers = offsets.filter((o) => Math.abs(o - offsetSeconds) <= INLIER_WINDOW_SECONDS)
  if (inliers.length > 0) offsetSeconds = inliers.reduce((sum, o) => sum + o, 0) / inliers.length

  return { offsetSeconds, matchedBeats: offsets.length, totalBeats: beatTimes.length }
}

const STORAGE_KEY = 'karaoke:calibrationOffsetSeconds'

/** The stored one-time calibration offset (seconds), or 0 (no correction) if none has been run yet
 * or storage isn't available (e.g. under test, or a browser with storage disabled). */
export function loadCalibrationOffsetSeconds(): number {
  if (typeof window === 'undefined' || !window.localStorage) return 0
  const raw = window.localStorage.getItem(STORAGE_KEY)
  if (raw === null) return 0
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : 0
}

/** Whether a real calibration result is on file, as opposed to `loadCalibrationOffsetSeconds`'s `0`
 * fallback for "never calibrated" -- callers that need to tell those two apart (e.g.
 * `useRecording`, which should let the server fall back to its own default rather than send an
 * unearned `0`) should check this first. */
export function hasCalibrationOffset(): boolean {
  if (typeof window === 'undefined' || !window.localStorage) return false
  return window.localStorage.getItem(STORAGE_KEY) !== null
}

export function saveCalibrationOffsetSeconds(offsetSeconds: number): void {
  if (typeof window === 'undefined' || !window.localStorage) return
  window.localStorage.setItem(STORAGE_KEY, String(offsetSeconds))
}

export function clearCalibrationOffsetSeconds(): void {
  if (typeof window === 'undefined' || !window.localStorage) return
  window.localStorage.removeItem(STORAGE_KEY)
}
