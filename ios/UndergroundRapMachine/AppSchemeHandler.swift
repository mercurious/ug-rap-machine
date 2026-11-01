import WebKit
import UniformTypeIdentifiers

/// Serves the page out of the app bundle on urm://app/ and answers the endpoints the page expects from the bridge
/// (flip2/server.py). A custom scheme is a secure context, so the microphone works, and every fetch('/ai/…') the
/// page makes lands here instead of on a server.
final class AppSchemeHandler: NSObject, WKURLSchemeHandler {
    static let scheme = "urm"
    static let startURL = URL(string: "urm://app/underground-rap-machine.html?phone&mc")!

    let bridge = MCBridge()
    /// Tasks still waiting for an answer. WebKit raises if a task is answered after it asked for it to stop, so
    /// a task is only answered while it is still in here.
    private var active: [ObjectIdentifier: any WKURLSchemeTask] = [:]

    func webView(_ webView: WKWebView, start urlSchemeTask: any WKURLSchemeTask) {
        let id = ObjectIdentifier(urlSchemeTask)
        active[id] = urlSchemeTask
        let request = urlSchemeTask.request
        Task {
            let reply = await respond(to: request)
            guard let task = active.removeValue(forKey: id) else { return }
            let headers = ["Content-Type": reply.type, "Content-Length": String(reply.data.count), "Cache-Control": "no-store"]
            guard let url = request.url,
                  let response = HTTPURLResponse(url: url, statusCode: reply.status, httpVersion: "HTTP/1.1", headerFields: headers) else { return }
            task.didReceive(response)
            task.didReceive(reply.data)
            task.didFinish()
        }
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: any WKURLSchemeTask) {
        active.removeValue(forKey: ObjectIdentifier(urlSchemeTask))
    }

    private func respond(to request: URLRequest) async -> HTTPReply {
        guard let url = request.url, let comps = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return .json(["error": "bad url"], status: 400)
        }
        let path = comps.path.isEmpty ? "/" : comps.path
        var query: [String: String] = [:]
        for item in comps.queryItems ?? [] { query[item.name] = item.value ?? "" }
        let method = request.httpMethod ?? "GET"

        if path.hasPrefix("/ai/") || path == "/bridge" {
            return await bridge.handle(method: method, path: path, query: query, body: Self.body(of: request))
        }
        // the handheld's endpoints (LEDs, Wi-Fi sync, battery, remote control): not on a phone
        if ["/led", "/sync", "/sys", "/link", "/status", "/cmd"].contains(path) {
            return .json(["error": "not on this device", "unavailable": true], status: 404)
        }
        // a file from the bundle; the page is at the bundle's top level
        let name = (path as NSString).lastPathComponent
        let ext = (name as NSString).pathExtension
        let base = (name as NSString).deletingPathExtension
        guard !base.isEmpty, let fileURL = Bundle.main.url(forResource: base, withExtension: ext.isEmpty ? nil : ext),
              let data = try? Data(contentsOf: fileURL) else {
            return .json(["error": "no such file"], status: 404)
        }
        let type = UTType(filenameExtension: ext)?.preferredMIMEType ?? "application/octet-stream"
        return HTTPReply(status: 200, type: type.hasPrefix("text/") ? type + "; charset=utf-8" : type, data: data)
    }

    /// The body of a POST from fetch(): WebKit hands it over as data or, for larger ones, as a stream.
    private static func body(of request: URLRequest) -> Data? {
        if let data = request.httpBody { return data }
        guard let stream = request.httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var data = Data()
        let size = 65_536
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: size)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let n = stream.read(buffer, maxLength: size)
            if n <= 0 { break }
            data.append(buffer, count: n)
        }
        return data
    }
}

/// What an endpoint answers with.
struct HTTPReply {
    var status: Int
    var type: String
    var data: Data

    static func json(_ object: Any, status: Int = 200) -> HTTPReply {
        let data = (try? JSONSerialization.data(withJSONObject: object)) ?? Data("{}".utf8)
        return HTTPReply(status: status, type: "application/json", data: data)
    }
}
