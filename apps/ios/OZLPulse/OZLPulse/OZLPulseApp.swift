import SwiftUI

@main
struct OZLPulseApp: App {
    var body: some Scene {
        WindowGroup {
            TabView {
                Tab("화제", systemImage: "chart.bar.xaxis") { ContentView() }
                Tab("이슈", systemImage: "doc.text.magnifyingglass") { IssuesView() }
            }
        }
    }
}
