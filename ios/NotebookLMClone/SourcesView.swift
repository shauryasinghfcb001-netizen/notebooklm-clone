import SwiftUI
import UniformTypeIdentifiers

struct SourcesView: View {
    @Environment(APIClient.self) var api
    let notebookID: String
    @State private var sources: [SourceInfo] = []
    @State private var error = ""
    @State private var showPaste = false
    @State private var showURL = false
    @State private var showYT = false
    @State private var showFile = false
    @State private var showDrive = false
    @State private var previewText = ""
    @State private var previewTitle = ""
    @State private var showPreview = false

    var body: some View {
        List {
            if !error.isEmpty { Text(error).foregroundStyle(.red).font(.caption) }
            ForEach(sources) { s in
                HStack {
                    Toggle("", isOn: Binding(
                        get: { s.enabled ?? true },
                        set: { v in Task { await setEnabled(s, v) } }
                    ))
                    .labelsHidden()
                    VStack(alignment: .leading) {
                        Text(s.title ?? "Untitled").font(.headline).lineLimit(2)
                        Text("\(s.kind ?? "?") · \(s.word_count ?? 0) words · \(s.status ?? "")")
                            .font(.caption).foregroundStyle(.secondary)
                        if let e = s.error, !e.isEmpty {
                            Text(e).font(.caption).foregroundStyle(.red)
                        }
                    }
                    Spacer()
                    Button("👁") { Task { await preview(s) } }
                    Button("🗑") { Task { await del(s) } }
                }
            }
        }
        .toolbar {
            Menu("＋ Add") {
                Button("Pasted text") { showPaste = true }
                Button("Web URL") { showURL = true }
                Button("YouTube") { showYT = true }
                Button("File (PDF/DOCX/…)") { showFile = true }
                Button("Google Drive") { showDrive = true }
            }
        }
        .task { await load() }
        .refreshable { await load() }
        .sheet(isPresented: $showPaste) { PasteSheet(notebookID: notebookID) { await load() } }
        .sheet(isPresented: $showURL) { URLSheet(notebookID: notebookID, youTube: false) { await load() } }
        .sheet(isPresented: $showYT) { URLSheet(notebookID: notebookID, youTube: true) { await load() } }
        .sheet(isPresented: $showDrive) { DriveSheet(notebookID: notebookID) { await load() } }
        .sheet(isPresented: $showPreview) {
            NavigationStack {
                ScrollView { Text(previewText).padding() }
                    .navigationTitle(previewTitle)
                    .navigationBarTitleDisplayMode(.inline)
            }
            .presentationDetents([.large])
        }
        .fileImporter(isPresented: $showFile, allowedContentTypes: [.data]) { result in
            switch result {
            case .success(let urls):
                guard let u = urls.first else { return }
                Task { await importFile(u) }
            case .failure(let e): error = e.localizedDescription
            }
        }
    }

    private func load() async {
        do {
            sources = try await api.get("/api/notebooks/\(notebookID)/sources")
        } catch { error = error.localizedDescription }
    }

    private func setEnabled(_ s: SourceInfo, _ v: Bool) async {
        do {
            let _: SourceInfo = try await api.patch("/api/notebooks/\(notebookID)/sources/\(s.id)", body: ["enabled": v])
            await load()
        } catch { error = error.localizedDescription }
    }

    private func del(_ s: SourceInfo) async {
        do {
            let _: JSONValue = try await api.remove("/api/notebooks/\(notebookID)/sources/\(s.id)")
            await load()
        } catch { error = error.localizedDescription }
    }

    private func preview(_ s: SourceInfo) async {
        do {
            let p: SourcePreview = try await api.get("/api/notebooks/\(notebookID)/sources/\(s.id)/preview")
            previewTitle = s.title ?? "Preview"
            previewText = p.text ?? "(empty)"
            showPreview = true
        } catch { error = error.localizedDescription }
    }

