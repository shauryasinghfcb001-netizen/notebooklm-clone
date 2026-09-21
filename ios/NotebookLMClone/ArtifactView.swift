import SwiftUI

struct ArtifactView: View {
    @Environment(APIClient.self) var api
    let artifactID: String
    let notebookID: String
    @State private var artifact: ArtifactInfo?
    @State private var error = ""
    @State private var shareFile: URL?
    @State private var sheetsURL = ""

    var body: some View {
        Group {
            if let a = artifact {
                artifactBody(a)
            } else if !error.isEmpty {
                Text(error).foregroundStyle(.red).padding()
            } else {
                ProgressView()
            }
        }
        .navigationTitle(artifact?.title ?? "Artifact")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    @ViewBuilder
    private func artifactBody(_ a: ArtifactInfo) -> some View {
        let c = a.content ?? .null
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                switch a.kind ?? "" {
                case "report":
                    Text(md(c["md"]?.string ?? "(empty)")).frame(maxWidth: .infinity, alignment: .leading)
                    ForEach(c["citations"]?.array ?? [], id: \.display) { x in
                        Text("[\(x["ref"]?.int ?? 0)] \(x["source_title"]?.string ?? ""): \((x["quote"]?.string ?? "").prefix(160))")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    shareButton(name: "report.pdf")
                case "flashcards":
                    FlashcardRunner(cards: c["cards"]?.array ?? [])
                case "quiz":
                    QuizRunner(questions: c["questions"]?.array ?? [])
                case "mindmap":
                    MindmapOutline(content: c)
                case "datatable":
                    DatatableGrid(content: c)
                    HStack {
                        shareButton(name: "table.csv")
                        Button("Send to Google Sheets") { Task { await pushSheets() } }
                    }
                    if let u = URL(string: sheetsURL), !sheetsURL.isEmpty {
                        Link("Open spreadsheet", destination: u)
                    }
                case "audio":
                    AudioPanel(artifactID: a.id, content: c)
                case "video":
                    VideoPanel(artifactID: a.id)
                case "slides":
                    ForEach((c["slides"]?.array ?? []).indices, id: \.self) { i in
                        Text("\(i + 1). \(c["slides"]?.array?[i]["title"]?.string ?? "Slide")")
                    }
                    shareButton(name: "slides.pptx")
                case "infographic":
                    InfographicPanel(artifactID: a.id)
                default:
                    Text(c.display).font(.caption).textSelection(.enabled)
                    shareButton(name: "artifact.bin")
                }
            }
            .padding()
        }
    }

    @ViewBuilder
    private func shareButton(name: String) -> some View {
        if let f = shareFile {
            ShareLink("Share file", item: f)
        } else {
            Button("Prepare share…") {
                Task {
                    do {
                        shareFile = try await api.downloadFile(path: "/api/artifacts/\(artifactID)/download", defaultName: name)
                    } catch { error = error.localizedDescription }
                }
            }
        }
    }

    private func load() async {
        do {
            artifact = try await api.get("/api/artifacts/\(artifactID)")
        } catch { error = error.localizedDescription }
    }

    private func pushSheets() async {
        do {
            let r: SheetsResp = try await api.post("/api/artifacts/\(artifactID):sheets")
            sheetsURL = r.spreadsheet_url ?? ""
            if sheetsURL.isEmpty { error = "Sheets returned no URL (is Google connected on the server?)" }
        } catch { error = error.localizedDescription }
    }
}

struct FlashcardRunner: View {
    let cards: [JSONValue]
    @State private var i = 0
    @State private var flipped = false

