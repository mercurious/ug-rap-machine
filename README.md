# Underground Rap Machine

A single-file browser instrument for underground rap. It generates the beat and samples, then runs live auto-tune on your microphone so you can perform over it. No samples are downloaded — every sound is synthesized in the browser with the Web Audio API.

## Run it

The mic only works on a secure page, so serve the folder from localhost rather than opening the file directly:

```bash
python3 -m http.server 8766 --bind 127.0.0.1
```

Then open <http://localhost:8766/underground-rap-machine.html> in Chrome, Edge or Firefox. Put on headphones before enabling the mic — through speakers the tuner will feed back.

## Sound templates

Four artist lanes. Each one is a template in `STYLES`: tempo and swing ranges, scales and chord loops, a drum kit, the lead and pad voices, how the chops and the flip loop are pitched and degraded, a mix, and a vocal preset.

| | GLITTER | JERK | CHE | PRTTIFUN |
|---|---|---|---|---|
| Lane | pluggnb / rage — Nettspend | NY jerk / plugg — xaviersobased | dark jerk / rage — Che | bubblegum plugg, sped-up — Prttifun |
| Tempo | 142–162 BPM, halftime snare on 3 | 150–180 BPM, staggered off-grid snares | 158–176 BPM, straight, stumbling double kicks | 150–170 BPM, bouncy jerk grid with swing |
| Drums | triplet and ×4 hat rolls, rimshots | fidgety kicks, snaps, open-hat bounce | dense hats, big clap-snare, ghosts dragged into the bar line | crisp snare, triplet rolls, snaps |
| Harmony | major / lydian / minor / dorian, maj7 and 9th chords | minor / phrygian / harmonic minor, often one-chord loops | phrygian / minor / harmonic minor, one or two chords with a ♭II lean | major / lydian pop loops, 9ths most of the time |
| Sounds | FM bells, glassy keys, glide 808 | plugg square lead, detuned pad wash, distorted 808 | rage stab (four saws screeching down into the note), sub-octave drone, 808 into the clipper | breathy flute lead, bright glass keys, clean 808 |
| Samples | pitched vocal chops, light tape | mangled chops, crushed and wobbling choir loop | chops pitched down and reversed, low choir loop crushed to 6 bits | chipmunk chops an octave up, high clean choir loop |
| Mix | light sidechain, bright reverb | heavy sidechain pump, more tape and dirt | hardest pump, most tape | least tape, most reverb and delay |
| Vocal preset | hard tune, +1.5 st formant, wide double | hard tune, dirtier, tighter space | hard tune, heavy dirt, formant down | hard tune, +3 st pitch and formant, widest double |

**Generate** rolls a new beat in the selected template: tempo, key, scale, 4-bar chord progression and every row of the pattern. **N** cycles the lanes.

## Controls

**Pattern.** Ten rows (kick, 808, snare, hats, open hat, perc, keys, lead, chop, flip) × 16 steps, over a 4-bar chord progression.

- Click a step to toggle it. Hats cycle through rolls (×2, ×3, ×4); 808 steps cycle on → slide.
- Shift-click or right-click changes the 808 pitch, lead note, chop vowel or flip slice.
- ⟳ re-rolls a single row; clicking a row name mutes it.
- Click a chord to move it up a scale degree (shift-click goes back).
- **Fills** adds hat rolls, a snare pickup and an 808 octave slide in bar 4.

**Scenes.** Intro, Verse, Hook and Break mute groups of rows for live arranging. Hold **Hold: filter** for a low-pass sweep.

**Flip sample.** The FLIP row chops a generated choir loop in time with the chords. **Load audio…** swaps in your own file, stretched to the nearest 1, 2, 4 or 8 bars (its pitch shifts with the tempo, like a sped-up sample).

**Vocal booth.**

