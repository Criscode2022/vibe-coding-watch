import SwiftUI

struct ContentView: View {
    @EnvironmentObject var bridge: BridgeClient

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Text(timeString).font(.largeTitle.monospaced())
                    Spacer()
                    Text(bridge.status)
                        .font(.caption.monospaced())
                        .foregroundStyle(bridge.status.contains("live") ? Color.green : Color.secondary)
                }
                countRow("working", bridge.snapshot.working, .green)
                countRow("ended", bridge.snapshot.ended, .cyan)
                countRow("attention", bridge.snapshot.attention, .orange)
                Text(bridge.lastHeard)
                    .font(.footnote.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                List((bridge.snapshot.orca?.items?.working ?? []) + (bridge.snapshot.orca?.items?.attention ?? []), id: \.id) { item in
                    VStack(alignment: .leading) {
                        Text(item.name ?? "agent").font(.headline)
                        Text("\(item.agent ?? "") · \(item.worktree ?? "")")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                TextField("Mac Mini Tailscale URL", text: $bridge.bridgeURL)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .font(.footnote.monospaced())
                    .onSubmit { bridge.saveURL() }
                HStack {
                    Button("Save URL") { bridge.saveURL() }
                    Spacer()
                    Button("Speak counts") { bridge.speakNow() }
                }
            }
            .padding()
            .navigationTitle("VibeOS")
        }
    }

    private var timeString: String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f.string(from: Date())
    }

    private func countRow(_ label: String, _ value: Int, _ color: Color) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text("\(value)").font(.system(size: 44, weight: .semibold, design: .monospaced)).foregroundStyle(color)
            Text(label.uppercased()).font(.caption).tracking(1.4).foregroundStyle(.secondary)
            Spacer()
        }
    }
}
