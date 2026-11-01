import Foundation
import FoundationModels
import AVFAudio

// MARK: - The plan, in the shape the page reads (PLAN_SCHEMA in flip2/server.py)

@Generable(description: "A line of lyrics and the melody the auto-tune bends it onto")
nonisolated struct MCLine {
    @Guide(description: "The words: 4 to 9 words, one breath, original")
    var text: String
    @Guide(description: "Scale degrees: 0 the root, 2 the third, 4 the fifth, 7 the octave, negative below the root. A rapped line gets 2 to 8 spread over it; a sung line gets one per syllable, up to 12, a tune to hum",
           .count(2...12), .element(.range(-3...9)))
    var melody: [Int]
}

@Generable(description: "A one-shot pad fired on a bar of the section")
nonisolated struct MCPad {
    @Guide(description: "Bar of the section, 1 is its first", .range(1...8))
    var bar: Int
    @Guide(description: "1 riser, 2 reverse crash, 3 boom, 4 tape stop, 5 laser, 6 sparkle, 7 vox hit, 8 808 dive", .range(1...8))
    var pad: Int
}

@Generable(description: "A section of the arrangement")
nonisolated struct MCSection {
    @Guide(description: "The mute group: intro (keys and flip only, filtered), verse (no chops, no lead), hook (everything) or break (no drums)",
           .anyOf(["intro", "verse", "hook", "break"]))
    var scene: String
    @Guide(description: "4 or 8", .range(4...8))
    var bars: Int
    @Guide(description: "true to sing the section (held vowels on the beat), false to rap it")
    var sung: Bool
    @Guide(description: "Pads fired during the section, at most 3; tape stop at most once in the whole plan", .maximumCount(3))
    var pads: [MCPad]
    @Guide(description: "The lyrics in order; a hook or verse has 2 to 4 lines, an intro or break may have none", .maximumCount(4))
    var lines: [MCLine]
}

@Generable(description: "The auto-tune preset for the voice")
nonisolated struct MCVocal {
    @Guide(description: "Transpose in semitones", .range(-7...7)) var pitch: Int
    @Guide(description: "Formant shift in semitones", .range(-4...4)) var formant: Int
    @Guide(description: "Stereo doubler, 0 to 100", .range(0...100)) var double: Int
    @Guide(description: "Distortion, 0 to 100", .range(0...100)) var dirt: Int
    @Guide(description: "Ping-pong delay, 0 to 100", .range(0...100)) var delay: Int
    @Guide(description: "Reverb, 0 to 100", .range(0...100)) var verb: Int
}

@Generable(description: "One performance plan for the rap machine")
nonisolated struct MCPlan {
    @Guide(description: "A song title, 1 to 4 words")
    var title: String
    @Guide(description: "The sound template", .anyOf(["glitter", "jerk", "che", "prttifun"]))
    var lane: String
    @Guide(description: "Tempo in BPM, inside the zone the performer set", .range(60...200))
    var bpm: Int
    @Guide(description: "The key", .anyOf(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]))
    var key: String
    @Guide(description: "The scale", .anyOf(["major", "lydian", "minor", "dorian", "phrygian", "harmonic"]))
    var mode: String
    @Guide(description: "Swing, percent", .range(0...25))
    var swing: Int
    @Guide(description: "Rows of the 16-step pattern to re-roll, at most 4", .maximumCount(4),
           .element(.anyOf(["kick", "bass", "snare", "hat", "ohat", "perc", "keys", "lead", "chop", "flip"])))
    var reroll: [String]
    var vocal: MCVocal
    @Guide(description: "The name of the voice that sings, from the list given")
    var voice: String
    @Guide(description: "The arrangement in order: 2 to 5 sections, 8 to 12 lines in all", .count(2...5))
    var sections: [MCSection]
}

// MARK: - The MC on the phone

/// Apple Intelligence writes the plan and a system voice speaks the lines. Same contract as AIBridge in
/// flip2/server.py: a plan is a job the page polls (/ai/progress), fetched when done (/ai/plan?job=N); a line of
/// speech comes back as a WAV.
final class OnDeviceMC {
    private(set) var progress: [String: Any] = ["phase": "idle"]
    private var job = 0
    private var result: (job: Int, value: [String: Any])?
    private var running: Task<Void, Never>?
    private let speech = SpeechRenderer()
    private var speaking: Task<Data, Error>?       // lines are rendered one at a time

