# SingScore

Turn a song file you own into a Rock Band-style karaoke game, for songs that don't have one.

*Try the [public demo](https://owenchlee.github.io/SingScore/) (Creative Commons songs only), or clone it and run it locally (below) with your own audio files.*

<img src="https://img.shields.io/badge/React-19-149eca?logo=react&logoColor=white" alt="React 19"> <img src="https://img.shields.io/badge/TypeScript-3178c6?logo=typescript&logoColor=white" alt="TypeScript"> <img src="https://img.shields.io/badge/Python-3.11-3776ab?logo=python&logoColor=white" alt="Python 3.11"> <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI"> <img src="https://img.shields.io/badge/PyTorch-ee4c2c?logo=pytorch&logoColor=white" alt="PyTorch">

## What it does

Games like Rock Band and Yousician only cover licensed setlists. SingScore builds that
experience for songs you supply: give it an audio file, and it separates the vocals, figures out
the melody and lyrics on its own, then turns it into a playable game: a scrolling note highway,
synced lyrics, and live pitch scoring against your own microphone as you sing.

No manual charting, no pre-made track packs. The song file itself is the only input.

## Legal

SingScore is a tool, not a song library. It ships no copyrighted music.

- **Your audio stays on your machine.** Processing runs locally. The app does not upload, host or
  redistribute your files, and cached results stay on your device.
- **Use audio you own or have permission to use.** You are responsible for what you process. This
  project is not affiliated with any artist, label or streaming service.
- **Loading from a link is off by default.** Downloading from a streaming site can breach that
  site's terms of service. If you accept that for your own use, start the server with
  `SINGSCORE_ENABLE_LINK_DOWNLOAD=1` (see below).
- **The public demo** uses only Creative Commons songs, credited in the app and in
  [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).
- **Takedown requests:** if you hold rights in something in this repository, open an issue at
  [github.com/owenchlee/SingScore/issues](https://github.com/owenchlee/SingScore/issues) and it will
  be removed promptly.

Code is [MIT licensed](LICENSE). Third-party models and libraries keep their own licenses.

## How it works

1. **Separate** vocals from the instrumental with [Demucs](https://github.com/facebookresearch/demucs) (source-separation ML model).
2. **Transcribe the melody** from the isolated vocal with [basic-pitch](https://github.com/spotify/basic-pitch), refined against [`librosa.pyin`](https://librosa.org/) for note-level pitch accuracy.
3. **Resolve lyrics** via a synced-lyrics lookup ([lrclib.net](https://lrclib.net), a request from your own machine), falling back to local speech-to-text with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) when no match exists.
4. **Play**: the frontend renders the note highway and lyrics in sync with the instrumental, listens to the mic in real time, and scores pitch accuracy (octave-tolerant, so singing the right note in the wrong register still counts).

Everything after step 1 is cached per song, so replaying is instant and processing never repeats.

## Stack

| Layer | Tech |
|---|---|
| Frontend | React 19, TypeScript, Vite, Web Audio API for live pitch detection |
| Backend | Python, FastAPI job server, background pipeline with progress streaming |
| ML/Audio | PyTorch, Demucs (source separation), basic-pitch + librosa (melody), faster-whisper (transcription) |
| Testing | pytest (backend), Vitest (frontend) |

## Running it locally

**Requires:** [Python 3.11](https://www.python.org/downloads/), [Node.js](https://nodejs.org),
and `ffmpeg` on your `PATH` (Windows: `winget install ffmpeg`; macOS: `brew install ffmpeg`).

You'll run two programs side by side, each in its **own terminal window that you leave open**
the whole time you're using the app: the **backend** (does the audio processing) and the
**frontend** (the webpage you actually use). Closing a window stops that half.

### 1. Clone the repo

```bash
git clone https://github.com/owenchlee/SingScore.git
cd SingScore
```

### 2. Start the backend

Still in that terminal, run:

**Windows:**
```bat
py -3.11 -m venv venv
venv\Scripts\python.exe -m pip install torch torchaudio
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe scripts\server.py
```

**macOS / Linux:**
```bash
python3.11 -m venv venv
venv/bin/python -m pip install torch torchaudio
venv/bin/python -m pip install -r requirements.txt
venv/bin/python scripts/server.py
```

Wait until it prints `Uvicorn running on http://127.0.0.1:8000`. **Leave this window open** —
that line means the backend is up and running in it.

### 3. Start the frontend

Open a **second, new** terminal window (don't reuse or close the first one), `cd` into the
`SingScore` folder again, then run:

```bash
cd frontend
npm install
npm run dev
```

### 4. Open the app

This second terminal will print a line like:

```
  ➜  Local:   http://localhost:5173/
```

Click that link, or copy the exact URL it printed into your browser. **Use the URL from your own
terminal**, not a bookmarked or guessed one — if something else on your machine is already using
port 5173, Vite automatically switches to the next free port (5174, 5175, ...) and prints
whichever one it actually picked.

Choose an audio file and it processes end-to-end (~1.5-7 min depending on hardware) then drops
you into the game. An NVIDIA GPU is auto-detected and used if present; otherwise everything falls
back to CPU. Already-processed songs replay instantly from a local cache.

To also show a "paste a link" box, start the backend with `SINGSCORE_ENABLE_LINK_DOWNLOAD=1`
(PowerShell: `$env:SINGSCORE_ENABLE_LINK_DOWNLOAD = "1"` before running `scripts\server.py`).
Only do this for content you're allowed to download.

### If it's not working

- **Nothing seemed to happen after pasting a command** — scroll up in that terminal; the real
  error is usually a few lines above where the prompt returned. Most common: the command isn't
  found (Python/Node isn't installed, or wasn't added to `PATH` during install).
- **`localhost` opens some other website** — that's a stale/bookmarked URL. Go back to the
  frontend terminal (step 3) and use the exact URL it printed (step 4).
- **Backend terminal errors out mentioning port 8000** — something else on your machine is
  already using that port. Close that other program, then re-run
  `venv\Scripts\python.exe scripts\server.py` (or the `venv/bin/python` equivalent).
- Both terminal windows need to stay open the whole time you're playing.

See [`NOTES.md`](NOTES.md) for the full phase-by-phase design history and the reasoning behind
specific tuning decisions.

## Optional: key change

Sync your vocal range once (from the app's "Voice range" screen, by singing your lowest and
highest comfortable note) and songs whose sung range doesn't fit yours are automatically
transposed -- audio and note targets together, tempo unchanged -- before you play. This needs the
free, open-source [Rubber Band Library](https://breakfastquay.com/rubberband/) command-line tool
on your `PATH` (not installed by `pip install -r requirements.txt`, same as `ffmpeg` above):

- **Windows**: download the "Windows executable" zip from
  [breakfastquay.com/rubberband](https://breakfastquay.com/rubberband/), extract it, and put
  `rubberband.exe` somewhere on your `PATH`.
- **macOS**: `brew install rubberband`
- **Linux**: `apt install rubberband-cli` (or your distro's equivalent)

Run `venv/Scripts/python.exe scripts/check_env.py` to confirm it's found. Without it, everything
else in the app works exactly as before -- key change is the only feature that needs it.

## Testing

```bash
venv/Scripts/python.exe -m pytest -v   # backend
cd frontend && npm run test             # frontend
```
