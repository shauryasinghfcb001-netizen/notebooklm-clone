import Foundation

enum APIError: Error, LocalizedError {
    case badURL(String)
    case http(Int, String)
    case loginRequired
    case decode(String)
    case noData

    var errorDescription: String? {
        switch self {
        case .badURL(let u): return "Bad server URL: \(u)"
        case .http(let c, let m): return "Server error \(c): \(m)"
        case .loginRequired: return "Login required"
        case .decode(let m): return "Bad server response: \(m)"
        case .noData: return "Empty response"
        }
    }
}

@Observable
@MainActor
final class APIClient {
    var baseURLString: String
    var me: UserInfo?
    var authRequired = false
    var serverReachable = false

    private let session: URLSession
    private let decoder = JSONDecoder()

    init() {
        self.baseURLString = UserDefaults.standard.string(forKey: "serverURL") ?? ""
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 60
        cfg.timeoutIntervalForResource = 600
        self.session = URLSession(configuration: cfg)
    }

    func saveServer(_ s: String) {
        var v = s.trimmingCharacters(in: .whitespacesAndNewlines)
        while v.hasSuffix("/") { v.removeLast() }
        baseURLString = v
        UserDefaults.standard.set(v, forKey: "serverURL")
    }

    private func makeURL(_ path: String, query: [String: String]? = nil) throws -> URL {
        guard var comps = URLComponents(string: baseURLString), comps.host != nil else {
            throw APIError.badURL(baseURLString.isEmpty ? "(empty — set the server in Settings)" : baseURLString)
        }
        comps.path = path
        if let query { comps.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        guard let url = comps.url else { throw APIError.badURL(path) }
        return url
    }

    private func send<T: Decodable>(_ path: String, method: String = "GET",
                                    query: [String: String]? = nil, body: Encodable? = nil,
                                    timeout: TimeInterval? = nil) async throws -> T {
        var req = URLRequest(url: try makeURL(path, query: query))
        req.httpMethod = method
        if let timeout { req.timeoutInterval = timeout }
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONEncoder().encode(AnyEncodable(body))
        }
        let (data, resp) = try await session.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw APIError.noData }
        guard (200..<300).contains(http.statusCode) else {
            let text = String(data: data, encoding: .utf8) ?? ""
            if http.statusCode == 401 && text.contains("login_required") { throw APIError.loginRequired }
            throw APIError.http(http.statusCode, String(text.prefix(300)))
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decode(error.localizedDescription)
        }
    }

    func get<T: Decodable>(_ p: String, query: [String: String]? = nil) async throws -> T {
        try await send(p, query: query)
    }

    func post<T: Decodable>(_ p: String, query: [String: String]? = nil, body: Encodable? = nil,
                            timeout: TimeInterval? = nil) async throws -> T {
        try await send(p, method: "POST", query: query, body: body, timeout: timeout)
    }

    func patch<T: Decodable>(_ p: String, body: Encodable? = nil) async throws -> T {
        try await send(p, method: "PATCH", body: body)
    }

    func remove<T: Decodable>(_ p: String) async throws -> T {
        try await send(p, method: "DELETE")
    }

    func upload<T: Decodable>(path: String, filename: String, data: Data, mime: String) async throws -> T {
        let boundary = "Boundary-\(UUID().uuidString)"
        var req = URLRequest(url: try makeURL(path))
        req.httpMethod = "POST"
        req.timeoutInterval = 300
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".utf8))
        body.append(Data("Content-Type: \(mime)\r\n\r\n".utf8))
        body.append(data)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        req.httpBody = body
        let (rdata, resp) = try await session.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (resp as? HTTPURLResponse)?.statusCode ?? -1
            throw APIError.http(code, String((String(data: rdata, encoding: .utf8) ?? "").prefix(300)))
        }
        return try decoder.decode(T.self, from: rdata)
    }

    func downloadFile(path: String, defaultName: String) async throws -> URL {
        let req = URLRequest(url: try makeURL(path))
        let (tmpURL, resp) = try await session.download(for: req)
        guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw APIError.http((resp as? HTTPURLResponse)?.statusCode ?? -1, "download failed")
        }
        var name = defaultName
        for (k, v) in http.allHeaderFields {
            if let ks = k as? String, let vs = v as? String,
               ks.lowercased() == "content-disposition", let r = vs.range(of: "filename=") {
                name = vs[r.upperBound...].trimmingCharacters(in: CharacterSet(charactersIn: "\"; "))
            }
        }
        let dest = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent(name)
        try? FileManager.default.removeItem(at: dest)
        try FileManager.default.moveItem(at: tmpURL, to: dest)
        return dest
    }

    // MARK: - session

    func bootstrap() async {
        do {
            let h: HealthResp = try await get("/api/health")
            serverReachable = true
            authRequired = h.auth_required ?? false
            if authRequired {
                do { me = try await get("/api/auth/me") } catch { me = nil }
            } else {
                me = UserInfo(id: nil, username: "local", role: "admin", local: true)
            }
        } catch {
            serverReachable = false
        }
    }

    func login(username: String, password: String) async throws {
        me = try await post("/api/auth/login", body: ["username": username, "password": password])
    }

    func register(username: String, password: String) async throws {
        me = try await post("/api/auth/register", body: ["username": username, "password": password])
    }

    func logout() async {
        let _: JSONValue? = try? await post("/api/auth/logout")
        me = nil
    }
}
