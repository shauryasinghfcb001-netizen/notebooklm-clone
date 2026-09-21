import SwiftUI

struct StudioView: View {
    @Environment(APIClient.self) var api
    let notebookID: String
    @State private var artifacts: [ArtifactInfo] = []
    @State private var error = ""
    @State private var paramKind: String?
    @State private var openedAID: String?
    @State private var jobRunning = false
    @State private var jobPct = 0.0
    @State private var jobMsg = ""

    let tools: [(kind: String, icon: String, label: String)] = [
        ("report", "doc.text", "Report"),
        ("flashcards", "rectangle.stack", "Cards"),
        ("quiz", "checklist", "Quiz"),
        ("mindmap", "brain", "Mind Map"),
        ("datatable", "tablecells", "Data Table"),
        ("audio", "waveform", "Audio"),
        ("video", "film", "Video"),
        ("slides", "presentation", "Slides"),
        ("infographic", "photo", "Graphic"),
    ]

    var body: some View {
        List {
            Section("Generate") {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 100))]) {
                    ForEach(tools, id: \.kind) { t in
                        Button { paramKind = t.kind } label: {
                            VStack {
                                Image(systemName: t.icon).font(.title2)
                                Text(t.label).font(.caption)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 10)
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }
            if jobRunning {
                Section("Working…") {
                    ProgressView(value: jobPct) { Text(jobMsg).font(.caption) }
                }
            }
            if !error.isEmpty { Text(error).foregroundStyle(.red).font(.caption) }
            Section("Artifacts") {
                ForEach(artifacts) { a in
                    NavigationLink(destination: ArtifactView(artifactID: a.id, notebookID: notebookID)) {
                        VStack(alignment: .leading) {
                            Text(a.title ?? a.kind ?? "?").lineLimit(2)
                            Text("\(a.kind ?? "?") · \(String((a.created_at ?? "").prefix(16)))")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .task { await loadArtifacts() }
        .refreshable { await loadArtifacts() }
        .sheet(item: $paramKind) { kind in
            StudioParamsView(kind: kind) { params in
                paramKind = nil
                Task { await generate(kind: kind, params: params) }
            }
        }
        .navigationDestination(isPresented: Binding(
            get: { openedAID != nil },
            set: { if !$0 { openedAID = nil } }
        )) {
            if let aid = openedAID {
                ArtifactView(artifactID: aid, notebookID: notebookID)
            }
        }
    }

    private func loadArtifacts() async {
        do {
            artifacts = try await api.get("/api/notebooks/\(notebookID)/studio")
        } catch { error = error.localizedDescription }
    }

    private func generate(kind: String, params: [String: JSONValue]) async {
        error = ""
        jobRunning = true
        jobPct = 0.05
        jobMsg = "Generating \(kind)…"
        do {
            if kind == "audio" || kind == "video" {
                let r: StudioResp = try await api.post("/api/notebooks/\(notebookID)/studio/\(kind)",
                                                       query: ["bg": "1"], body: params, timeout: 60)
                if let jid = r.job_id { await pollJob(jid) }
                else { jobRunning = false }
            } else {
                let a: StudioResp = try await api.post("/api/notebooks/\(notebookID)/studio/\(kind)",
                                                       body: params, timeout: 300)
                await loadArtifacts()
                jobRunning = false
                if let aid = a.id { openedAID = aid }
            }
        } catch {
            error = error.localizedDescription
            jobRunning = false
        }
    }

    private func pollJob(_ jid: String) async {
        for _ in 0..<150 {
            if Task.isCancelled { jobRunning = false; return }
            do {
                let j: JobStatus = try await api.get("/api/jobs/\(jid)")
                jobMsg = "\(j.message ?? j.status ?? "") (\(j.progress ?? 0)%)"
                jobPct = Double(j.progress ?? 0) / 100.0
                if j.status == "done" {
                    await loadArtifacts()
                    jobRunning = false
                    if let aid = j.result?["artifact_id"]?.string { openedAID = aid }
                    return
                }
                if j.status == "error" {
                    jobMsg = "Failed: \(j.message ?? "")"
                    jobRunning = false
                    return
                }
            } catch {
                jobMsg = error.localizedDescription
                jobRunning = false
                return
            }
            try? await Task.sleep(nanoseconds: 2_000_000_000)
        }
        jobRunning = false
    }
}

extension String: Identifiable {
    public var id: String { self }
}

struct StudioParamsView: View {
    @Environment(\.dismiss) var dismiss
    let kind: String
    let onGo: ([String: JSONValue]) -> Void
    @State private var count = 5
    @State private var topic = "key concepts"
    @State private var difficulty = "mixed"
    @State private var reportType = "briefing"
    @State private var columns = "Topic, Key point, Source"
    @State private var length = "brief"
    @State private var focus = "the key ideas"
    @State private var tone = "conversational"
    @State private var smartPause = true
    @State private var slideCount = 6
    @State private var theme = "brand"

    var body: some View {
        NavigationStack {
            Form {
                switch kind {
                case "flashcards":
                    Stepper("Cards: \(count)", value: $count, in: 1...30)
                    TextField("Topic", text: $topic)
                    Picker("Difficulty", selection: $difficulty) {
                        ForEach(["mixed", "easy", "hard"], id: \.self) { Text($0) }
                    }
                case "quiz":
                    Stepper("Questions: \(count)", value: $count, in: 1...20)
                case "report":
                    Picker("Type", selection: $reportType) {
                        ForEach(["briefing", "study-guide", "faq", "timeline"], id: \.self) { Text($0) }
                    }
                case "datatable":
                    TextField("Columns (comma-separated)", text: $columns)
                case "audio":
                    Picker("Length", selection: $length) {
                        ForEach(["brief", "standard", "extended"], id: \.self) { Text($0) }
                    }
                    TextField("Focus", text: $focus)
                    Picker("Tone", selection: $tone) {
                        ForEach(["conversational", "formal", "playful"], id: \.self) { Text($0) }
                    }
                    Toggle("Smart pause (remove silences)", isOn: $smartPause)
                case "video":
                    TextField("Focus", text: $focus)
                case "slides":
                    Stepper("Max slides: \(slideCount)", value: $slideCount, in: 3...20)
                case "infographic":
                    Picker("Theme", selection: $theme) {
                        ForEach(["brand", "blue", "green", "dark"], id: \.self) { Text($0) }
                    }
                default:
                    Text("No options — one tap to generate.")
                }
                Button("Generate") { onGo(build()) }
                    .buttonStyle(.borderedProminent)
            }
            .navigationTitle(kind.capitalized)
            .toolbar { Button("Cancel") { dismiss() } }
        }
    }

    private func build() -> [String: JSONValue] {
        switch kind {
        case "flashcards":
            return ["count": .number(Double(count)), "difficulty": .string(difficulty), "topic": .string(topic)]
        case "quiz":
            return ["count": .number(Double(count))]
        case "report":
            return ["type": .string(reportType)]
        case "datatable":
            let cols = columns.split(separator: ",").map { JSONValue.string($0.trimmingCharacters(in: .whitespaces)) }
            return ["columns": .array(cols)]
        case "audio":
            return ["length": .string(length), "focus": .string(focus), "tone": .string(tone), "smart_pause": .bool(smartPause)]
        case "video":
            return ["focus": .string(focus)]
        case "slides":
            return ["slide_count": .number(Double(slideCount))]
        case "infographic":
            return ["theme": .string(theme)]
        default:
            return [:]
        }
    }
}
