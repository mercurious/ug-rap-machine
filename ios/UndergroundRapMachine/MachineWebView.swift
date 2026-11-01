import SwiftUI
import WebKit
import AVFAudio

/// The page in a WKWebView, loaded through the app's own URL scheme (see AppSchemeHandler) so it is a secure
/// context with a microphone, and so the MC endpoints it fetches land in this process.
struct MachineWebView: UIViewRepresentable {
    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(context.coordinator.scheme, forURLScheme: AppSchemeHandler.scheme)
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        config.allowsPictureInPictureMediaPlayback = false
        config.userContentController.add(WeakScriptMessageHandler(context.coordinator), name: "urm")

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.uiDelegate = context.coordinator
        webView.navigationDelegate = context.coordinator
        webView.isOpaque = false
        webView.backgroundColor = .black
        webView.scrollView.backgroundColor = .black
        webView.scrollView.isScrollEnabled = false          // the page scrolls its own panels
        webView.scrollView.bounces = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        #if DEBUG
        webView.isInspectable = true                        // Safari → Develop → the phone, for the page's console
        #endif
        context.coordinator.webView = webView
        webView.load(URLRequest(url: AppSchemeHandler.startURL))
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKUIDelegate, WKNavigationDelegate, WKScriptMessageHandler {
        /// The one live coordinator, so the app can poke the page when it comes back to the foreground.
        static weak var current: Coordinator?

        let scheme = AppSchemeHandler()
        weak var webView: WKWebView?
        private let tick = UISelectionFeedbackGenerator()
        private let padHit = UIImpactFeedbackGenerator(style: .medium)
        private let thump = UIImpactFeedbackGenerator(style: .heavy)
        private var interruptions: Task<Void, Never>?

        override init() {
            super.init()
            Coordinator.current = self
            tick.prepare(); padHit.prepare(); thump.prepare()
            // a call or Siri takes the session; when it ends, take it back and wake the page's audio context
            interruptions = Task { [weak self] in
                for await note in NotificationCenter.default.notifications(named: AVAudioSession.interruptionNotification) {
                    guard let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                          AVAudioSession.InterruptionType(rawValue: raw) == .ended else { continue }
                    AudioSessionController.configure()
                    self?.resumePage()
                }
            }
        }

        deinit { interruptions?.cancel() }

        func resumePage() {
            webView?.evaluateJavaScript("window.__urmResume && __urmResume()")
        }

        // MARK: microphone
        // The page's getUserMedia asks WebKit, WebKit asks here; granting it leaves the one system prompt
        // (NSMicrophoneUsageDescription) instead of a second, browser-style one.
        func webView(_ webView: WKWebView, decideMediaCapturePermissionsFor origin: WKSecurityOrigin, initiatedBy frame: WKFrameInfo,
                     type: WKMediaCaptureType) async -> WKPermissionDecision {
            type == .microphone ? .grant : .deny
        }

        // MARK: navigation
        // The page never navigates; anything that tries (a link in a take's name, say) goes to Safari.
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction) async -> WKNavigationActionPolicy {
            guard let url = navigationAction.request.url else { return .cancel }
            if url.scheme == AppSchemeHandler.scheme || url.scheme == "about" || url.scheme == "blob" { return .allow }
            _ = await UIApplication.shared.open(url)
            return .cancel
        }

        // MARK: messages from the page (webkit.messageHandlers.urm)
        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
            switch type {
            case "haptic":
                switch body["k"] as? String {
                case "pad": padHit.impactOccurred()
                case "play", "rec": thump.impactOccurred()
                default: tick.selectionChanged()
                }
            case "share":
                guard let name = body["name"] as? String, let b64 = body["data"] as? String, let data = Data(base64Encoded: b64) else { return }
                share(data, named: name)
            case "log":
                print("page: \(body["text"] as? String ?? "")")
            default:
                break
            }
        }

        /// A take, or a WAV of one: written to a temporary file and handed to the share sheet (Files, AirDrop,
        /// Messages, Voice Memos…), which is how a download works on a phone.
        private func share(_ data: Data, named name: String) {
            let safe = name.replacingOccurrences(of: "/", with: "-")
            let url = FileManager.default.temporaryDirectory.appendingPathComponent(safe)
            do { try data.write(to: url, options: .atomic) } catch { print("share: \(error.localizedDescription)"); return }
            let sheet = UIActivityViewController(activityItems: [url], applicationActivities: nil)
            guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first(where: { $0.activationState == .foregroundActive }),
                  let root = scene.keyWindow?.rootViewController else { return }
            if let pop = sheet.popoverPresentationController, let host = webView {   // iPad anchors it mid-screen
                pop.sourceView = host
                pop.sourceRect = CGRect(x: host.bounds.midX, y: host.bounds.midY, width: 1, height: 1)
                pop.permittedArrowDirections = []
            }
            var top = root
            while let next = top.presentedViewController { top = next }
            top.present(sheet, animated: true)
        }
    }
}

/// WKUserContentController retains its message handlers; this stands in so the coordinator is not kept alive by
/// the web view it owns.
private final class WeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    weak var target: WKScriptMessageHandler?
    init(_ target: WKScriptMessageHandler) { self.target = target }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(userContentController, didReceive: message)
    }
}
