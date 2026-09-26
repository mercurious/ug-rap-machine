# Underground Rap Machine

A single-file browser instrument for underground rap. It generates the beat and samples, then runs live auto-tune on your microphone so you can perform over it. No samples are downloaded — every sound is synthesized in the browser with the Web Audio API.

## Run it

The mic only works on a secure page, so serve the folder from localhost rather than opening the file directly:

```bash
python3 -m http.server 8766 --bind 127.0.0.1
```

Then open <http://localhost:8766/underground-rap-machine.html> in Chrome, Edge or Firefox. Put on headphones before enabling the mic — through speakers the tuner will feed back.

## Sound templates

| | GLITTER | JERK |
|---|---|---|
| Lane | pluggnb / rage — Nettspend | NY jerk / plugg — xaviersobased |
| Tempo | 142–162 BPM, halftime snare on 3 | 150–180 BPM, staggered off-grid snares |
| Drums | triplet and ×4 hat rolls, rimshots | fidgety kicks, snaps, open-hat bounce |
| Harmony | major / lydian / minor / dorian, maj7 and 9th chords | minor / phrygian / harmonic minor, often one-chord loops |
| Sounds | FM bells, glassy keys, glide 808 | plugg square lead, detuned pad wash, distorted 808 |
| Samples | pitched vocal chops, light tape | mangled chops, crushed and wobbling choir loop |
| Mix | light sidechain, bright reverb | heavy sidechain pump, more tape and dirt |
| Vocal preset | hard tune, +1.5 st formant, wide double | hard tune, dirtier, tighter space |

**Generate** rolls a new beat in the selected template: tempo, key, scale, 4-bar chord progression and every row of the pattern.

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

**Pads.** Eight built-in sounds (riser, reverse crash, boom, tape stop, laser, sparkle, vox hit, 808 dive) on keys 1–8. Drop an audio file on a pad to replace it, or press ● to record 2 seconds of your tuned vocal as an ad-lib.

**Master and takes.** Volume, tape/lo-fi, sidechain pump and FX return. **Record take** captures the full mix — beat, pads and vocal — and each take downloads in the browser's recording format (WebM, Ogg or M4A) or as WAV.

### Keyboard

| Key | Action |
|---|---|
| Space | Play / stop |
| G | Generate a new beat |
| 1–8 | Trigger pads |
| R | Start / stop recording |
| M | Mic on / off |

## How it works

**Auto-tune** runs in an AudioWorklet (with a ScriptProcessor fallback):

- **Pitch detection:** YIN on a 2× decimated signal, updated every ~2.7 ms and anchored on the newest samples to keep lag low. A median check rejects octave errors.
- **Correction:** the detected pitch snaps to the nearest note in the locked scale, with hysteresis so notes don't flicker. Retune speed is a one-pole glide toward the target.
- **Pitch shifting:** TD-PSOLA. Pitch-synchronous grains are re-spaced at the target period, and pitch marks are only placed where a detection exists so corrections line up in time. Formant shift resamples each grain.
- **Latency:** about 36 ms at the Normal range (48 kHz), plus your system's audio output buffer. If monitoring feels late, the output buffer (PipeWire/PulseAudio, CoreAudio, WASAPI) is usually the bigger share.

**Beat engine** is a look-ahead scheduler (Web Worker timer, 120 ms horizon) driving synthesized voices: sine 808s with drive and glide, noise/tone drums, FM bells, detuned saw pads and a filtered square lead. Vocal chops are formant-synthesized vowels rendered offline and played as samples; the flip loop is a rendered choir that is then bit-crushed, sample-rate reduced, wobbled and given vinyl crackle.

Everything lives in `underground-rap-machine.html` — no build step or dependencies. Fonts load from Google Fonts and fall back to system fonts offline.