| Control | What it does |
|---|---|
| Lock to | Beat scale, pentatonic, chromatic, or tuner off |
| Voice | Lowest pitch to track — Deep 65 Hz, Normal 80 Hz, High 120 Hz (lower = more latency) |
| Retune speed | 0 ms is the hard, robotic snap; higher lets natural vibrato through |
| Amount | How much of the correction is applied |
| Pitch | Transpose ±12 semitones, formants preserved |
| Formant | Shift vocal character ±6 semitones without changing pitch |
| Double / Dirt / Delay / Reverb | Stereo doubler, distortion, dotted-8th ping-pong delay, reverb |

No mic? **Tune a vocal file…** runs an audio file through the same chain, starting on the next bar.

**Pads.** Eight built-in sounds (riser, reverse crash, boom, tape stop, laser, sparkle, vox hit, 808 dive) on keys 1–8. Tape stop winds the song down and stops it; when Gemma plays it, the beat drops back in on the next bar instead. Drop an audio file on a pad to replace it, or press ● to record 2 seconds of your tuned vocal as an ad-lib.

**Master and takes.** Volume, tape/lo-fi, sidechain pump and FX return. **Record take** captures the full mix — beat, pads and vocal — and each take downloads in the browser's recording format (WebM, Ogg or M4A) or as WAV.

### Keyboard

| Key | Action |
|---|---|
| Space | Play / stop |
| G | Generate a new beat |
| N | Next artist lane |
| 1–8 | Trigger pads |
| I V H B | Scenes: intro, verse, hook, break |
| F (hold) | Low-pass filter sweep |
| R | Start / stop recording |
| M | Mic on / off |
| [ ] | Previous / next view (Flip 2 layout only) |

## MC mode: Gemma plays the machine

