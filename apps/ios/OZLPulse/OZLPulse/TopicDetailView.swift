import Charts
import SwiftUI

struct TopicDetailView: View {
    let topic: Topic
    let server: String
    @State private var history: [HistoryPoint] = []
    @State private var historyError: String?
    @State private var historyLoaded = false

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 6) {
                    Text(topic.title).font(.headline)
                    Text(topic.reasons.joined(separator: " · ")).font(.subheadline).foregroundStyle(.secondary)
                    TagRow(topic: topic)
                }
                .padding(.vertical, 4)
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 6) {
                    ForEach(Signal.allCases) { s in
                        GridRow {
                            Text(s.label).font(.caption)
                            ProgressView(value: min(max(topic.signals[s.rawValue] ?? 0, 0), 1)).tint(s.color)
                            Text(topic.signals[s.rawValue] ?? 0, format: .number.precision(.fractionLength(2)))
                                .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                        }
                    }
                }
            } footer: {
                Text("점수 \(topic.score, format: .number.precision(.fractionLength(2))) · \(topic.rank)위 · 처음 잡힌 때 \(PulseDate.ago(topic.firstSeen))")
            }

            Section("지난 24시간") {
                if let e = historyError {
                    Text(e).font(.footnote).foregroundStyle(.secondary)
                } else if !historyLoaded {
                    Text("불러오는 중…").font(.footnote).foregroundStyle(.secondary)
                } else if history.count < 2 {
                    Text(history.first.map { "실행 1회 — \($0.rank)위 · 매체 \($0.nOutlets)곳" } ?? "지난 24시간 기록이 없습니다")
                        .font(.footnote).foregroundStyle(.secondary)
                } else {
                    TrendChart(history: history)
                }
            }

            if let cov = topic.coverageRecent, !cov.isEmpty {
                Section("슈카월드 최근 다룸") {
                    ForEach(cov, id: \.videoId) { v in
                        VStack(alignment: .leading) {
                            Text(v.title).font(.subheadline)
                            Text(v.date).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }

            Section("기사 \(topic.nItems)건 · \(topic.outlets.joined(separator: ", "))") {
                ForEach(topic.items) { a in
                    ArticleLink(title: a.title, url: a.url, caption: "\(a.outlet) · \(a.tier) · \(PulseDate.ago(a.ts))")
                }
            }

            if !topic.trendHits.isEmpty {
                Section("연결된 급상승어") { Text(topic.trendHits.joined(separator: ", ")) }
            }
        }
        .navigationTitle("\(topic.rank)위")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: topic.topicId) { await loadHistory() }
    }

    private func loadHistory() async {
        guard let api = PulseAPI(server: server) else { historyError = PulseError.noServer.errorDescription; return }
        do {
            history = try await api.topic(topic.topicId).history
            historyError = nil
            historyLoaded = true
        } catch {
            historyError = "추이를 불러오지 못했습니다"
        }
    }
}

/// 순위(1위가 위)와 매체 수를 한 차트에. 순위는 축을 뒤집어 그린다.
struct TrendChart: View {
    let history: [HistoryPoint]

    var body: some View {
        let maxRank = max(history.map(\.rank).max() ?? 1, 10)
        VStack(alignment: .leading, spacing: 8) {
            Chart(history) { p in
                LineMark(x: .value("시각", p.date), y: .value("순위", p.rank))
                    .foregroundStyle(.primary)
                    .interpolationMethod(.monotone)
                PointMark(x: .value("시각", p.date), y: .value("순위", p.rank))
                    .foregroundStyle(.primary).symbolSize(16)
            }
            .chartYScale(domain: .automatic(includesZero: false, reversed: true))
            .chartYAxis { AxisMarks(position: .leading, values: .automatic(desiredCount: min(maxRank, 4))) }
            .frame(height: 120)
            .accessibilityLabel("순위 \(history.first!.rank)위에서 \(history.last!.rank)위")

            Chart(history) { p in   // 실행마다 점 하나 — 시간 단위로 묶으면 같은 시간대 실행이 합쳐져 부풀려진다
                LineMark(x: .value("시각", p.date), y: .value("매체 수", p.nOutlets))
                    .foregroundStyle(Signal.volume.color)
                    .interpolationMethod(.stepEnd)
                PointMark(x: .value("시각", p.date), y: .value("매체 수", p.nOutlets))
                    .foregroundStyle(Signal.volume.color).symbolSize(16)
            }
            .chartYScale(domain: 0...max(history.map(\.nOutlets).max() ?? 1, 1))
            .chartYAxis { AxisMarks(position: .leading) }
            .frame(height: 70)
            .accessibilityLabel("매체 수 \(history.first!.nOutlets)곳에서 \(history.last!.nOutlets)곳")

            Text("위: 순위(위가 1위) \(history.first!.rank)→\(history.last!.rank) · 아래: 매체 수 \(history.first!.nOutlets)→\(history.last!.nOutlets) · 실행 \(history.count)회")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }
}