    struct Voice { let name: String; let id: String; let quality: AVSpeechSynthesisVoiceQuality }

    /// The English voices on the phone, one per name, the best quality of each, premium first. Listed once a
    /// minute at most: the page asks for health every few seconds and the voice database is slow to answer.
    private var voiceCache: (at: Date, list: [Voice])?
    var voices: [Voice] {
        if let c = voiceCache, Date().timeIntervalSince(c.at) < 60 { return c.list }
        let list = Self.listVoices()
        voiceCache = (Date(), list)
        return list
    }

    private static func listVoices() -> [Voice] {
        var best: [String: Voice] = [:]
        for v in AVSpeechSynthesisVoice.speechVoices() where v.language.hasPrefix("en") {
            let candidate = Voice(name: v.name, id: v.identifier, quality: v.quality)
            if let have = best[v.name], have.quality.rawValue >= v.quality.rawValue { continue }
            best[v.name] = candidate
        }
        return best.values.sorted { a, b in
            a.quality.rawValue != b.quality.rawValue ? a.quality.rawValue > b.quality.rawValue : a.name < b.name
        }
    }

    func health() -> [String: Any] {
        let names = voices.map(\.name)
        var out: [String: Any] = [
            "llm": false, "model": "on this phone", "llmUrl": "on-device", "llmName": "Apple Intelligence",
            "tts": !names.isEmpty, "ttsUrl": "on-device", "ttsName": "Speech", "voices": names, "voice": names.first ?? "",
            "native": true,
        ]
        switch SystemLanguageModel.default.availability {
        case .available:
            out["llm"] = true; out["llmStatus"] = "ok"
        case .unavailable(let reason):
            out["llmStatus"] = "off"
            out["llmHint"] = Self.hint(for: reason)
        }
        if names.isEmpty { out["ttsHint"] = "no English voice on this phone: add one under Settings → Accessibility → Spoken Content → Voices" }
        return out
    }

    private static func hint(for reason: SystemLanguageModel.Availability.UnavailableReason) -> String {
        switch reason {
        case .appleIntelligenceNotEnabled: "Apple Intelligence is off: turn it on in Settings, or point Bridge at a laptop running flip2/server.py"
        case .modelNotReady: "Apple Intelligence is still downloading its model; try again in a bit"
        case .deviceNotEligible: "this phone has no Apple Intelligence: point Bridge at a laptop running flip2/server.py"
        @unknown default: "Apple Intelligence is not available right now"
        }
    }

    // MARK: plan

    func startPlan(_ req: [String: Any]) -> [String: Any] {
        guard SystemLanguageModel.default.isAvailable else {
            if case .unavailable(let r) = SystemLanguageModel.default.availability { return ["error": Self.hint(for: r)] }
            return ["error": "Apple Intelligence is not available"]
        }
        if let phase = progress["phase"] as? String, phase == "prompt" || phase == "writing", running != nil {
            return ["job": job, "running": true]     // one at a time: hand back the job that is running
        }
        job += 1
        let thisJob = job, t0 = Date()
        progress = ["phase": "prompt", "tokens": 0, "job": thisJob]
        result = nil
        running = Task { await self.run(req, job: thisJob, t0: t0) }
        return ["job": thisJob]
    }

    func plan(job: Int) -> [String: Any] {
        if let result, result.job == job { return result.value }
        return ["error": job != self.job ? "no such plan" : "still writing"]
    }

    private func run(_ req: [String: Any], job: Int, t0: Date) async {
        do {
            let (plan, tokens) = try await write(req, job: job, t0: t0)
            let secs = Date().timeIntervalSince(t0)
            result = (job, ["plan": plan, "tokens": tokens, "secs": secs])
            progress = ["phase": "done", "tokens": tokens, "secs": secs, "job": job]
        } catch {
            let message = Self.describe(error)
            result = (job, ["error": message])
            progress = ["phase": "error", "error": message, "job": job]
        }
        running = nil
    }

    private static func describe(_ error: Error) -> String {
        if let e = error as? LanguageModelSession.GenerationError {
            switch e {
            case .guardrailViolation: return "Apple Intelligence would not write that one; try another theme"
            case .exceededContextWindowSize: return "the plan ran out of room; try again"
            case .unsupportedLanguageOrLocale: return "Apple Intelligence does not write in this language"
            default: break
            }
        }
        return error.localizedDescription
    }

