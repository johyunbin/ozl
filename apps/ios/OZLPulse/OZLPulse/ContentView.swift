import SwiftUI

enum Pane: String, CaseIterable, Identifiable {
    case topics = "순위", official = "기관 발표", searches = "급상승어"
    var id: String { rawValue }
}

enum LangFilter: String, CaseIterable, Identifiable {
    case all = "전체", ko = "국내", en = "해외"
    var id: String { rawValue }
    func accepts(_ lang: String) -> Bool { self == .all || (self == .ko ? lang == "ko" : lang != "ko") }
}

struct ContentView: View {
    @AppStorage("serverURL") private var server = ""
    @AppStorage("pane") private var pane: Pane = .topics
    @AppStorage("lang") private var lang: LangFilter = .all
    @AppStorage("hideRed") private var hideRed = false
    @State private var store = PulseStore()
    @State private var showSettings = false
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            List {
                statusSection
                switch pane {
                case .topics: topicsSection
                case .official: officialSection
                case .searches: searchesSection
                }
                Section {
                    Text("검증 전 신호입니다. 점수는 순위를 정하는 데만 쓰고 사실 여부와는 상관이 없습니다.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("OZL Pulse")
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: Topic.self) { TopicDetailView(topic: $0, server: server) }
            .safeAreaInset(edge: .top) {
                Picker("보기", selection: $pane) {
                    ForEach(Pane.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal).padding(.bottom, 6)
                .background(.bar)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        Picker("지역", selection: $lang) {
                            ForEach(LangFilter.allCases) { Text($0.rawValue).tag($0) }
                        }
                        Toggle("민감 소재 숨김", isOn: $hideRed)
                    } label: {
                        Label("거르기", systemImage: lang == .all && !hideRed ? "line.3.horizontal.decrease.circle" : "line.3.horizontal.decrease.circle.fill")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Label("설정", systemImage: "gearshape") }
                }
            }
            .refreshable { await store.load(server: server) }
            .sheet(isPresented: $showSettings) {
                SettingsView(server: $server) { Task { await store.load(server: server) } }
            }
            .overlay {
                if store.data == nil {
                    if store.loading {
                        ProgressView()
                    } else if server.isEmpty {
                        ContentUnavailableView {
                            Label("서버 주소가 없습니다", systemImage: "network")
                        } description: {
                            Text("설정에서 Pulse 서버 주소를 넣어 주세요.")
                        } actions: {
                            Button("설정 열기") { showSettings = true }
                        }
                    }
                }
            }
        }
        .task(id: scenePhase) {   // 앞에 올 때 한 번, 앞에 있는 동안 5분마다. 뒤로 가면 이 작업이 취소된다
            guard scenePhase == .active else { return }
            await store.load(server: server)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(300))
                if Task.isCancelled { break }
                await store.load(server: server)
            }
        }
    }

    @ViewBuilder private var statusSection: some View {
        Section {
            if let d = store.data {
                Text("\(PulseDate.ago(d.generatedAt)) 갱신 · 주제 \(d.nTopics) · 기사 \(d.nWindow)건 · 유튜브 \(d.signalStatus["youtube"] ?? "?")"
                     + (d.feedsFailed.isEmpty ? "" : " · 실패 피드 \(d.feedsFailed.count)"))
                    .font(.footnote).foregroundStyle(.secondary)
            }
            if let e = store.error, !server.isEmpty {   // 주소가 없을 때는 가운데 안내 화면이 같은 말을 한다
                Label(e + (store.data == nil ? "" : " — 이전 자료를 보여 줍니다"), systemImage: "exclamationmark.triangle")
                    .font(.footnote).foregroundStyle(.orange)
            }
            if store.healthFailed && !server.isEmpty {
                Label("실행 상태를 확인하지 못했습니다", systemImage: "questionmark.circle")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            if let h = store.health, h.stale {
                Label(h.dbError != nil ? "기록 DB 를 읽지 못했습니다" :
                        h.lastOk.map { "마지막 성공 실행이 \(PulseDate.ago($0))입니다. 매시 실행이 멈췄을 수 있습니다." } ?? "아직 성공한 실행이 없습니다",
                      systemImage: "clock.badge.exclamationmark")
                    .font(.footnote).foregroundStyle(.orange)
            }
        }
    }

    private var visibleTopics: [Topic] {
        (store.data?.topics ?? []).filter { lang.accepts($0.lang) && !(hideRed && $0.sensitivity?.level == "RED") }
    }

    @ViewBuilder private var topicsSection: some View {
        Section {
            if store.data != nil && visibleTopics.isEmpty {
                Text("조건에 맞는 주제가 없습니다").foregroundStyle(.secondary)
            }
            ForEach(visibleTopics) { t in
                NavigationLink(value: t) { TopicRow(topic: t) }
            }
        } header: {
            HStack(spacing: 10) {
                ForEach(Signal.allCases) { s in
                    Label { Text(s.label) } icon: { RoundedRectangle(cornerRadius: 2).fill(s.color).frame(width: 8, height: 8) }
                }
            }
            .font(.caption2)
        }
    }

    @ViewBuilder private var officialSection: some View {
        Section("최근 3시간") {
            let items = store.data?.officialNew ?? []
            if store.data != nil && items.isEmpty { Text("최근 3시간 기관 발표가 없습니다").foregroundStyle(.secondary) }
            ForEach(items) { o in
                ArticleLink(title: o.title, url: o.url, caption: "\(o.outlet) · \(o.tier) · \(PulseDate.ago(o.ts))")
            }
        }
    }

    @ViewBuilder private var searchesSection: some View {
        Section("구글 트렌드 급상승어") {
            let items = (store.data?.searches ?? []).filter { lang.accepts($0.lang) && !(hideRed && $0.sensitivity?.level == "RED") }
            if store.data != nil && items.isEmpty { Text("급상승어가 없습니다").foregroundStyle(.secondary) }
            ForEach(items) { s in
                VStack(alignment: .leading, spacing: 3) {
                    HStack {
                        Text(s.title).font(.body.weight(.semibold))
                        Spacer()
                        Text(s.traffic.isEmpty ? "검색량 모름" : s.traffic).font(.caption).foregroundStyle(.secondary)
                    }
                    if let id = s.topicId, let t = visibleTopics.first(where: { $0.topicId == id }) {   // 숨긴 주제의 제목은 여기서도 보이지 않게
                        Text("연결된 주제 \(t.rank)위 · \(t.title)").font(.caption).foregroundStyle(.tint)
                    }
                    if !s.news.isEmpty { Text(s.news).font(.caption).foregroundStyle(.secondary) }
                }
            }
        }
    }
}

