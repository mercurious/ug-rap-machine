import SwiftUI

/// The iPhone build of the Underground Rap Machine. The instrument itself is the same single page as everywhere
/// else (underground-rap-machine.html, opened with ?phone); this shell gives it what a browser on a phone cannot:
/// an audio session set up for live auto-tune, the microphone without a second prompt, haptics, the share sheet
/// for takes, and the MC endpoints answered on the phone itself (Apple Intelligence and a system voice) or by a
/// bridge on the Wi-Fi.
@main
struct UndergroundRapMachineApp: App {
    @Environment(\.scenePhase) private var scenePhase

    init() {
        AudioSessionController.configure()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .preferredColorScheme(.dark)
        }
        .onChange(of: scenePhase) { _, phase in
            // back from the background or a call: the session may have been taken away, and the page's audio
            // context is suspended until something resumes it
            if phase == .active {
                AudioSessionController.configure()
                MachineWebView.Coordinator.current?.resumePage()
            }
        }
    }
}