    /// One guided generation, streamed so the page sees it being written. Returns the plan as the page's JSON and
    /// a rough token count.
    private func write(_ req: [String: Any], job: Int, t0: Date) async throws -> ([String: Any], Int) {
        let session = LanguageModelSession(instructions: Self.instructions)
        let prompt = Self.prompt(for: req)
        let options = GenerationOptions(temperature: 0.9, maximumResponseTokens: 1800)
        let stream = session.streamResponse(to: prompt, generating: MCPlan.self, options: options)
        var last: GeneratedContent?
        var tokens = 0
        for try await snapshot in stream {
            last = snapshot.rawContent
            tokens = max(tokens, snapshot.rawContent.debugDescription.count / 4)
            progress = ["phase": "writing", "tokens": tokens, "secs": Date().timeIntervalSince(t0), "job": job]
        }
        guard let last else { throw SpeechRenderer.Failure("Apple Intelligence wrote nothing") }
        let plan = try MCPlan(last)
        return (Self.json(plan), tokens)
    }

    private static func json(_ p: MCPlan) -> [String: Any] {
        [
            "title": p.title, "lane": p.lane, "bpm": p.bpm, "key": p.key, "mode": p.mode, "swing": p.swing,
            "reroll": p.reroll, "voice": p.voice,
            "vocal": ["pitch": p.vocal.pitch, "formant": p.vocal.formant, "double": p.vocal.double,
                      "dirt": p.vocal.dirt, "delay": p.vocal.delay, "verb": p.vocal.verb],
            "sections": p.sections.map { s -> [String: Any] in
                ["scene": s.scene, "bars": s.bars >= 6 ? 8 : 4, "sung": s.sung,
                 "pads": s.pads.map { ["bar": $0.bar, "pad": $0.pad] },
                 "lines": s.lines.map { ["text": $0.text, "melody": $0.melody] }]
            },
        ]
    }

    // The same brief as flip2/server.py gives Gemma, written for a smaller model and the system's content rules.
    private static let instructions = """
    You are the MC and producer at an Underground Rap Machine: an instrument that generates a beat and auto-tunes \
    a voice over it. You are given the beat as it stands and you answer with ONE performance plan.

    What you control
    - lane: the sound template. GLITTER: pluggnb / rage, halftime, major or lydian with maj7 and 9th chords, FM \
    bells, glassy keys, glide 808; pretty, floaty, melodic. JERK: NY jerk / plugg, minor or phrygian one-chord \
    loops, square plugg lead, detuned pad wash, distorted 808, mangled chops; fidgety, grimy. CHE: dark jerk / \
    rage, phrygian, one or two chords, 808 into the clipper, rage stabs, sub-octave drone, chops pitched down and \
    reversed; menacing. PRTTIFUN: bubblegum plugg, major / lydian pop loops, flute lead, chipmunk chops an octave \
    up, sped-up choir; sweet, bouncy, bright. Switching lane generates a fresh beat in that lane; keeping it keeps \
    the current beat.
    - bpm, key, mode, swing (percent): the groove. The tempo is the performer's call: the message gives a tempo \
    zone around the BPM they set; stay inside it. Pick the lane for the mood and keep the performer's tempo.
    - reroll: rows of the 16-step pattern to re-roll (kick bass snare hat ohat perc keys lead chop flip).
    - vocal: the auto-tune preset for the voice. pitch and formant in semitones; double, dirt, delay, verb 0-100.
    - voice: the name of the voice that sings, from the list given.
    - sections: the arrangement, played in order. scene is a mute group: intro (keys and flip only, filtered), \
    verse (no chops, no lead), hook (everything), break (no drums). bars is 4 or 8. pads are one-shots fired on a \
    bar of the section (bar 1 = its first bar): 1 riser, 2 reverse crash, 3 boom, 4 tape stop (the beat winds \
    down and drops back in on the next bar), 5 laser, 6 sparkle, 7 vox hit, 8 808 dive. Use tape stop at most \
    once, as a drop on the last bar before a hook or on the very last bar.
    - sung: true to SING the section, false to RAP it. A sung line is held out on the beat, one vowel per \
    syllable at the melody's pitch; a rapped line is spoken in rhythm and the auto-tune bends it onto the \
    melody. Sing a hook to make it catchy, rap the verses.
    - lines: the lyrics of the section, one after another from its first bar. Each line is 4 to 9 words, one \
    breath. Its melody is the notes the auto-tune forces, as scale degrees: 0 is the root, 2 the third, 4 the \
    fifth, 7 the octave, negative goes below the root. For a rapped line give 2 to 8 degrees, spread evenly over \
    it. For a sung line give ONE DEGREE PER SYLLABLE (up to 12), a tune someone could hum: mostly steps, a leap \
    to land the line, end on 0, 2 or 4. Hooks repeat a shape; verses move more.

    Write like the lane: GLITTER is dreamy and flexing, JERK is jittery NY slang, CHE is paranoid and dark, \
    PRTTIFUN is sugary and playful. Hooks come back word for word. Rhyme inside and at the ends of lines. \
    Original words only: never quote existing songs and never name real artists. Slang is fine; keep it clean \
    enough for the radio, nothing hateful. An intro or break may have no lines; a hook and a verse always have 2 \
    to 4 lines. Eight to twelve lines in the whole plan. Titles vary: not the same first word every time, and \
    never one already performed.
    """

