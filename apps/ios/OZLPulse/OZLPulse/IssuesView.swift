import SwiftUI
import WebKit

/// "이슈" 탭. 서버가 /preview/ 아래에 내는 독자용 사이트를 웹뷰로 연다.
/// 앱은 토큰을 읽거나 저장하지 않고 JavaScript 를 주입하지 않는다. 로그인 폼은 사이트의 것을 그대로 보여 주고,
/// 세션 쿠키는 웹뷰의 기본(영구) 저장소가 갖는다.
struct IssuesView: View {
    @AppStorage("serverURL") private var server = ""
    @State private var web = IssuesWebModel()
    @State private var showSettings = false

    private var home: URL? { PulseAPI(server: server)?.base.appending(path: "preview/") }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("이슈")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItemGroup(placement: .topBarLeading) {
                        if web.canGoBack {
                            Button { web.webView.goBack() } label: { Label("뒤로", systemImage: "chevron.backward") }
                        }
                    }
                    ToolbarItemGroup(placement: .topBarTrailing) {
                        if home != nil {
                            Button { if let home { web.open(home) } } label: { Label("첫 화면", systemImage: "house") }
                            Button { web.reload() } label: { Label("새로 고침", systemImage: "arrow.clockwise") }
                                .disabled(web.loading)
                        }
                        Button { showSettings = true } label: { Label("설정", systemImage: "gearshape") }
                    }
                }
                .sheet(isPresented: $showSettings) {
                    SettingsView(server: $server) {}
                }
        }
        .onAppear { web.home = home; web.loadIfNeeded() }
        .onChange(of: server) {
            web.home = home
            if let home { web.open(home) }
        }
    }

    @ViewBuilder private var content: some View {
        if home == nil {
            ContentUnavailableView {
                Label("서버 주소가 없습니다", systemImage: "network")
            } description: {
                Text("설정에서 OZL 서버 주소를 넣어 주세요.")
            } actions: {
                Button("설정 열기") { showSettings = true }
            }
        } else {
            IssuesWebView(model: web)
                .ignoresSafeArea(edges: .bottom)
                .overlay {
                    if let error = web.error {
                        ContentUnavailableView {
                            Label("이슈 화면을 불러오지 못했습니다", systemImage: "wifi.exclamationmark")
                        } description: {
                            Text(error)
                        } actions: {
                            Button("다시 시도") { web.retry() }
                                .buttonStyle(.borderedProminent)
                        }
                        .background(Color(.systemBackground))
                    } else if web.loading && !web.hasContent {
                        ProgressView()
                    }
                }
        }
    }
}

@Observable
@MainActor
final class IssuesWebModel: NSObject, WKNavigationDelegate, WKUIDelegate {
    let webView: WKWebView
    var home: URL?
    var canGoBack = false
    var loading = false
    var hasContent = false
    var error: String?
    @ObservationIgnored private var failedURL: URL?
    @ObservationIgnored private var observations: [NSKeyValueObservation] = []

    override init() {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()   // 영구 저장소 — 로그인 세션 쿠키가 앱을 다시 열어도 남는다
        webView = WKWebView(frame: .zero, configuration: config)
        super.init()
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        let refresh = UIRefreshControl()
        refresh.addAction(UIAction { [weak self] _ in self?.reload() }, for: .valueChanged)
        webView.scrollView.refreshControl = refresh
        observations = [
            webView.observe(\.canGoBack, options: [.initial, .new]) { [weak self] _, change in
                let value = change.newValue ?? false
                Task { @MainActor in self?.canGoBack = value }
            },
            webView.observe(\.isLoading, options: [.initial, .new]) { [weak self] _, change in
                let value = change.newValue ?? false
                Task { @MainActor in
                    self?.loading = value
                    if !value { self?.webView.scrollView.refreshControl?.endRefreshing() }
                }
            },
        ]
    }

    func loadIfNeeded() {
        guard webView.url == nil, error == nil, let home else { return }
        open(home)
    }

    func open(_ url: URL) {
        error = nil
        failedURL = nil
        webView.load(URLRequest(url: url))
    }

    func reload() {
        if error != nil || webView.url == nil { retry() } else { webView.reload() }
    }

    func retry() {
        if let url = failedURL ?? webView.url ?? home { open(url) }
        else { webView.scrollView.refreshControl?.endRefreshing() }
    }

    /// 서버와 같은 호스트(와 포트)만 웹뷰 안에서 연다.
    private func isServer(_ url: URL) -> Bool {
        guard let home, let host = url.host?.lowercased(), host == home.host?.lowercased() else { return false }
        return (url.port ?? defaultPort(url)) == (home.port ?? defaultPort(home))
    }

    private func defaultPort(_ url: URL) -> Int { url.scheme?.lowercased() == "https" ? 443 : 80 }

    private func openOutside(_ url: URL) {
        guard ["http", "https", "mailto", "tel"].contains(url.scheme?.lowercased() ?? "") else { return }
        UIApplication.shared.open(url)
    }

    // MARK: WKNavigationDelegate

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction) async -> WKNavigationActionPolicy {
        guard let url = action.request.url else { return .cancel }
        let scheme = url.scheme?.lowercased() ?? ""
        if scheme == "about" || scheme == "blob" || scheme == "data" { return .allow }
        if isServer(url) { return .allow }
        // 다른 호스트: 사용자가 누른 링크나 큰 화면 이동은 Safari 로, 그 밖의 하위 프레임 로드는 막는다.
        if action.targetFrame?.isMainFrame ?? true || action.navigationType == .linkActivated {
            openOutside(url)
        }
        return .cancel
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        error = nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        hasContent = true
        failedURL = nil
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: any Error) {
        fail(error, url: (error as NSError).userInfo[NSURLErrorFailingURLErrorKey] as? URL)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: any Error) {
        fail(error, url: webView.url)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        webView.reload()
    }

    private func fail(_ error: any Error, url: URL?) {
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled { return }   // 다른 이동으로 끊긴 것
        if ns.domain == "WebKitErrorDomain" && ns.code == 102 { return }                 // 정책으로 멈춘 이동(바깥 링크)
        webView.scrollView.refreshControl?.endRefreshing()
        failedURL = url ?? webView.url ?? home
        self.error = Self.describe(ns)
    }

    private static func describe(_ e: NSError) -> String {
        guard e.domain == NSURLErrorDomain else { return e.localizedDescription }
        switch e.code {
        case NSURLErrorCannotConnectToHost:
            return "서버에 연결할 수 없습니다. 맥미니의 OZL 서버가 꺼져 있을 수 있습니다."
        case NSURLErrorNotConnectedToInternet, NSURLErrorNetworkConnectionLost:
            return "네트워크에 연결되어 있지 않습니다."
        case NSURLErrorCannotFindHost, NSURLErrorDNSLookupFailed:
            return "서버 이름을 찾지 못했습니다. 이 기기가 같은 tailnet 에 로그인해 있는지 확인해 주세요."
        case NSURLErrorTimedOut:
            return "서버가 제때 답하지 않았습니다."
        case NSURLErrorAppTransportSecurityRequiresSecureConnection:
            return "이 주소는 HTTP 로 열 수 없습니다. tailnet 이름(ts.net)이나 이 기기 주소를 써 주세요."
        default:
            return e.localizedDescription
        }
    }

    // MARK: WKUIDelegate — target="_blank" 링크

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url {
            if isServer(url) { webView.load(URLRequest(url: url)) } else { openOutside(url) }
        }
        return nil
    }
}

struct IssuesWebView: UIViewRepresentable {
    let model: IssuesWebModel
    func makeUIView(context: Context) -> WKWebView { model.webView }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
