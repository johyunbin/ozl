import SwiftUI

struct SettingsView: View {
    @Binding var server: String
    var onSave: () -> Void
    @State private var draft = ""
    @State private var check: String?
    @State private var checking = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(text: $draft, prompt: Text(verbatim: "http://기기이름.tailnet.ts.net:8765")) { Text(verbatim: "서버 주소") }
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button {
                        Task { await test() }
                    } label: {
                        if checking { ProgressView() } else { Text("연결 확인") }
                    }
                    .disabled(PulseAPI(server: draft) == nil || checking)
                    if let check { Text(check).font(.footnote).foregroundStyle(.secondary) }
                } header: {
                    Text("OZL 서버 주소")
                } footer: {
                    Text(verbatim: "맥미니에서 tailscale status 로 이름을 확인하세요. 이 기기도 같은 tailnet 에 로그인해 있어야 열립니다. 시뮬레이터에서는 http://127.0.0.1:8765 를 쓸 수 있습니다.")
                }
            }
            .navigationTitle("설정")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("저장") {
                        server = draft.trimmingCharacters(in: .whitespacesAndNewlines)
                        onSave()
                        dismiss()
                    }
                    .disabled(PulseAPI(server: draft) == nil)
                }
            }
            .onAppear { draft = server }
        }
    }

    private func test() async {
        guard let api = PulseAPI(server: draft) else { return }
        checking = true
        defer { checking = false }
        do {
            let h = try await api.health()
            check = h.stale ? "연결됨 — 다만 매시 실행이 멈춘 것 같습니다" : "연결됨" + (h.lastOk.map { " · 마지막 실행 \(PulseDate.ago($0))" } ?? "")
        } catch {
            check = "연결 실패: " + ((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }
}
