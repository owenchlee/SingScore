// `HTMLAudioElement.currentTime` is the right source of truth for *where the song is*, but it is
// not a smooth clock: browsers refresh it in coarse, uneven steps (often a few tens of ms), so
// consecutive animation frames can read the same value and then jump by several frames' worth at
// once. Positioning scrolling note bars straight off it makes them visibly stutter even at a
// steady 60fps. This keeps the audio clock as the authority but fills in the gaps between its
// updates using the frame timestamp, nudging toward each fresh reading instead of snapping to it.

// A correction bigger than this is a real discontinuity (a seek, or a long stall), not
// quantization noise -- snap to it rather than easing across a jump the player should see at once.
const SNAP_THRESHOLD_SECONDS = 0.25
// Fraction of the gap to a fresh audio reading that gets closed per update. Small enough that the
// bars don't visibly step when a reading lands, large enough that any real drift is gone in well
// under a second.
const MAX_REFRESH_GAP_SECONDS = 0.2
const MAX_SLEW = 0.1
// Absolute per-frame cap so a long (dropped-frame) advance never turns the slew into a visible step.
const MAX_SLEW_PER_FRAME_SECONDS = 0.005
// If the audio clock stops advancing while it still reports playing (buffering), the prediction
// would otherwise keep running ahead of the audio indefinitely.
const MAX_LEAD_SECONDS = 0.1

export type SmoothClock = (
  audioTimeSeconds: number,
  frameTimeMs: number,
  isPlaying: boolean,
  playbackRate?: number,
) => number

export function createSmoothClock(): SmoothClock {
  let lastOut: number | null = null
  let lastFrameMs = 0
  let lastRawAudioTime = Number.NaN
  // Seconds the output still has to gain (or lose) to match the latest audio reading.
  let owed = 0
  let lastReading = 0
  let lastReadingFrameMs = 0
  // Observed gap between fresh readings: a coarse clock legitimately goes this long without one.
  let refreshGap = 0

  return (audioTimeSeconds, frameTimeMs, isPlaying, playbackRate = 1) => {
    if (!isPlaying) {
      lastOut = null
      lastRawAudioTime = audioTimeSeconds
      return audioTimeSeconds
    }

    if (lastOut === null) {
      lastOut = audioTimeSeconds
      lastFrameMs = frameTimeMs
      lastRawAudioTime = audioTimeSeconds
      lastReading = audioTimeSeconds
      lastReadingFrameMs = frameTimeMs
      owed = 0
      return audioTimeSeconds
    }

    const advance = Math.max(0, ((frameTimeMs - lastFrameMs) / 1000) * playbackRate)
    lastFrameMs = frameTimeMs
    const predicted = lastOut + advance

    if (audioTimeSeconds !== lastRawAudioTime) {
      lastRawAudioTime = audioTimeSeconds
      const gap = (frameTimeMs - lastReadingFrameMs) / 1000
      if (gap < MAX_REFRESH_GAP_SECONDS) refreshGap = gap
      lastReadingFrameMs = frameTimeMs
      lastReading = audioTimeSeconds
      const error = audioTimeSeconds - predicted
      if (Math.abs(error) > SNAP_THRESHOLD_SECONDS) {
        lastOut = audioTimeSeconds
        owed = 0
        return audioTimeSeconds
      }
      owed = error
    }

    // Close the gap by speeding up or slowing down slightly, never by stepping, so output only moves forward.
    const maxSlew = Math.min(advance * MAX_SLEW, MAX_SLEW_PER_FRAME_SECONDS)
    const slew = Math.max(-maxSlew, Math.min(maxSlew, owed))
    owed -= slew
    const out = Math.min(predicted + slew, lastReading + Math.max(MAX_LEAD_SECONDS, refreshGap * 2 * playbackRate))
    lastOut = Math.max(lastOut, out)
    return lastOut
  }
}
