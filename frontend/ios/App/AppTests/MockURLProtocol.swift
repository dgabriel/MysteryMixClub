import Foundation

/// Intercepts every request `URLSession.shared` makes for the duration of a
/// test. `MMCAPIClient` talks to `URLSession.shared` directly and is not
/// configurable with a mock session (ADR 0029: the MMC access token and its
/// HTTP traffic never cross the WebView bridge, so there was never a reason to
/// make the transport pluggable) -- registering this class process-wide via
/// `URLProtocol.registerClass` is the only seam available to test it without
/// a real server.
final class MockURLProtocol: URLProtocol {
    struct Stub {
        let status: Int
        let json: [String: Any]
    }

    /// One FIFO queue of stubbed responses per exact request path. A path
    /// called more times than it has stubs queued fails loudly instead of
    /// silently reusing the last stub -- an unexpected extra call (e.g. a
    /// refresh loop) should fail a test, not pass it by accident.
    static var stubs: [String: [Stub]] = [:]
    static var requests: [URLRequest] = []

    // `class`, not `static`: overriding an Objective-C class method
    // (URLProtocol is NSObject-based) requires dynamic dispatch.
    // swiftlint:disable:next static_over_final_class
    override class func canInit(with request: URLRequest) -> Bool { true }

    // swiftlint:disable:next static_over_final_class
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        MockURLProtocol.requests.append(request)
        guard let url = request.url else {
            client?.urlProtocol(self, didFailWithError: URLError(.badURL))
            return
        }
        guard var queue = MockURLProtocol.stubs[url.path], !queue.isEmpty else {
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        let stub = queue.removeFirst()
        MockURLProtocol.stubs[url.path] = queue
        let response = HTTPURLResponse(
            url: url, statusCode: stub.status, httpVersion: "HTTP/1.1", headerFields: nil
        )!
        // Test-only fixture data the test itself constructs, never external input.
        // swiftlint:disable:next force_try
        let data = try! JSONSerialization.data(withJSONObject: stub.json)
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    static func reset() {
        stubs = [:]
        requests = []
    }
}