The **MC** panel hands the instrument to a local language model. Through the bridge in `flip2/server.py`, a [llama.cpp](https://github.com/ggml-org/llama.cpp) server running **Gemma 4 E4B** gets the beat as it stands (lane, tempo, key, chords, how busy each row is, the theme you picked) and answers with one JSON performance, constrained by a schema so it always parses:

- the lane, tempo, key, mode and swing, and which rows to re-roll;
- a booth preset (pitch, formant, double, dirt, delay, reverb) and which Pocket TTS voice sings;
- sections in order, each a scene, 4 or 8 bars, pad hits on given bars, and the lines, every line with a **melody** as scale degrees.

**Pocket TTS** then speaks each line, the page trims it, lays the sections on the bar grid, fires the scenes and pads at their bars, and plays every line into the vocal chain. While a line plays, the auto-tune is forced to one note at a time from its melody, spread evenly over the line, so spoken TTS comes out sung in the song's key. Your mic can stay on; it shares the booth. **Keep going** asks for the next song while this one plays and switches to it when the plan ends; until it arrives, the plan loops. Themes are a hint, "surprise me" leaves it to the model. Takes record the whole thing like any other performance.

Timing on the Flip 2 with E4B: about 90–150 s to write a plan of ten lines, then a few seconds per line of speech. The status line shows what it is doing. `URM_MODEL=e2b` picks the small Gemma, about twice as fast.

**On the Flip 2** nothing is typed: choose **Rap Machine + Gemma** under Ports. Its launcher starts Gemma, Pocket TTS and the bridge, opens the page, and stops them all when you leave with Guide (or L1+Select+Start). It uses the llamatalk kit and models that [Retro Voice Chat](https://github.com/mercurious/retro-voice-chat) installs; if they are missing, the MC panel says so and the rest of the machine works as usual. While the model loads the panel shows "Gemma loading"; after that, **Let Gemma play**.

**Anywhere else** (a laptop with its own llama-server and `tts-server`), start the bridge yourself and open the page through it:

```bash
python3 flip2/server.py --dir . --llm http://127.0.0.1:8096 --tts http://127.0.0.1:8097
```

then <http://127.0.0.1:8766/underground-rap-machine.html?mc>. Point `--llm` at any llama-server with a Gemma (or another instruction model) and `--tts` at a `tts-server` from the same kit; the page talks to the bridge only.

## Retroid Pocket Flip 2

The same file runs as a handheld instrument on a Flip 2 with [ROCKNIX](https://rocknix.org) and the house Firefox build. `flip2/` holds the device side:

| File | Role |
|---|---|
| `server.py` | Serves the page on `http://127.0.0.1:8766` (a secure context, so the mic works) and writes the stick LED rings from `POST /led`. Also `--test` to see the ring order, `--grant-mic` to allow the mic for that origin in the Firefox profile, and `--key`, `--click`, `--set`, `--status` to drive a page opened with `?remote` from ssh. |
| `launch.sh` | Starts the server, opens the page in kiosk mode through `/storage/apps/firefox-rocknix/launch.sh`, then loads the controller profile. Cleans up and restores the rings on exit. |
| `rap-machine.yaml` | InputPlumber profile: which button sends which key. |
| `Rap Machine.sh`, `Rap Machine + Gemma.sh` | The ROCKNIX port entries (under Ports in EmulationStation); the second one also starts Gemma and Pocket TTS for the MC mode. |
| `install.sh [host]` | Copies all of it over ssh (default host `flip2-12g`), grants the mic, adds the ports to `gamelist.xml`. EmulationStation shows them after a game list refresh (Start → Game Settings → Update Gamelists) or a restart. |

Open with `?flip` and the page zooms itself to a 960-px-wide layout for the 5.5" 1920×1080 panel and shows one view at a time: **Pattern**, **Booth**, **Pads**, **Mix**, **MC**. The touchscreen works everywhere; the controller does the performing:

| Control | Action |
|---|---|
| A B X Y | Pads 1–4 |
| D-pad ↑ → ↓ ← | Pads 5–8 |
| Start | Play / stop |
| Select | Generate a new beat |
| L1 / R1 | Previous / next view |
| Left stick | Scene: up Intro, right Verse, down Hook, left Break |
| L3 (press the left stick) | Mic on / off |
| R3 (press the right stick) | Record a take |
| L2 (hold) | Low-pass filter sweep |
| Right stick + R2 | Pointer and tap |
| Guide (Home) | Leave |

**LED rings.** The ring around the left stick is the beat clock: one segment per beat in the lane's colour, the fill bar in the second colour, a slow breath when stopped. The ring around the right stick is a VU of your tuned voice, a red heartbeat while a take records, and a white flash on every pad hit. Frames go to the server at up to 30 per second only when something changed; the kernel's `multi_intensity` order is read from sysfs, not assumed.

Plug in headphones: through the speakers the internal mic feeds back into the tuner. Takes download into Firefox's download folder on the device.

## How it works

**Auto-tune** runs in an AudioWorklet (with a ScriptProcessor fallback):

- **Pitch detection:** YIN on a 2× decimated signal, updated every ~2.7 ms and anchored on the newest samples to keep lag low. A median check rejects octave errors.
- **Correction:** the detected pitch snaps to the nearest note in the locked scale, with hysteresis so notes don't flicker. Retune speed is a one-pole glide toward the target.
- **Pitch shifting:** TD-PSOLA. Pitch-synchronous grains are re-spaced at the target period, and pitch marks are only placed where a detection exists so corrections line up in time. Formant shift resamples each grain.
- **Latency:** about 36 ms at the Normal range (48 kHz), plus your system's audio output buffer. If monitoring feels late, the output buffer (PipeWire/PulseAudio, CoreAudio, WASAPI) is usually the bigger share.

**Beat engine** is a look-ahead scheduler (Web Worker timer, 120 ms horizon) driving synthesized voices: sine 808s with drive and glide, noise/tone drums, FM bells, detuned saw pads and a filtered square lead. Vocal chops are formant-synthesized vowels rendered offline and played as samples; the flip loop is a rendered choir that is then bit-crushed, sample-rate reduced, wobbled and given vinyl crackle.

Everything lives in `underground-rap-machine.html` — no build step or dependencies. Fonts load from Google Fonts and fall back to system fonts offline. The Flip 2 bridge in `flip2/server.py` is standard-library Python.
