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
| Tempo | 112–126 BPM, halftime snare on 3 | 116–128 BPM, staggered off-grid snares | 118–130 BPM, straight, stumbling double kicks | 114–126 BPM, bouncy jerk grid with swing |
| Drums | triplet and ×4 hat rolls, rimshots | fidgety kicks, snaps, open-hat bounce | dense hats, big clap-snare, ghosts dragged into the bar line | crisp snare, triplet rolls, snaps |
| Harmony | major / lydian / minor / dorian, maj7 and 9th chords | minor / phrygian / harmonic minor, often one-chord loops | phrygian / minor / harmonic minor, one or two chords with a ♭II lean | major / lydian pop loops, 9ths most of the time |
| Sounds | FM bells, glassy keys, glide 808 | plugg square lead, detuned pad wash, distorted 808 | rage stab (four saws screeching down into the note), sub-octave drone, 808 into the clipper | breathy flute lead, bright glass keys, clean 808 |
| Samples | pitched vocal chops, light tape | mangled chops, crushed and wobbling choir loop | chops pitched down and reversed, low choir loop crushed to 6 bits | chipmunk chops an octave up, high clean choir loop |
| Mix | light sidechain, bright reverb | heavy sidechain pump, more tape and dirt | hardest pump, most tape | least tape, most reverb and delay |
| Vocal preset | hard tune, +1.5 st formant, wide double | hard tune, dirtier, tighter space | hard tune, heavy dirt, formant down | hard tune, +3 st pitch and formant, widest double |