struct TopicRow: View {
    let topic: Topic

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(spacing: 2) {
                Text("\(topic.rank)").font(.title3.monospacedDigit().weight(.semibold))
                MoveBadge(move: topic.move)
            }
            .frame(width: 34)
            VStack(alignment: .leading, spacing: 4) {
                Text(topic.title).font(.subheadline.weight(.semibold)).lineLimit(3)
                Text(topic.reasons.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                TagRow(topic: topic)
            }
            Spacer(minLength: 4)
            VStack(alignment: .trailing, spacing: 4) {
                Text(topic.score, format: .number.precision(.fractionLength(2))).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                SignalBars(signals: topic.signals)
            }
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .combine)
    }
}

struct MoveBadge: View {
    let move: String
    var body: some View {
        Text(move == "-" ? "–" : move)
            .font(.caption2.weight(.medium))
            .foregroundStyle(move == "신규" ? .green : move.hasPrefix("▲") ? .red : move.hasPrefix("▼") ? .blue : .secondary)
    }
}

struct SignalBars: View {
    let signals: [String: Double]
    var body: some View {
        HStack(alignment: .bottom, spacing: 3) {
            ForEach(Signal.allCases) { s in
                let v = min(max(signals[s.rawValue] ?? 0, 0), 1)
                ZStack(alignment: .bottom) {
                    RoundedRectangle(cornerRadius: 2).fill(.quaternary)
                    RoundedRectangle(cornerRadius: 2).fill(s.color).frame(height: 20 * v)
                }
                .frame(width: 7, height: 20)
            }
        }
        .accessibilityLabel(Signal.allCases.map { "\($0.label) \(Int((signals[$0.rawValue] ?? 0) * 100))" }.joined(separator: ", "))
    }
}

struct TagRow: View {
    let topic: Topic
    var body: some View {
        HStack(spacing: 4) {
            Tag(text: topic.lang == "ko" ? "국내" : "해외")
            if let s = topic.sensitivity, s.level != "GREEN" {
                Tag(text: s.level == "RED" ? "민감" : "주의", tint: s.level == "RED" ? .red : .yellow)
            }
            if let c = topic.coverageRecent?.first { Tag(text: "슈카 최근 \(c.date)") }
            if topic.coverageRecent == nil { Tag(text: "커버리지 대조 실패") }
        }
    }
}

struct Tag: View {
    let text: String
    var tint: Color = .secondary
    var body: some View {
        Text(text).font(.caption2)
            .padding(.horizontal, 6).padding(.vertical, 1)
            .foregroundStyle(tint == .secondary ? Color.secondary : tint)
            .background(tint == .secondary ? Color.secondary.opacity(0.12) : tint.opacity(0.18), in: RoundedRectangle(cornerRadius: 4))
    }
}

/// 외부 피드에서 온 주소는 http(s) 만 연다.
struct ArticleLink: View {
    let title: String
    let url: String
    let caption: String
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            if let u = URL(string: url), ["http", "https"].contains(u.scheme?.lowercased() ?? "") {
                Link(title, destination: u).font(.subheadline)
            } else {
                Text(title).font(.subheadline)
            }
            Text(caption).font(.caption).foregroundStyle(.secondary)
        }
    }
}

extension Signal {
    var color: Color {
        switch self {
        case .volume: .orange
        case .search: .purple
        case .official: .green
        case .community: .teal
        }
    }
}
