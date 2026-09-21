import SwiftUI

struct NotesView: View {
    @Environment(APIClient.self) var api
    let notebookID: String
    @State private var notes: [NoteInfo] = []
    @State private var error = ""
    @State private var editing: NoteInfo?
    @State private var showEditor = false
    @State private var shareFile: URL?

    var body: some View {
        List {
            if !error.isEmpty { Text(error).foregroundStyle(.red).font(.caption) }
            ForEach(notes) { n in
                VStack(alignment: .leading) {
                    Text(n.title ?? "Untitled").font(.headline)
                    Text(String((n.content_md ?? "").prefix(120)))
                        .font(.caption).foregroundStyle(.secondary).lineLimit(3)
                }
                .swipeActions {
                    Button("Delete", role: .destructive) { Task { await del(n) } }
                    Button("Edit") { editing = n; shareFile = nil; showEditor = true }.tint(.blue)
                    Button("PDF") { Task { await pdf(n) } }.tint(.orange)
                }
            }
            if let f = shareFile {
                ShareLink("Share the PDF", item: f)
            }
        }
        .toolbar {
            Button("＋ Note") { editing = nil; showEditor = true }
        }
        .task { await load() }
        .refreshable { await load() }
        .sheet(isPresented: $showEditor) {
            NoteEditor(notebookID: notebookID, note: editing) { await load() }
        }
    }

    private func load() async {
        do {
            notes = try await api.get("/api/notebooks/\(notebookID)/notes")
        } catch { error = error.localizedDescription }
    }

    private func del(_ n: NoteInfo) async {
        do {
            let _: JSONValue = try await api.remove("/api/notebooks/\(notebookID)/notes/\(n.id)")
            await load()
        } catch { error = error.localizedDescription }
    }

    private func pdf(_ n: NoteInfo) async {
        do {
            shareFile = try await api.downloadFile(path: "/api/notebooks/\(notebookID)/notes/\(n.id)/pdf",
                                                   defaultName: "note.pdf")
        } catch { error = error.localizedDescription }
    }
}

struct NoteEditor: View {
    @Environment(APIClient.self) var api
    @Environment(\.dismiss) var dismiss
    let notebookID: String
    let note: NoteInfo?
    let onDone: () async -> Void
    @State private var title = ""
    @State private var content = ""
    @State private var error = ""

    var body: some View {
        NavigationStack {
            Form {
                TextField("Title", text: $title)
                TextEditor(text: $content).frame(minHeight: 220)
                if !error.isEmpty { Text(error).foregroundStyle(.red) }
                Button("Save") { Task { await save() } }.buttonStyle(.borderedProminent)
            }
            .navigationTitle(note == nil ? "New note" : "Edit note")
            .toolbar { Button("Cancel") { dismiss() } }
            .onAppear {
                title = note?.title ?? ""
                content = note?.content_md ?? ""
            }
        }
    }

    private func save() async {
        do {
            if let n = note {
                let _: NoteInfo = try await api.patch("/api/notebooks/\(notebookID)/notes/\(n.id)",
                                                      body: ["title": title, "content_md": content])
            } else {
                let _: NoteInfo = try await api.post("/api/notebooks/\(notebookID)/notes",
                                                     body: ["title": title, "content_md": content])
            }
            await onDone()
            dismiss()
        } catch { error = error.localizedDescription }
    }
}