**Generate** rolls a new beat in the selected template: key, scale, 4-bar chord progression and every row of the pattern, at the tempo you have set. **120 down** and **160 up** switch between the downtempo and uptempo baselines in one tap, and whichever the BPM is nearer to stays lit. Switching lanes lands on the lit baseline (the tempo ranges above are where each lane sits in its own genre), and Gemma writes its songs for it (see MC). The BPM box and **−**/**+** go from 60 to 200 for anything in between. **N** cycles the lanes.

## Controls

**Pattern.** Ten rows (kick, 808, snare, hats, open hat, perc, keys, lead, chop, flip) × 16 steps, over a 4-bar chord progression.

- Click a step to toggle it. Hats cycle through rolls (×2, ×3, ×4); 808 steps cycle on → slide.
- Shift-click or right-click changes the 808 pitch, lead note, chop vowel or flip slice.
- ⟳ re-rolls a single row; clicking a row name mutes it.
- Click a chord to move it up a scale degree (shift-click goes back).
- **Fills** adds hat rolls, a snare pickup and an 808 octave slide in bar 4. They are on by default; the button is parked on the Flip 2 to make room for the tempo switch.

**Scenes.** Intro, Verse, Hook and Break mute groups of rows for live arranging. Hold **Hold: filter** for a low-pass sweep (on the Flip 2 the button shows **L2**, the trigger that holds it).

**Flip sample.** The FLIP row chops a generated choir loop in time with the chords. Loading your own audio is parked for now (it crashed the handheld build), so the **Load audio…** button is hidden.

**Vocal booth.**

| Control | What it does |
|---|---|
| Mic | Which input the booth listens to. **Auto** takes a USB mic (Shure, Rode, Yeti, anything with "USB" in its name) when one is plugged in, otherwise the system default; picking one remembers it |
| Lock to | Beat scale, pentatonic, chromatic, or tuner off |
| Voice | Lowest pitch to track — Deep 65 Hz, Normal 80 Hz, High 120 Hz (lower = more latency) |
| Retune speed | 0 ms is the hard, robotic snap; higher lets natural vibrato through |
| Amount | How much of the correction is applied |
| Pitch | Transpose ±12 semitones, formants preserved |
| Formant | Shift vocal character ±6 semitones without changing pitch |
| Double / Dirt / Delay / Reverb | Stereo doubler, distortion, dotted-8th ping-pong delay, reverb |

**USB mics.** Plug the mic in before or after the page opens. In auto, a USB mic that arrives while the mic is on takes over from the built-in one. Unplugging the mic turns it off instead of falling back to the built-in mic, which would feed back through the speakers; plug the same mic back in and it comes back on. If the mic sends pure silence for a few seconds, the booth asks whether it is muted, on the mic or in the system mixer (PipeWire can keep a USB mic muted between plug-ins). A mic with a headphone jack, like the MV7, often becomes the system's default output too, so the beat follows it to that jack.

**USB headphones.** On the Flip 2, plugging in USB headphones (Apple's USB-C EarPods, a USB-C dongle, a mic with a headphone jack) moves the sound to them: Firefox there can't pick an output itself, so the bridge makes them PipeWire's default output while they are plugged in, and puts back the output it replaced when they are unplugged or the app exits. The booth says where the beat plays. Unplugging them while the mic is on turns Monitor off, so the mic doesn't feed back through the speakers, and plugging them back in turns it on again. The EarPods' inline mic counts as a USB mic, so auto picks it. Elsewhere the operating system already moves the sound to headphones you plug in. If the Flip 2 doesn't see a USB device at all after it has been charging, plug a charger in and out once (its Type-C controller can miss the power going away).

No mic? **Tune a vocal file…** runs an audio file through the same chain, starting on the next bar.

**Pads.** Eight built-in sounds (riser, reverse crash, boom, tape stop, laser, sparkle, vox hit, 808 dive) on keys 1–8. Tape stop winds the song down and stops it; when Gemma plays it, the beat drops back in on the next bar instead. Drop an audio file on a pad to replace it, or press ● to record 2 seconds of your tuned vocal as an ad-lib.

**Master and takes.** Volume, tape/lo-fi, sidechain pump and FX return. The record button (the red dot in the transport row, or **R**) captures the full mix — beat, pads and vocal — and each take downloads in the browser's recording format (WebM, Ogg or M4A) or as WAV.

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
- sections in order, each a scene, 4 or 8 bars, **sung or rapped**, pad hits on given bars, and the lines, every line with a **melody** as scale degrees.

**Pocket TTS** then speaks each line, the page trims it, lays the sections on the bar grid, fires the scenes and pads at their bars, and plays every line into the vocal chain. While a line plays, the auto-tune is forced to one note at a time from its melody, so spoken TTS comes out sung in the song's key. Your mic can stay on; it shares the booth. The tempo is yours: the BPM at the moment you press **Let Gemma play** (or move to by hand while it plays) is the session's cue, and every plan stays within about 5% of it whatever lane Gemma picks, so a session started at 90 stays slow. Gemma is also told which baseline that is, and writes for it: short, punchy lines uptempo, longer and more laid-back ones downtempo. Tap the other baseline while it plays and the song already written for the old one is dropped and the next one is asked for at the new tempo.

**Sung sections.** A rapped line is the spoken line bent onto its melody by the auto-tune, as above. A sung line goes through the singer ported from autojam first. It finds the syllables in Pocket TTS's audio (voiced stretches from YIN, split where the level dips). It puts each vowel onset on a quarter, an eighth or a sixteenth, whatever fits two bars, and holds the last syllable. Only each vowel's loud middle is stretched to its note, so the consonants keep their natural speed. The vowels are then resynthesised by TD-PSOLA at the melody's pitch, with a 60 ms glide into each note and vibrato on the long ones; the grains are the voice's own, so it still sounds like the chosen voice. The line starts early by its first consonant, so the first vowel lands on the downbeat. It still goes through the booth with the tuner forced to each syllable's note, so the hard tune snaps the glides and vibrato into the stepped auto-tune sound. Gemma writes one degree per syllable for a sung line (up to 12). The singing runs in a Web Worker while the beat plays, in about 0.1 s a line. The **sing** menu decides which sections are sung: Gemma picks (at least one sung, usually the hook, and one rapped), the hooks, all of it, or rap only. If the tempo has moved by the time a sung line plays, it is played that much faster or slower and the forced tuner puts it back on the note.

**Syncopation** sets how Gemma sits on the beat. At 0 every line starts on the one and its melody is spread evenly over the line, the way a machine would. Turned up, lines come in on a pickup (an 8th, a 16th or a dotted 8th before the bar) or lazily after it, some lie a touch behind the beat, and the note changes are pulled onto the 16th grid with a taste for the off-beats, swung like the hats. The slider is read when each plan is laid out, so it takes effect on the next song (or the next loop of this one), and Gemma is told the setting so the lines are written to fit: even lines when it is low, pickups and mixed lengths when it is high. Default 45. **Keep going** asks for the next song while this one plays and switches to it when the plan ends; until it arrives, the plan loops. Themes are a hint, "surprise me" leaves it to the model. Takes record the whole thing like any other performance.

Timing on the Flip 2 with E4B: about 90–150 s to write a plan of ten lines, then a few seconds per line of speech. The model and the voice run on three big cores at low priority (the model as a batch task) and Firefox's audio threads get a real-time slice on the launcher's watch, so a plan being written under a playing song does not make the beat flutter. The status line shows what it is doing. `URM_MODEL=e2b` picks the small Gemma, about twice as fast.

**On the Flip 2** nothing is typed: choose **Rap Machine + Gemma** under Ports. Its launcher starts Gemma, Pocket TTS and the bridge, opens the page, and stops them all when you leave with Guide (or L1+Select+Start). It uses the llamatalk kit and models that [Retro Voice Chat](https://github.com/mercurious/retro-voice-chat) installs; if they are missing, the MC panel says so and the rest of the machine works as usual. While the model loads the panel shows "Gemma loading"; after that, **Let Gemma play**.

**Anywhere else** (a laptop with its own llama-server and `tts-server`), start the bridge yourself and open the page through it:

```bash
python3 flip2/server.py --dir . --llm http://127.0.0.1:8096 --tts http://127.0.0.1:8097
```

then <http://127.0.0.1:8766/underground-rap-machine.html?mc>. Point `--llm` at any llama-server with a Gemma (or another instruction model) and `--tts` at a `tts-server` from the same kit; the page talks to the bridge only. Any other OpenAI-compatible server works too, Ollama or a shared GPU box: give its base URL (with or without `/v1`) and name the model with `--llm-model`, e.g. `--llm http://HOST:11434/v1 --llm-model gemma4:e4b`. Thinking is turned off either way.

## Retroid Pocket Flip 2

The same file runs as a handheld instrument on a Flip 2 with [ROCKNIX](https://rocknix.org) and the house Firefox build. `flip2/` holds the device side:

| File | Role |
|---|---|
| `server.py` | Serves the page on `http://127.0.0.1:8766` (a secure context, so the mic works) and writes the stick LED rings from `POST /led`. Also `--test` to see the ring order, `--grant-mic` to allow the mic for that origin in the Firefox profile, and `--key`, `--click`, `--set`, `--status` to drive a page opened with `?remote` from ssh. |
| `launch.sh` | Starts the server, opens the page in kiosk mode through `/storage/apps/firefox-rocknix/launch.sh`, then loads the controller profile. Cleans up and restores the rings on exit. |
| `rap-machine.yaml` | InputPlumber profile: which button sends which key. |
| `Rap Machine.sh`, `Rap Machine + Gemma.sh` | The ROCKNIX port entries (under Ports in EmulationStation); the second one also starts Gemma and Pocket TTS for the MC mode. |
| `install.sh [host]` | Copies all of it over ssh (default host `flip2-12g`), grants the mic, adds the ports to `gamelist.xml`. EmulationStation shows them after a game list refresh (Start → Game Settings → Update Gamelists) or a restart. |

Open with `?flip` and the page zooms itself to a 960-px-wide layout for the 5.5" 1920×1080 panel and shows one view at a time: **Pattern**, **Booth**, **Pads**, **Mix**, **MC** (`&view=booth` opens on a given view). The touchscreen works everywhere; the controller does the performing:

| Control | Action |
|---|---|
| A B X Y | Pads 1–4 |
| D-pad ↑ → ↓ ← | Pads 5–8 |
| Start | Play / stop |
| Select | Generate a new beat |
| L1 / R1 | Previous / next view |
| Left stick | Scene: up Intro, right Verse, down Hook, left Break (the scene buttons carry the arrow) |
| L3 (press the left stick) | Mic on / off |
| R3 (press the right stick) | Record a take |
| L2 (hold) | Low-pass filter sweep |
| Right stick + R2 | Pointer and tap |
| Guide (Home) | Leave |

**Gauges.** Between the view buttons and the status chips sit a battery gauge (fill, percentage, a bolt while charging, the watts going in or out) stacked on the sync chip, and a Gemma speedo two lines tall that gives way if the row runs short: under its label, pulsing dots while the model reads the beat or Pocket TTS sings, a bar and tokens per second while it writes, the last speed when idle. `&sysdemo=writing|prompt|tts|low` renders sample states, with the widest sync chip, to check the fit. Battery and speedo come from `GET /sys` on the bridge every two seconds, along with the default audio output (for the headphone notices).

**MC lyrics.** The lyric sheet fills the panel and scrolls with Gemma: the line being sung stays a third of the way down.

**LED rings.** The ring around the left stick is the beat clock: one segment per beat in the lane's colour, the fill bar in the second colour, a slow breath when stopped. The ring around the right stick is a VU of your tuned voice, a red heartbeat while a take records, and a white flash on every pad hit. While Gemma performs, the right ring follows its voice instead. Each line's loudness and syllable onsets are measured when it is synthesized, and the ring reads them as that part of the line is heard, output and tuner latency included. A rapped line chases: every syllable steps a bright head one segment round the ring, with a white tick on the attack and a tail in the lane's second colour. A sung line glows: the ring fills as high as the note sits in the melody, in a colour for each pitch class, and shimmers with the vibrato. Frames go to the server at up to 30 per second only when something changed; the kernel's `multi_intensity` order is read from sysfs, not assumed.

Plug in headphones: through the speakers the internal mic feeds back into the tuner. Takes download into Firefox's download folder on the device.

**Wi-Fi sync.** The bridge speaks HI5S, the sync of [HI5](https://github.com/mercurious/hi5), [Jaffedrone](https://github.com/mercurious/jaffedrone) and [fliptribe](https://github.com/mercurious/fliptribe), so the machines lock to each other on the same network with no setup. Every unit broadcasts 32 bytes on UDP 5150 ten times a second: tempo, play/stop and its 16th-step position. A unit set to LEAD leads, otherwise the lowest id among the AUTO units does; FOLLOW never leads. Followers take the leader's tempo, start and stop with it (joining at its position), and pull their phase in through an 8-sample median: more than half a step off, they jump; less, they trim their clock by up to 3%. The Rap Machine follows with two extras. The bridge reads the leader through the Wi-Fi scatter: power save holds broadcasts for the next beacon, so it keeps 8 s of packets and trusts the quickest. The page adds a slow integral to the trim, so a unit whose clock runs a little fast or slow settles on zero offset rather than a standing one. Measured on a Flip 2 over home Wi-Fi: locked within about ±1 ms in 10 s following a leader, and HI5 following the Flip 2 at +2 ms. The **sync** chip in the views row shows the role and the offset (`follow +4ms`, `lead ·2`); tap it to cycle off, auto, lead and follow. It starts on `auto` (`URM_SYNC` or `--sync`; `URM_SYNC_PORT=0` turns it off). This is separate from the jam link on UDP 47800, which also carries key, mode and chords for autojam, and both run at once.

## How it works

**Auto-tune** runs in an AudioWorklet (with a ScriptProcessor fallback):

- **Pitch detection:** YIN on a 2× decimated signal, updated every ~2.7 ms and anchored on the newest samples to keep lag low. A median check rejects octave errors.
- **Correction:** the detected pitch snaps to the nearest note in the locked scale, with hysteresis so notes don't flicker. Retune speed is a one-pole glide toward the target.
- **Pitch shifting:** TD-PSOLA. Pitch-synchronous grains are re-spaced at the target period, and pitch marks are only placed where a detection exists so corrections line up in time. Formant shift resamples each grain.
- **Latency:** about 36 ms at the Normal range (48 kHz), plus your system's audio output buffer. If monitoring feels late, the output buffer (PipeWire/PulseAudio, CoreAudio, WASAPI) is usually the bigger share.

**Beat engine** is a look-ahead scheduler (Web Worker timer, 120 ms horizon) driving synthesized voices: sine 808s with drive and glide, noise/tone drums, FM bells, detuned saw pads and a filtered square lead. Vocal chops are formant-synthesized vowels rendered offline and played as samples; the flip loop is a rendered choir that is then bit-crushed, sample-rate reduced, wobbled and given vinyl crackle.

Everything lives in `underground-rap-machine.html` — no build step or dependencies. Fonts load from Google Fonts and fall back to system fonts offline. The Flip 2 bridge in `flip2/server.py` is standard-library Python.

## License

MIT. See [LICENSE](LICENSE).
