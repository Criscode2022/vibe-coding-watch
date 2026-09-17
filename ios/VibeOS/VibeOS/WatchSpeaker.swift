import AVFoundation
import Foundation

final class WatchSpeaker {
    private let synth = AVSpeechSynthesizer()

    func activate() {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playback, mode: .spokenAudio, options: [.allowBluetooth, .allowBluetoothA2DP])
            try session.setActive(true)
        } catch {
            NSLog("VibeOS audio session: \(error)")
        }
    }

    func speak(working: Int, ended: Int, attention: Int, event: String?) {
        activate()
        let prefix = (event?.isEmpty == false) ? event! + " " : "Vibe OS. "
        let line = "\(prefix)\(working) working. \(ended) ended. \(attention) need attention."
        synth.stopSpeaking(at: .immediate)
        let utterance = AVSpeechUtterance(string: line)
        utterance.rate = 0.5
        utterance.volume = 1
        utterance.prefersAssistiveTechnologySettings = false
        synth.speak(utterance)
    }
}