    private static func prompt(for req: [String: Any]) -> String {
        let st = req["state"] as? [String: Any] ?? [:]
        let tempo = req["tempo"] as? [String: Any] ?? [:]
        let anchor = (tempo["anchor"] as? Int) ?? (st["bpm"] as? Int) ?? 120
        let margin = max(4, Int((Double(anchor) * 0.05).rounded()))
        let lo = (tempo["lo"] as? Int) ?? anchor - margin, hi = (tempo["hi"] as? Int) ?? anchor + margin
        let feel = tempo["feel"] as? String ?? ""
        let sync = min(100, max(0, (req["sync"] as? Int) ?? 45))
        let sing = req["sing"] as? String ?? "auto"
        let voices = (req["voices"] as? [String]).flatMap { $0.isEmpty ? nil : $0 } ?? ["the default voice"]
        let avoid = ((req["avoid"] as? [String]) ?? []).filter { !$0.isEmpty }.suffix(6)
        let theme = String(((req["theme"] as? String) ?? "surprise me").trimmingCharacters(in: .whitespaces).prefix(60))
        let chords = (st["chords"] as? [String])?.joined(separator: " | ") ?? ""
        let density = (st["density"] as? [String: Any]).map { d in d.keys.sorted().map { "\($0) \(d[$0] ?? 0)" }.joined(separator: ", ") } ?? ""

        var s = "The beat right now: lane \(st["lane"] ?? "glitter"), \(st["bpm"] ?? anchor) BPM, \(st["key"] ?? "C") \(st["mode"] ?? "major"), " +
                "chords \(chords), swing \(st["swing"] ?? 0)%, scene \(st["scene"] ?? "hook"). Steps on per row: \(density).\n" +
                "Tempo zone: \(lo)-\(hi) BPM, set by the performer around \(anchor); bpm must stay inside it.\n"
        if feel == "uptempo" {
            s += "Feel: uptempo, around 160 BPM. A bar goes by in 1.5 s, so keep lines short and punchy (6-9 syllables), with hype, quick-fire energy and chants that land on the beat.\n"
        } else if feel == "downtempo" {
            s += "Feel: downtempo, around 120 BPM. Lines have room to breathe: laid-back flows, longer lines (8-12 syllables), moodier and more melodic.\n"
        }
        s += "Vocal syncopation \(sync)%: "
        s += sync < 20 ? "every line lands square on the downbeat, so write even lines of the same length.\n"
           : sync >= 60 ? "lines come in on pickups and behind the beat; mix short punchy lines with longer ones and start some on a one-word pickup.\n"
           : "some lines come in on a pickup or behind the beat; vary the line lengths a little.\n"
        switch sing {
        case "hooks": s += "Singing: every hook is sung (sung true); verses, intros and breaks are rapped (sung false).\n"
        case "all": s += "Singing: sing every section (sung true everywhere), short lines with few syllables, like a ballad.\n"
        case "off": s += "Singing: none; rap every section (sung false everywhere).\n"
        default: s += "Singing: your call; sing at least one section (a hook is the natural one) and rap at least one.\n"
        }
        s += "Voices available: \(voices.joined(separator: ", ")).\nTheme from the performer: \(theme).\n"
        if !avoid.isEmpty {
            s += "Already performed this session: \(avoid.joined(separator: "; ")). Do not reuse those titles or lines; change the key, the lane or the mood.\n"
        }
        return s + "Answer with the plan."
    }

    // MARK: speech

