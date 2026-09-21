import Foundation

// Lenient JSON value: artifact content shapes vary by kind and may evolve.
enum JSONValue: Codable {
    case string(String), number(Double), bool(Bool), array([JSONValue]), object([String: JSONValue]), null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else if let o = try? c.decode([String: JSONValue].self) { self = .object(o) }
        else { throw DecodingError.dataCorruptedError(in: c, debugDescription: "unknown JSON") }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .number(let n): try c.encode(n)
        case .bool(let b): try c.encode(b)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        case .null: try c.encodeNil()
        }
    }

    var string: String? { if case .string(let s) = self { return s }; return nil }
    var double: Double? { if case .number(let n) = self { return n }; return nil }
    var int: Int? { if case .number(let n) = self { return Int(n) }; return nil }
    var bool: Bool? { if case .bool(let b) = self { return b }; return nil }
    var array: [JSONValue]? { if case .array(let a) = self { return a }; return nil }
    var object: [String: JSONValue]? { if case .object(let o) = self { return o }; return nil }
    subscript(key: String) -> JSONValue? { object?[key] }
    var stringArray: [String] { array?.compactMap { $0.string } ?? [] }
    var display: String {
        switch self {
        case .string(let s): return s
        case .number(let n): return n.truncatingRemainder(dividingBy: 1) == 0 ? String(Int(n)) : String(n)
        case .bool(let b): return b ? "true" : "false"
        case .null: return ""
        case .array(let a): return a.map { $0.display }.joined(separator: ", ")
        case .object: return ""
        }
    }
}

func decodeAs<T: Decodable>(_ j: JSONValue) -> T? {
    guard let data = try? JSONEncoder().encode(j) else { return nil }
    return try? JSONDecoder().decode(T.self, from: data)
}

struct AnyEncodable: Encodable {
    private let enc: (Encoder) throws -> Void
    init<T: Encodable>(_ e: T) { enc = { try e.encode(to: $0) } }
    func encode(to encoder: Encoder) throws { try enc(encoder) }
}

func md(_ s: String) -> AttributedString {
    (try? AttributedString(markdown: s)) ?? AttributedString(s)
}

// Key names match the server API exactly (snake_case).
struct HealthResp: Decodable {
    var ok: Bool?
    var llm_provider: String?
    var auth_required: Bool?
}

struct UserInfo: Decodable {
    var id: String?
    var username: String?
    var role: String?
    var local: Bool?
}

struct Notebook: Codable, Identifiable {
    var id: String
    var title: String?
    var updated_at: String?
    var sources_count: Int?
}

struct SourceInfo: Codable, Identifiable {
    var id: String
    var kind: String?
    var title: String?
    var enabled: Bool?
    var status: String?
    var word_count: Int?
    var error: String?
}

struct SourcePreview: Decodable {
    var text: String?
}

struct Citation: Decodable, Identifiable {
    var ref: Int?
    var source_id: String?
    var source_title: String?
    var quote: String?
    var id: String { "\(ref ?? 0)-\(source_id ?? "?")-\(quote?.prefix(10) ?? "")" }
}

struct ChatMsg: Decodable {
    var id: String?
    var role: String?
    var content: String?
    var citations: [Citation]?
    var created_at: String?
}

struct ChatResp: Decodable {
    var id: String?
    var answer_md: String?
    var citations: [Citation]?
}

struct SuggestResp: Decodable {
    var prompts: [String]?
}

struct NoteInfo: Codable, Identifiable {
    var id: String
    var title: String?
    var content_md: String?
    var updated_at: String?
}

struct ArtifactInfo: Decodable, Identifiable {
    var id: String
    var kind: String?
    var title: String?
    var status: String?
    var created_at: String?
    var content: JSONValue?
    var params: JSONValue?
}

struct StudioResp: Decodable {
    var id: String?
    var job_id: String?
    var kind: String?
    var title: String?
}

struct JobStatus: Decodable {
    var id: String?
    var status: String?
    var progress: Int?
    var message: String?
    var result: JSONValue?
}

struct QuotaVal: Decodable {
    var used: Int?
    var limit: Int?
}

struct Quotas: Decodable {
    var chats: QuotaVal?
    var studio: QuotaVal?
    var research: QuotaVal?
}

struct ShareResp: Decodable {
    var token: String?
    var url: String?
}

struct DriveFile: Decodable, Identifiable {
    var id: String
    var name: String?
    var mimeType: String?
}

struct DriveStatus: Decodable {
    var google_configured: Bool?
    var google_connected: Bool?
    var redirect_uri: String?
}

struct SheetsResp: Decodable {
    var spreadsheet_url: String?
}

struct SeedResp: Decodable {
    var id: String?
    var title: String?
    var sources: Int?
}
