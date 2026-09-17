import Combine
import Foundation

@MainActor
final class BridgeClient: ObservableObject {
    @Published var snapshot = AgentSnapshot(working: 0, ended: 0, attention: 0)
    @Published var status = "connecting…"
    @Published var lastHeard = "—"
    @Published var bridgeURL: String = UserDefaults.standard.string(forKey: "bridgeURL")
        ?? "http://100.118.53.14:7733"

    private let speaker = WatchSpeaker()
    private var timer: Timer?
    private var lastKey: String?
    private var lastIds: [String: Set<String>] = [:]
    private var primed = false

    func start() {
        speaker.activate()
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.tick() }
        }
        Task { await tick() }
    }

    func saveURL() {
        UserDefaults.standard.set(bridgeURL, forKey: "bridgeURL")
        primed = false
        lastKey = nil
        lastIds = [:]
        Task { await tick() }
    }

    func speakNow() {
        speaker.speak(
            working: snapshot.working,
            ended: snapshot.ended,
            attention: snapshot.attention,
            event: "Count update."
        )
        lastHeard = "manual push"
    }

    private func tick() async {
        guard let url = URL(string: bridgeURL.trimmingCharacters(in: .whitespacesAndNewlines) + "/api/state") else {
            status = "bad URL"
            return
        }
        do {
            var req = URLRequest(url: url, timeoutInterval: 6)
            req.cachePolicy = .reloadIgnoringLocalCacheData
            let (data, _) = try await URLSession.shared.data(for: req)
            let snap = try JSONDecoder().decode(AgentSnapshot.self, from: data)
            snapshot = snap
            status = "Mac Mini live"
            let key = "\(snap.working)|\(snap.ended)|\(snap.attention)"
            let ids = [
                "working": Set(snap.ids?["working"] ?? []),
                "ended": Set(snap.ids?["ended"] ?? []),
                "attention": Set(snap.ids?["attention"] ?? []),
            ]
            if !primed {
                primed = true
                lastKey = key
                lastIds = ids
                return
            }
            var bits: [String] = []
            if !ids["working"]!.subtracting(lastIds["working"] ?? []).isEmpty { bits.append("Started working.") }
            if !(lastIds["working"] ?? []).subtracting(ids["working"]!).isEmpty { bits.append("Finished.") }
            if !ids["attention"]!.subtracting(lastIds["attention"] ?? []).isEmpty { bits.append("Needs attention.") }
            if key != lastKey && bits.isEmpty { bits.append("Count update.") }
            lastKey = key
            lastIds = ids
            if let event = bits.isEmpty ? nil : bits.joined(separator: " ") {
                speaker.speak(working: snap.working, ended: snap.ended, attention: snap.attention, event: event)
                lastHeard = event
            }
        } catch {
            status = "bridge offline"
        }
    }
}
