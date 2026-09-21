import SwiftUI

struct NotebookDetailView: View {
    @Environment(APIClient.self) var api
    let notebook: Notebook
    @State private var shareURL = ""
    @State private var showShare = false

    var body: some View {
        TabView {
            ChatView(notebookID: notebook.id)
                .tabItem { Label("Chat", systemImage: "bubble.left.and.bubble.right") }
            SourcesView(notebookID: notebook.id)
                .tabItem { Label("Sources", systemImage: "books.vertical") }
            StudioView(notebookID: notebook.id)
                .tabItem { Label("Studio", systemImage: "wand.and.stars") }
            NotesView(notebookID: notebook.id)
                .tabItem { Label("Notes", systemImage: "note.text") }
        }
        .navigationTitle(notebook.title ?? "Notebook")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { Button("Share") { Task { await share() } } }
        .sheet(isPresented: $showShare) {
            VStack(spacing: 16) {
                Text("Share link").font(.headline)
                Text(shareURL).font(.caption).textSelection(.enabled)
                if let url = URL(string: shareURL), shareURL.hasPrefix("http") {
                    ShareLink("Open / Send", item: url)
                }
                Button("Close") { showShare = false }
            }
            .padding()
            .presentationDetents([.medium])
        }
    }

    private func share() async {
        do {
            let r: ShareResp = try await api.post("/api/notebooks/\(notebook.id)/shares", body: ["kind": "notebook"])
            var u = r.url ?? ""
            if u.hasPrefix("/") { u = api.baseURLString + u }
            shareURL = u.isEmpty ? "(empty — set PUBLIC_BASE_URL on the server for full links)" : u
            showShare = true
        } catch {
            shareURL = "Error: \(error.localizedDescription)"
            showShare = true
        }
    }
}
