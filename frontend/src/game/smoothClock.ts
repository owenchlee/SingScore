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
const CORRECTION_GAIN = 0.15
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
  let anchorAudioTime: number | null = null
  let anchorFrameMs = 0
  let lastRawAudioTime = Number.NaN

  return (audioTimeSeconds, frameTimeMs, isPlaying, playbackRate = 1) => {
    if (!isPlaying) {
      // Paused/ended: nothing is advancing, so there's nothing to interpolate -- report the real
      // position and start fresh when playback resumes.
      anchorAudioTime = null
      lastRawAudioTime = audioTimeSeconds
      return audioTimeSeconds
    }

    if (anchorAudioTime === null) {
      anchorAudioTime = audioTimeSeconds
      anchorFrameMs = frameTimeMs
      lastRawAudioTime = audioTimeSeconds
      return audioTimeSeconds
    }

    const predicted = anchorAudioTime + ((frameTimeMs - anchorFrameMs) / 1000) * playbackRate

    if (audioTimeSeconds === lastRawAudioTime) {
      return Math.min(predicted, audioTimeSeconds + MAX_LEAD_SECONDS)
    }
    lastRawAudioTime = audioTimeSeconds

    const error = audioTimeSeconds - predicted
    if (Math.abs(error) > SNAP_THRESHOLD_SECONDS) {
      anchorAudioTime = audioTimeSeconds
      anchorFrameMs = frameTimeMs
      return audioTimeSeconds
    }

    const corrected = predicted + error * CORRECTION_GAIN
    anchorAudioTime = corrected
    anchorFrameMs = frameTimeMs
    return corrected
  }
}
