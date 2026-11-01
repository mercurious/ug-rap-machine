import AVFAudio

/// The audio session a live auto-tune wants: play and record at once, out of the speaker unless headphones or
/// Bluetooth are connected, no system voice processing on the mic (measurement mode leaves the signal alone for the
/// pitch tracker), and the shortest I/O buffer the hardware gives.
enum AudioSessionController {
    /// Off the main thread: activating a session can block for a moment.
    static func configure() {
        Task.detached(priority: .userInitiated) {
            let session = AVAudioSession.sharedInstance()
            do {
                try session.setCategory(.playAndRecord, mode: .measurement,
                                        options: [.defaultToSpeaker, .allowBluetoothA2DP, .allowAirPlay])
                try session.setPreferredSampleRate(48_000)
                try session.setPreferredIOBufferDuration(0.005)
                try session.setActive(true)
            } catch {
                print("audio session: \(error.localizedDescription)")
            }
        }
    }
}
