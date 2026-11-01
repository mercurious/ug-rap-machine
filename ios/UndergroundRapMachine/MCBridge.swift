import Foundation

/// The MC endpoints (/ai/health, /ai/plan, /ai/progress, /ai/tts), with the same shapes as flip2/server.py so the
/// page does not know the difference. By default the phone plays the MC itself: Apple Intelligence writes the plan
/// and a system voice speaks the lines (OnDeviceMC). Given a bridge URL (POST /bridge, from the MC view), a laptop
/// running `flip2/server.py --llm --tts` gets every call instead, for Gemma and Pocket TTS.
final class MCBridge {
    private static let bridgeKey = "bridgeURL"
    private let local = OnDeviceMC()

    var lanURL: URL? {
        get {
            guard let s = UserDefaults.standard.string(forKey: Self.bridgeKey), !s.isEmpty else { return nil }
            return URL(string: s)
        }
        set { UserDefaults.standard.set(newValue?.absoluteString ?? "", forKey: Self.bridgeKey) }
    }

    func handle(method: String, path: String, query: [String: String], body: Data?) async -> HTTPReply {
        if path == "/bridge" {
            if method == "POST" {
                let obj = body.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
                var s = (obj["url"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                if !s.isEmpty, !s.contains("://") { s = "http://" + s }
                while s.hasSuffix("/") { s.removeLast() }
                lanURL = s.isEmpty ? nil : URL(string: s)
            }
            return .json(["url": lanURL?.absoluteString ?? ""])
        }
        if let lan = lanURL { return await proxy(to: lan, method: method, path: path, query: query, body: body) }

        switch (method, path) {
        case ("GET", "/ai/health"):
            return .json(local.health())
        case ("GET", "/ai/progress"):
            return .json(local.progress)
        case ("POST", "/ai/plan"):
            let req = body.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
            return .json(local.startPlan(req))
        case ("GET", "/ai/plan"):
            guard let job = Int(query["job"] ?? "") else { return .json(["error": "job=N needed"], status: 400) }
            let res = local.plan(job: job)
            return .json(res, status: res["plan"] == nil ? 404 : 200)
        case ("POST", "/ai/tts"):
            let req = body.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
            let text = String((req["text"] as? String ?? "").prefix(200))
            do {
                let wav = try await local.speak(text, voice: req["voice"] as? String)
                return HTTPReply(status: 200, type: "audio/wav", data: wav)
            } catch {
                return .json(["error": error.localizedDescription], status: 502)
            }
        default:
            return .json(["error": "no such endpoint"], status: 404)
        }
    }

    /// Forward a call to the bridge on the Wi-Fi, same path, query and body.
    private func proxy(to lan: URL, method: String, path: String, query: [String: String], body: Data?) async -> HTTPReply {
        guard var comps = URLComponents(url: lan, resolvingAgainstBaseURL: false) else { return .json(["error": "bad bridge url"], status: 502) }
        comps.path = (comps.path.hasSuffix("/") ? String(comps.path.dropLast()) : comps.path) + path
        if !query.isEmpty { comps.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        guard let url = comps.url else { return .json(["error": "bad bridge url"], status: 502) }
        var request = URLRequest(url: url, timeoutInterval: 300)   // a line of TTS can take a while on a laptop
        request.httpMethod = method
        request.httpBody = body
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            let http = response as? HTTPURLResponse
            return HTTPReply(status: http?.statusCode ?? 200,
                             type: http?.value(forHTTPHeaderField: "Content-Type") ?? "application/json", data: data)
        } catch {
            return .json(["error": "bridge \(lan.host() ?? lan.absoluteString): \(error.localizedDescription)"], status: 502)
        }
    }
}
