import { describe, expect, it } from 'vitest'
import { createSmoothClock } from './smoothClock'

const FRAME_MS = 1000 / 60

// Simulates an audio clock that only refreshes every `stepMs`, read once per 60fps frame.
function simulate(stepMs: number, frames: number, clock = createSmoothClock()) {
  const raw: number[] = []
  const smooth: number[] = []
  for (let i = 0; i < frames; i++) {
    const frameMs = i * FRAME_MS
    const audioTime = Math.floor(frameMs / stepMs) * stepMs / 1000
    raw.push(audioTime)
    smooth.push(clock(audioTime, frameMs, true))
  }
  return { raw, smooth }
}

function frameDeltas(values: number[]) {
  return values.slice(1).map((value, index) => (value - values[index]) * 1000)
}

describe('createSmoothClock', () => {
  it('turns a stepped audio clock into evenly spaced frames', () => {
    const { raw, smooth } = simulate(40, 240)
    const rawDeltas = frameDeltas(raw)
    const smoothDeltas = frameDeltas(smooth).slice(30) // past the initial convergence
    // The raw clock repeats a value then jumps; the smoothed one advances ~one frame every frame.
    expect(Math.min(...rawDeltas)).toBe(0)
    expect(Math.min(...smoothDeltas)).toBeGreaterThan(FRAME_MS * 0.5)
    expect(Math.max(...smoothDeltas)).toBeLessThan(FRAME_MS * 1.5)
  })

  it('stays close to the real audio position', () => {
    const { raw, smooth } = simulate(40, 240)
    for (let i = 30; i < raw.length; i++) {
      expect(Math.abs(smooth[i] - raw[i])).toBeLessThan(0.06)
    }
  })

  it('reports the real position while paused', () => {
    const clock = createSmoothClock()
    clock(1, 0, true)
    expect(clock(2.5, 100, false)).toBe(2.5)
  })

  it('snaps on a seek instead of easing across it', () => {
    const clock = createSmoothClock()
    clock(10, 0, true)
    clock(10.016, FRAME_MS, true)
    expect(clock(30, 2 * FRAME_MS, true)).toBe(30)
  })

  it('does not run away from a stalled audio clock', () => {
    const clock = createSmoothClock()
    clock(5, 0, true)
    expect(clock(5, 2000, true)).toBeCloseTo(5.1, 6)
  })
})
