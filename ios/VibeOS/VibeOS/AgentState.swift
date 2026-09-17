import Foundation

struct AgentItem: Codable, Identifiable {
    var kind: String?
    var id: String
    var name: String?
    var agent: String?
    var worktree: String?
    var host: String?
    var state: String?
}

struct AgentBuckets: Codable {
    var working: [AgentItem] = []
    var ended: [AgentItem] = []
    var attention: [AgentItem] = []
}

struct OrcaBlock: Codable {
    var available: Bool?
    var working: Int?
    var ended: Int?
    var attention: Int?
    var items: AgentBuckets?
}

struct WatchBlock: Codable {
    var connected: Bool?
    var bridge: String?
}

struct AgentSnapshot: Codable {
    var ts: Int?
    var source: String?
    var working: Int
    var ended: Int
    var attention: Int
    var event: String?
    var ids: [String: [String]]?
    var orca: OrcaBlock?
    var watch: WatchBlock?
}
