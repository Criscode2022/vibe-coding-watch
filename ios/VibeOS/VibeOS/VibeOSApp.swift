import SwiftUI

@main
struct VibeOSApp: App {
    @StateObject private var bridge = BridgeClient()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(bridge)
                .onAppear { bridge.start() }
        }
    }
}