    /// One line as a 16-bit WAV, in the voice of that name (or the best voice on the phone).
    func speak(_ text: String, voice: String?) async throws -> Data {
        let list = voices
        let id = list.first { $0.name == voice }?.id ?? list.first?.id
        let previous = speaking
        let task = Task<Data, Error> {
            _ = try? await previous?.value
            return try await speech.render(text, voiceID: id)
        }
        speaking = task
        return try await task.value
    }
}

// MARK: - Speech to a buffer

/// AVSpeechSynthesizer writing into memory instead of the speaker. Off the main actor: the synthesizer calls back
/// on its own thread with one buffer at a time and an empty one at the end.
nonisolated final class SpeechRenderer: @unchecked Sendable {
    struct Failure: LocalizedError {
        let errorDescription: String?
        init(_ text: String) { errorDescription = text }
    }

    private let synthesizer = AVSpeechSynthesizer()

    func render(_ text: String, voiceID: String?) async throws -> Data {
        let utterance = AVSpeechUtterance(string: text.isEmpty ? "yeah" : text)
        utterance.voice = voiceID.flatMap(AVSpeechSynthesisVoice.init(identifier:)) ?? AVSpeechSynthesisVoice(language: "en-US")
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        utterance.prefersAssistiveTechnologySettings = false
        let collector = Collector()
        return try await withCheckedThrowingContinuation { continuation in
            collector.finish = { continuation.resume(with: $0) }
            synthesizer.write(utterance) { buffer in collector.take(buffer) }
            // a voice that is not downloaded never sends its last buffer: give up after a while
            Task.detached { try? await Task.sleep(for: .seconds(30)); collector.timeOut() }
        }
    }

    private final class Collector: @unchecked Sendable {
        private let lock = NSLock()
        private var samples: [Float] = []
        private var rate: Double = 0
        private var done = false
        var finish: ((Result<Data, Error>) -> Void)?

        func take(_ buffer: AVAudioBuffer) {
            guard let pcm = buffer as? AVAudioPCMBuffer else { return }
            lock.lock()
            if pcm.frameLength == 0 { lock.unlock(); complete(); return }
            rate = pcm.format.sampleRate
            samples.append(contentsOf: SpeechRenderer.mono(pcm))
            lock.unlock()
        }

        func timeOut() { complete(timedOut: true) }

        private func complete(timedOut: Bool = false) {
            lock.lock()
            if done { lock.unlock(); return }
            done = true
            let s = samples, r = rate
            lock.unlock()
            if s.isEmpty { finish?(.failure(Failure(timedOut ? "the voice did not answer; is it downloaded?" : "the voice produced no sound"))) }
            else { finish?(.success(SpeechRenderer.wav(s, rate: r))) }
        }
    }

    /// Channel 0 of a buffer as floats, whatever format the voice renders in.
    private static func mono(_ pcm: AVAudioPCMBuffer) -> [Float] {
        let n = Int(pcm.frameLength)
        if let f = pcm.floatChannelData { return Array(UnsafeBufferPointer(start: f[0], count: n)) }
        if let i = pcm.int16ChannelData { return UnsafeBufferPointer(start: i[0], count: n).map { Float($0) / 32768 } }
        if let i = pcm.int32ChannelData { return UnsafeBufferPointer(start: i[0], count: n).map { Float($0) / 2_147_483_648 } }
        return []
    }

    /// 16-bit mono WAV, peak-normalised a touch under full scale, as Pocket TTS hands it over.
    private static func wav(_ samples: [Float], rate: Double) -> Data {
        let peak = samples.reduce(0) { max($0, abs($1)) }
        let gain: Float = peak > 0 ? 0.9 / peak : 1
        let sr = UInt32(rate > 0 ? rate : 22_050), bytes = UInt32(samples.count * 2)
        var d = Data(capacity: 44 + Int(bytes))
        func put(_ s: String) { d.append(contentsOf: Array(s.utf8)) }
        func put32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        func put16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        put("RIFF"); put32(36 + bytes); put("WAVE"); put("fmt "); put32(16); put16(1); put16(1)
        put32(sr); put32(sr * 2); put16(2); put16(16); put("data"); put32(bytes)
        var pcm = [Int16](); pcm.reserveCapacity(samples.count)
        for x in samples { pcm.append(Int16(max(-1, min(1, x * gain)) * 32767)) }
        pcm.withUnsafeBytes { d.append(contentsOf: $0) }
        return d
    }
}