    private func importFile(_ u: URL) async {
        let accessing = u.startAccessingSecurityScopedResource()
        defer { if accessing { u.stopAccessingSecurityScopedResource() } }
        do {
            let data = try Data(contentsOf: u)
            let _: SourceInfo = try await api.upload(path: "/api/notebooks/\(notebookID)/sources:file",
                                                     filename: u.lastPathComponent, data: data,
                                                     mime: "application/octet-stream")
            await load()
        } catch { error = error.localizedDescription }
    }
}

struct PasteSheet: View {
    @Environment(APIClient.self) var api
    @Environment(\.dismiss) var dismiss
    let notebookID: String
    let onDone: () async -> Void
    @State private var title = ""
    @State private var text = ""
    @State private var error = ""

    var body: some View {
        NavigationStack {
            Form {
                TextField("Title", text: $title)
                TextEditor(text: $text).frame(minHeight: 160)
                if !error.isEmpty { Text(error).foregroundStyle(.red) }
                Button("Add source") {
                    Task {
                        do {
                            let _: SourceInfo = try await api.post("/api/notebooks/\(notebookID)/sources:paste",
                                                                   body: ["title": title.isEmpty ? "Pasted text" : title, "text": text])
                            await onDone()
                            dismiss()
                        } catch { error = error.localizedDescription }
                    }
                }
            }
            .navigationTitle("Paste text")
        }
    }
}

struct URLSheet: View {
    @Environment(APIClient.self) var api
    @Environment(\.dismiss) var dismiss
    let notebookID: String
    let youTube: Bool
    let onDone: () async -> Void
    @State private var url = ""
    @State private var error = ""

    var body: some View {
        NavigationStack {
            Form {
                TextField(youTube ? "YouTube link" : "Article URL", text: $url)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                if !error.isEmpty { Text(error).foregroundStyle(.red) }
                Button("Add") {
                    Task {
                        do {
                            let ep = youTube ? "sources:youtube" : "sources:url"
                            let _: SourceInfo = try await api.post("/api/notebooks/\(notebookID)/\(ep)",
                                                                   body: ["url": url], timeout: 180)
                            await onDone()
                            dismiss()
                        } catch { error = error.localizedDescription }
                    }
                }
            }
            .navigationTitle(youTube ? "YouTube" : "Web URL")
        }
    }
}

struct DriveSheet: View {
    @Environment(APIClient.self) var api
    @Environment(\.dismiss) var dismiss
    @Environment(\.openURL) var openURL
    let notebookID: String
    let onDone: () async -> Void
    @State private var status: DriveStatus?
    @State private var files: [DriveFile] = []
    @State private var error = ""
    @State private var connectURL = ""

    var body: some View {
        NavigationStack {
            List {
                if !error.isEmpty { Text(error).foregroundStyle(.red).font(.caption) }
                if status?.google_configured != true {
                    Text("Google not configured on the server. Set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET there, restart it, then retry.")
                        .font(.caption)
                } else if status?.google_connected != true {
                    if connectURL.isEmpty {
                        Button("Connect Google Drive") { Task { await fetchConnect() } }
                    } else if let u = URL(string: connectURL) {
                        Link("Open Google sign-in", destination: u)
                        Button("I've connected — refresh") { Task { await load() } }
                    }
                } else {
                    ForEach(files) { f in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(f.name ?? "?").lineLimit(2)
                                Text(f.mimeType ?? "").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button("Import") { Task { await importDrive(f) } }
                        }
                    }
                }
            }
            .navigationTitle("Google Drive")
            .task { await load() }
        }
    }

    private func load() async {
        do {
            status = try await api.get("/api/integrations/status")
            if status?.google_connected == true {
                files = try await api.get("/api/integrations/drive/files")
            }
        } catch { error = error.localizedDescription }
    }

    private func fetchConnect() async {
        do {
            let r: JSONValue = try await api.get("/api/integrations/drive/auth-url")
            connectURL = r["url"]?.string ?? ""
        } catch { error = error.localizedDescription }
    }

    private func importDrive(_ f: DriveFile) async {
        do {
            let _: SourceInfo = try await api.post("/api/notebooks/\(notebookID)/sources:drive",
                                                   body: ["file_id": f.id], timeout: 180)
            await onDone()
            dismiss()
        } catch { error = error.localizedDescription }
    }
}
