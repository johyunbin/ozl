import Foundation

/// Pulse 서버(읽기 전용) 호출. 주소는 설정 화면에서 넣는다 — 저장소에 실제 주소를 적지 않는다.
struct PulseAPI {
    let base: URL

    init?(server: String) {
        let trimmed = server.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https", url.host != nil else { return nil }
        base = url
    }

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private func get<T: Decodable>(_ path: String, as: T.Type) async throws -> T {
        var req = URLRequest(url: base.appending(path: path))
        req.cachePolicy = .reloadIgnoringLocalCacheData
        req.timeoutInterval = 15
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw PulseError.badResponse }
        guard http.statusCode == 200 else { throw PulseError.status(http.statusCode) }
        return try Self.decoder.decode(T.self, from: data)
    }

    func now() async throws -> NowPayload { try await get("api/now", as: NowPayload.self) }
    func health() async throws -> Health { try await get("api/health", as: Health.self) }
    func topic(_ id: Int) async throws -> TopicDetailPayload { try await get("api/topic/\(id)", as: TopicDetailPayload.self) }
}

enum PulseError: LocalizedError {
    case badResponse, status(Int), noServer

    var errorDescription: String? {
        switch self {
        case .badResponse: "응답을 읽지 못했습니다"
        case .status(503): "서버에 아직 결과가 없습니다(첫 실행 전)"
        case .status(403): "서버가 이 주소로 온 요청을 거절했습니다(Host 검사)"
        case .status(let c): "서버 오류 \(c)"
        case .noServer: "설정에서 서버 주소를 넣어 주세요"
        }
    }
}

/// 화면 상태 — 마지막으로 받은 자료는 실패해도 지우지 않는다.
@MainActor
@Observable
final class PulseStore {
    var data: NowPayload?
    var health: Health?
    var healthFailed = false
    var error: String?
    var loading = false
    var lastLoaded: Date?
    private var generation = 0
    private var dataServer: String?

    /// 요청마다 세대 번호를 붙여 가장 최근 요청의 응답만 반영한다 — 늦게 끝난 옛 응답(옛 서버 주소 포함)이 새 자료를 덮지 않게.
    func load(server: String) async {
        generation += 1
        let mine = generation
        guard let api = PulseAPI(server: server) else {
            error = PulseError.noServer.errorDescription
            return
        }
        if dataServer != nil && dataServer != server {   // 주소를 바꿨으면 옛 서버 자료를 새 주소 아래에 두지 않는다
            data = nil
            health = nil
        }
        loading = true
        async let nowTask = api.now()
        async let healthTask = api.health()
        let nowResult: Result<NowPayload, Error>
        do { nowResult = .success(try await nowTask) } catch { nowResult = .failure(error) }
        let healthResult: Health?
        do { healthResult = try await healthTask } catch { healthResult = nil }
        guard mine == generation else { return }   // 더 새 요청이 있다 — 그쪽이 반영한다
        loading = false
        switch nowResult {
        case .success(let d):
            data = d
            dataServer = server
            error = nil
            lastLoaded = .now
        case .failure(let e):
            error = (e as? LocalizedError)?.errorDescription ?? e.localizedDescription
        }
        if let h = healthResult {
            health = h
            healthFailed = false
        } else {
            healthFailed = true   // 마지막 상태는 남겨 두고 확인 실패만 따로 알린다
        }
    }
}
