import Foundation

/// `/api/now` — 서버의 now.json 그대로. 키는 snake_case 로 오고 디코더가 camelCase 로 바꾼다.
struct NowPayload: Decodable {
    let generatedAt: String
    let windowHours: Double
    let nWindow: Int
    let nTopics: Int
    let feedsFailed: [FeedStatus]
    let signalStatus: [String: String]
    let topics: [Topic]
    let officialNew: [OfficialItem]
    let searches: [SearchTerm]

    enum CodingKeys: String, CodingKey {
        case generatedAt, windowHours, nWindow, nTopics, feedsFailed, signalStatus, topics, officialNew, searches
    }

    /// 목록은 원소 하나씩 읽어 깨진 원소만 건너뛴다 — 기사 하나의 형식 오류로 화면 전체 갱신이 멈추지 않게.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        generatedAt = try c.decode(String.self, forKey: .generatedAt)
        windowHours = (try? c.decode(Double.self, forKey: .windowHours)) ?? 6
        nWindow = (try? c.decode(Int.self, forKey: .nWindow)) ?? 0
        nTopics = (try? c.decode(Int.self, forKey: .nTopics)) ?? 0
        feedsFailed = c.lossy([FeedStatus].self, forKey: .feedsFailed)
        signalStatus = (try? c.decode([String: String].self, forKey: .signalStatus)) ?? [:]
        topics = c.lossy([Topic].self, forKey: .topics)
        officialNew = c.lossy([OfficialItem].self, forKey: .officialNew)
        searches = c.lossy([SearchTerm].self, forKey: .searches)
    }
}

private struct Skip: Decodable {}   // 읽지 못한 원소를 건너뛰는 자리

extension KeyedDecodingContainer {
    func lossy<T: Decodable>(_ type: [T].Type, forKey key: Key) -> [T] {
        guard var u = try? nestedUnkeyedContainer(forKey: key) else { return [] }
        var out: [T] = []
        while !u.isAtEnd {
            if let v = try? u.decode(T.self) { out.append(v) } else { _ = try? u.decode(Skip.self) }
        }
        return out
    }
}

struct FeedStatus: Decodable, Hashable {
    let id: String
    let outlet: String?
    let error: String?
}

struct Sensitivity: Decodable, Hashable {
    let level: String          // GREEN · YELLOW · RED
    let reasons: [String]
}

struct CoverageHit: Decodable, Hashable {
    let videoId: String
    let title: String
    let date: String
}

struct Article: Decodable, Hashable, Identifiable {
    let title: String
    let url: String
    let outlet: String
    let kind: String
    let tier: String
    let ts: String
    var id: String { url + outlet + title }
}

struct Topic: Decodable, Hashable, Identifiable {
    let topicId: Int
    let rank: Int
    let move: String
    let title: String
    let lang: String
    let score: Double
    let signals: [String: Double]
    let on: [String]
    let reasons: [String]
    let trendHits: [String]
    let nItems: Int
    let nOutlets: Int
    let recent1h: Int
    let firstSeen: String
    let outlets: [String]
    let sensitivity: Sensitivity?
    let coverageRecent: [CoverageHit]?   // null = 커버리지 대조 실패, [] = 겹침 없음
    let items: [Article]
    var id: Int { topicId }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        topicId = try c.decode(Int.self, forKey: .topicId)
        rank = try c.decode(Int.self, forKey: .rank)
        move = (try? c.decode(String.self, forKey: .move)) ?? "-"
        title = try c.decode(String.self, forKey: .title)
        lang = (try? c.decode(String.self, forKey: .lang)) ?? "ko"
        score = (try? c.decode(Double.self, forKey: .score)) ?? 0
        signals = (try? c.decode([String: Double].self, forKey: .signals)) ?? [:]
        on = (try? c.decode([String].self, forKey: .on)) ?? []
        reasons = (try? c.decode([String].self, forKey: .reasons)) ?? []
        trendHits = (try? c.decode([String].self, forKey: .trendHits)) ?? []
        nItems = (try? c.decode(Int.self, forKey: .nItems)) ?? 0
        nOutlets = (try? c.decode(Int.self, forKey: .nOutlets)) ?? 0
        recent1h = (try? c.decode(Int.self, forKey: .recent1h)) ?? 0
        firstSeen = (try? c.decode(String.self, forKey: .firstSeen)) ?? ""
        outlets = (try? c.decode([String].self, forKey: .outlets)) ?? []
        sensitivity = try? c.decode(Sensitivity.self, forKey: .sensitivity)
        // null = 커버리지 대조 실패. 키가 없거나 형식이 다르면 실패와 같이 본다
        coverageRecent = (try? c.decodeIfPresent([CoverageHit].self, forKey: .coverageRecent)) ?? nil
        items = c.lossy([Article].self, forKey: .items)
    }

    // convertFromSnakeCase 는 recent_1h 를 recent1H 로 바꾼다(숫자로 시작하는 조각의 첫 글자를 대문자로 — 실측)
    enum CodingKeys: String, CodingKey {
        case topicId, rank, move, title, lang, score, signals, on, reasons, trendHits, nItems, nOutlets
        case recent1h = "recent1H"
        case firstSeen, outlets, sensitivity, coverageRecent, items
    }
}

struct OfficialItem: Decodable, Hashable, Identifiable {
    let title: String
    let url: String
    let outlet: String
    let tier: String
    let ts: String
    var id: String { url + title }
}

struct SearchTerm: Decodable, Hashable, Identifiable {
    let title: String
    let lang: String
    let traffic: String
    let news: String
    let topicId: Int?
    let sensitivity: Sensitivity?   // 예전 now.json 에는 없다
    var id: String { lang + title }
}

/// `/api/topic/<id>`
struct TopicDetailPayload: Decodable {
    let history: [HistoryPoint]
}

struct HistoryPoint: Decodable, Hashable, Identifiable {
    let at: String
    let rank: Int
    let score: Double
    let nItems: Int
    let nOutlets: Int
    var id: String { at }
    var date: Date { PulseDate.parse(at) ?? .distantPast }
}

/// `/api/health`
struct Health: Decodable {
    let lastOk: String?
    let stale: Bool
    let dbError: String?
}

enum Signal: String, CaseIterable, Identifiable {
    case volume, search, official, community
    var id: String { rawValue }
    var label: String {
        switch self {
        case .volume: "보도"
        case .search: "검색"
        case .official: "기관"
        case .community: "커뮤니티"
        }
    }
}

/// 서버 시각(ISO 8601, 소수 초 6자리) 읽기 — Foundation 은 소수 3자리까지만 확실히 읽어서 잘라 낸다.
enum PulseDate {
    private static let fractional = Date.ISO8601FormatStyle(includingFractionalSeconds: true)   // Sendable — Swift 6 동시성 검사 통과
    private static let plain = Date.ISO8601FormatStyle()

    static func parse(_ s: String) -> Date? {
        let trimmed = s.replacingOccurrences(of: #"(\.\d{3})\d+"#, with: "$1", options: .regularExpression)
        return (try? fractional.parse(trimmed)) ?? (try? plain.parse(trimmed))
    }

    static func ago(_ s: String, now: Date = .now) -> String {
        guard let d = parse(s) else { return "시각 모름" }
        let m = Int((now.timeIntervalSince(d) / 60).rounded())
        if m < 1 { return "방금" }
        if m < 60 { return "\(m)분 전" }
        if m < 1440 { return "\(m / 60)시간 전" }
        return "\(m / 1440)일 전"
    }
}