    var body: some View {
        VStack(spacing: 12) {
            if cards.isEmpty {
                Text("(no cards)")
            } else {
                Text("\(i + 1) / \(cards.count)").font(.caption).foregroundStyle(.secondary)
                Text(flipped ? (cards[i]["back"]?.string ?? "") : (cards[i]["front"]?.string ?? ""))
                    .frame(maxWidth: .infinity, minHeight: 140)
                    .padding()
                    .background(Color(.secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                HStack {
                    Button("Flip") { flipped.toggle() }.buttonStyle(.bordered)
                    Button("← Prev") { i = (i - 1 + cards.count) % cards.count; flipped = false }.buttonStyle(.bordered)
                    Button("Next →") { i = (i + 1) % cards.count; flipped = false }.buttonStyle(.bordered)
                }
            }
        }
    }
}

struct QuizRunner: View {
    let questions: [JSONValue]
    @State private var i = 0
    @State private var score = 0
    @State private var picked: Int?
    @State private var done = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if questions.isEmpty {
                Text("(no questions)")
            } else if done {
                Text("Score: \(score)/\(questions.count)").font(.title2)
                Button("Restart") { i = 0; score = 0; picked = nil; done = false }
            } else {
                let q = questions[i]
                Text("Q\(i + 1)/\(questions.count): \(q["q"]?.string ?? "")").font(.headline)
                ForEach((q["choices"]?.stringArray ?? []).indices, id: \.self) { k in
                    let choices = q["choices"]?.stringArray ?? []
                    let ans = q["answer"]?.int ?? 0
                    Button(choices[k]) { pick(k, ans: ans) }
                        .buttonStyle(.bordered)
                        .tint(picked == nil ? .accentColor : (k == ans ? .green : (k == picked ? .red : .accentColor)))
                        .disabled(picked != nil)
                }
                if picked != nil {
                    Text("Explanation: \(q["explanation"]?.string ?? "")").font(.caption)
                    Button(i + 1 < questions.count ? "Next →" : "Finish") {
                        if i + 1 < questions.count { i += 1; picked = nil } else { done = true }
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
        }
    }

    private func pick(_ k: Int, ans: Int) {
        picked = k
        if k == ans { score += 1 }
    }
}

struct MMRow: Identifiable {
    let id: String
    let label: String
    let depth: Int
}

func flattenMM(_ nodes: [JSONValue], rootHint: String) -> [MMRow] {
    var byID: [String: JSONValue] = [:]
    for n in nodes {
        if let id = n["id"]?.string { byID[id] = n }
    }
    var rows: [MMRow] = []
    var seen = Set<String>()
    func walk(_ id: String, _ depth: Int) {
        guard !seen.contains(id), let n = byID[id] else { return }
        seen.insert(id)
        rows.append(MMRow(id: id, label: n["label"]?.string ?? id, depth: depth))
        for c in n["children"]?.stringArray ?? [] { walk(c, depth + 1) }
    }
    if byID[rootHint] != nil {
        walk(rootHint, 0)
    } else if let match = nodes.first(where: { $0["label"]?.string == rootHint }),
              let id = match["id"]?.string {
        walk(id, 0)
    } else {
        for n in nodes {
            if let id = n["id"]?.string { walk(id, 0) }
        }
    }
    return rows
}

struct MindmapOutline: View {
    let content: JSONValue

    var body: some View {
        let nodes = content["nodes"]?.array ?? []
        let rows = flattenMM(nodes, rootHint: content["root"]?.string ?? "root")
        VStack(alignment: .leading, spacing: 6) {
            Text("Root: \(content["root"]?.string ?? "")").font(.headline)
            ForEach(rows) { r in
                Text("• \(r.label)").padding(.leading, CGFloat(r.depth) * 18)
            }
        }
    }
}

struct DatatableGrid: View {
    let content: JSONValue

    var body: some View {
        let cols = content["columns"]?.stringArray ?? []
        let rows = content["rows"]?.array ?? []
        ScrollView([.horizontal, .vertical]) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 0) {
                    ForEach(cols, id: \.self) { h in
                        Text(h).bold().frame(minWidth: 110, alignment: .leading).padding(6)
                            .background(Color(.secondarySystemBackground))
                    }
                }
                ForEach(rows.indices, id: \.self) { i in
                    HStack(spacing: 0) {
                        ForEach((rows[i].array ?? []).indices, id: \.self) { j in
                            Text(rows[i].array?[j].display ?? "")
                                .frame(minWidth: 110, alignment: .leading).padding(6)
                        }
                    }
                }
            }
        }
        .frame(minHeight: 200)
    }
}

struct AudioPanel: View {
    @Environment(APIClient.self) var api
    let artifactID: String
    let content: JSONValue
    @State private var fileURL: URL?
    @State private var error = ""

    var body: some View {
        VStack {
            if let f = fileURL {
                AudioPlayerView(fileURL: f,
                                chapters: (content["chapters"]?.array ?? []).map {
                                    AudioChapter(n: $0["n"]?.int ?? 0, speaker: $0["speaker"]?.string ?? "",
                                                 start: $0["start"]?.double ?? 0, title: $0["title"]?.string ?? "")
                                },
                                durationHint: content["duration_sec"]?.double ?? 0)
            } else if !error.isEmpty {
                Text(error).foregroundStyle(.red)
            } else {
                ProgressView("Downloading audio…")
                    .task {
                        do {
                            fileURL = try await api.downloadFile(path: "/api/artifacts/\(artifactID)/download", defaultName: "audio.mp3")
                        } catch { error = error.localizedDescription }
                    }
            }
        }
    }
}

struct VideoPanel: View {
    @Environment(APIClient.self) var api
    let artifactID: String
    @State private var fileURL: URL?
    @State private var error = ""

    var body: some View {
        Group {
            if let f = fileURL {
                LocalVideoView(url: f)
            } else if !error.isEmpty {
                Text(error).foregroundStyle(.red)
            } else {
                ProgressView("Downloading video…")
                    .task {
                        do {
                            fileURL = try await api.downloadFile(path: "/api/artifacts/\(artifactID)/download", defaultName: "video.mp4")
                        } catch { error = error.localizedDescription }
                    }
            }
        }
    }
}

struct InfographicPanel: View {
    @Environment(APIClient.self) var api
    let artifactID: String
    @State private var image: UIImage?
    @State private var fileURL: URL?
    @State private var error = ""

    var body: some View {
        VStack {
            if let img = image {
                Image(uiImage: img).resizable().scaledToFit()
                if let f = fileURL { ShareLink("Share PNG", item: f) }
            } else if !error.isEmpty {
                Text(error).foregroundStyle(.red)
            } else {
                ProgressView("Downloading…")
                    .task {
                        do {
                            let f = try await api.downloadFile(path: "/api/artifacts/\(artifactID)/download", defaultName: "graphic.png")
                            fileURL = f
                            if let data = try? Data(contentsOf: f) { image = UIImage(data: data) }
                        } catch { error = error.localizedDescription }
                    }
            }
        }
    }
}
