import AVFoundation
import AVKit
import SwiftUI

struct AudioChapter: Identifiable {
    let id = UUID()
    let n: Int
    let speaker: String
    let start: Double
    let title: String
}

@Observable
@MainActor
final class AudioController {
    var playing = false
    var time = 0.0
    var duration = 0.0
    var rate: Float = 1.0
    private var player: AVPlayer?
    private var observer: Any?

    func load(url: URL, hint: Double) {
        stop()
        let p = AVPlayer(url: url)
        player = p
        duration = hint
        observer = p.addPeriodicTimeObserver(forInterval: CMTime(seconds: 0.5, preferredTimescale: 600), queue: .main) { [weak self] t in
            Task { @MainActor in
                guard let self else { return }
                self.time = t.seconds.isFinite ? t.seconds : 0
                if let d = self.player?.currentItem?.duration.seconds, d.isFinite, d > 0 {
                    self.duration = d
                }
            }
        }
    }

    func toggle() {
        guard let p = player else { return }
        if playing {
            p.pause()
            playing = false
        } else {
            p.play()
            p.rate = rate
            playing = true
        }
    }

    func seek(_ s: Double) {
        player?.seek(to: CMTime(seconds: s, preferredTimescale: 600))
        time = s
    }

    func setRate(_ r: Float) {
        rate = r
        if playing { player?.rate = r }
    }

    func stop() {
        if let o = observer {
            player?.removeTimeObserver(o)
            observer = nil
        }
        player?.pause()
        player = nil
        playing = false
    }
}

func fmtTime(_ s: Double) -> String {
    let t = Int(max(0, s))
    return String(format: "%d:%02d", t / 60, t % 60)
}

struct AudioPlayerView: View {
    let fileURL: URL
    let chapters: [AudioChapter]
    let durationHint: Double
    @State private var ctl = AudioController()

    var body: some View {
        VStack(spacing: 10) {
            HStack {
                Button(ctl.playing ? "⏸ Pause" : "▶ Play") { ctl.toggle() }
                    .buttonStyle(.borderedProminent)
                Text("\(fmtTime(ctl.time)) / \(fmtTime(ctl.duration))")
                    .font(.caption)
                    .monospacedDigit()
            }
            Slider(value: Binding(get: { ctl.time }, set: { ctl.seek($0) }),
                   in: 0...max(ctl.duration, 1))
            HStack {
                ForEach([0.75, 1.0, 1.25, 1.5, 2.0], id: \.self) { r in
                    Button("\(r, specifier: "%.2g")×") { ctl.setRate(Float(r)) }
                        .buttonStyle(.bordered)
                        .font(.caption)
                        .tint(abs(Double(ctl.rate) - r) < 0.01 ? .accentColor : .gray)
                }
            }
            if !chapters.isEmpty {
                Text("Chapters").font(.headline).frame(maxWidth: .infinity, alignment: .leading)
                ForEach(chapters) { ch in
                    Button {
                        ctl.seek(ch.start)
                    } label: {
                        HStack {
                            Text("\(ch.n). \(ch.title)").lineLimit(1)
                            Spacer()
                            Text(fmtTime(ch.start)).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .onAppear { ctl.load(url: fileURL, hint: durationHint) }
        .onDisappear { ctl.stop() }
    }
}

struct LocalVideoView: View {
    let url: URL
    @State private var player: AVPlayer

    init(url: URL) {
        self.url = url
        _player = State(initialValue: AVPlayer(url: url))
    }

    var body: some View {
        VideoPlayer(player: player)
            .frame(height: 260)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .onDisappear { player.pause() }
    }
}
