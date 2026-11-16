# Third-party licenses and credits

SingScore's own code is MIT (see `LICENSE`). This file lists what it depends on and the
audio shipped in the public demo.

## Demo songs (`frontend/public/demo-cache/`)

Music by Josh Woodward, licensed under
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). Source:
<https://www.joshwoodward.com/faq> ("all of my original music is licensed as Creative Commons 4.0
Attribution"; remixes and commercial use allowed with attribution). Checked 2026-11-04.

- Music - "Border Blaster" by Josh Woodward. Free download: https://www.joshwoodward.com/
- Music - "Private Hurricane" by Josh Woodward. Free download: https://www.joshwoodward.com/
- Music - "Stars Collide" by Josh Woodward. Free download: https://www.joshwoodward.com/

**Changes made:** the vocals were removed (source separation), and a melody chart and word-timed
lyrics were generated automatically. Per his FAQ, do not list these adapted versions on streaming
or sales services, and do not submit them to Content ID matching.

The FAQ does not name these three songs individually, so confirm the license on each song's page
at the source (Free Music Archive / joshwoodward.com) before a release.

## Models and libraries

"Checked" means the license text was confirmed this session; "believed" means it is from memory
and still needs a look before a release.

| Component | License | Status | Note |
|---|---|---|---|
| Demucs (code) | MIT | checked | The `htdemucs` weights' terms are unclear (community question, no answer): see <https://huggingface.co/adefossez/HTDemucs/discussions/1> |
| Whisper | MIT | checked | `faster-whisper` itself: believed MIT |
| Rubber Band | GPL (commercial license sold separately) | checked | Called as an external CLI the user installs; not bundled. Do not ship the binary without complying with the GPL |
| MMS forced-aligner weights (`MahmoudAshraf/mms-300m-1130-forced-aligner`) | CC-BY-NC 4.0 | per `requirements.txt` | Non-commercial only. Replace before any paid use |
| basic-pitch | Apache-2.0 | believed | |
| yt-dlp | Unlicense | believed | Only used when `SINGSCORE_ENABLE_LINK_DOWNLOAD=1` |
| audio-separator / BS-RoFormer weights | MIT / varies | believed | Check the weights' license separately |
| lrclib.net | community database | not checked | Lyrics are fetched from the user's own machine, not redistributed here |
