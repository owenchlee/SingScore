# Stage 3: a hosted "bring your own audio" app where audio never reaches the server

## Why

If a hosted server receives, processes or stores users' songs, the host is the one making and
holding copies, and needs DMCA §512 safe-harbor machinery (registered agent, takedown flow).
If the whole pipeline runs in the user's browser, the server only serves static code and models.
That is the same legal shape as the local app (and as the existing GitHub Pages demo), but with
zero install. Lyrics display to a user's own file on their own device stays in the "private use"
posture; a hosted lyrics catalog does not.

## Component-by-component feasibility

Current pipeline (Python, `audio_pipeline/`) against what a browser build needs.

| Step | Now | Browser option | Status |
|---|---|---|---|
| Vocal separation | Demucs / BS-RoFormer (PyTorch) | `onnxruntime-web` with an ONNX htdemucs export | Community exports exist; sizes seen ~57-166 MB per model, WebGPU needs workarounds on some exports, ~3-5 min/song on CPU/WASM per one write-up. Verify the weights' license first (open question) |
| Melody | basic-pitch + `librosa.pyin` refinement | `@spotify/basic-pitch` (TS) for notes; pyin has no JS port, needs a port or a different refiner | basic-pitch-ts expects 22,050 Hz mono; last released about a year ago |
| Lyrics lookup | lrclib.net over HTTP | `fetch` from the browser | Not checked: lrclib's CORS policy and terms for browser use |
| Lyrics fallback | faster-whisper | A WASM/WebGPU Whisper build | Not researched this session |
| Word alignment | MMS wav2vec2 CTC (300M, **CC-BY-NC**) | Large ONNX model and a non-commercial license | Likely the hardest piece. Consider dropping it for a hosted build and using lrclib's line timing |
| Key change | Rubber Band CLI (GPL) | SoundTouch (LGPL) in an AudioWorklet | Straightforward; quality differs from Rubber Band R3 |
| Recording mixdown | ffmpeg-based mastering | Web Audio / ffmpeg.wasm | Not researched |

## Suggested order

1. **Spike (1-2 days):** drop a 30 s clip into a page, run Demucs ONNX, export the vocal stem.
   Measure download size, peak memory and time on a mid laptop. This decides if the idea is viable.
2. **Melody:** basic-pitch-ts on the stem, compare notes against `notes.json` from the Python
   pipeline on the three demo songs.
3. **Lyrics:** lrclib from the browser; no fallback in v1 (show the note highway without lyrics).
4. **Wire into the existing UI** behind the same `songs` shape (`notes.json`, `lyrics.json`,
   instrumental audio held in memory / IndexedDB, never uploaded).
5. **Key change** with SoundTouch.
6. Hosting: static files only (Pages/Netlify/Vercel). Models served from a CDN or Hugging Face.

## Before it goes public

- Re-check every model license in `THIRD_PARTY_LICENSES.md` for the exact weights shipped.
- Keep the wording honest in the UI: "your file is processed in your browser and never uploaded."
  Make sure that stays true (no analytics that capture audio, no error reporting with audio).
- A music/IP lawyer should review the final architecture, specifically the lyrics display.

## What this does not do

It does not make any particular song licensed. It removes the host from the chain of copying.
Whether a user's own use is permitted is between them and the rights holders.
