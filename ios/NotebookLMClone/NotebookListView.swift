import SwiftUI

struct NotebookListView: View {
    @Environment(APIClient.self) var api
    @State private var notebooks: [Notebook] = []
    @State private var quotas: Quotas?
    @State private var showNew = false
    @State private var newTitle = ""
    @State private var error = ""

    var body: some View {
        NavigationStack {
            List {
                if !error.isEmpty { Text(error).foregroundStyle(.red).font(.caption) }
                ForEach(notebooks) { nb in
                    NavigationLink(destination: NotebookDetailView(notebook: nb)) {
                        VStack(alignment: .leading) {
                            Text(nb.title ?? "Untitled").font(.headline)
                            Text("\(nb.sources_count ?? 0) sources · \(String((nb.updated_at ?? "").prefix(10)))")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .swipeActions {
                        Button("Delete", role: .destructive) { Task { await del(nb) } }
                        Button("Duplicate") { Task { await dup(nb) } }.tint(.blue)
                    }
                }
                if quotas != nil {
                    Text(quotaLine).font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Notebooks")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    HStack {
                        NavigationLink(destination: SettingsView()) { Image(systemName: "gear") }
                        Button("✨ Demo") { Task { await seed() } }
                    }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button("＋ New") { newTitle = ""; showNew = true }
                }
            }
            .alert("New notebook", isPresented: $showNew) {
                TextField("Title", text: $newTitle)
                Button("Create") { Task { await create() } }
                Button("Cancel", role: .cancel) {}
            }
            .task { await load() }
            .refreshable { await load() }
        }
    }

    private var quotaLine: String {
        guard let q = quotas else { return "" }
        return "💬 \(q.chats?.used ?? 0)/\(q.chats?.limit ?? 0) · ✨ \(q.studio?.used ?? 0)/\(q.studio?.limit ?? 0) · 🔎 \(q.research?.used ?? 0)/\(q.research?.limit ?? 0)"
    }

    private func load() async {
        do {
            notebooks = try await api.get("/api/notebooks")
            quotas = try await api.get("/api/quotas")
        } catch { error = error.localizedDescription }
    }

    private func create() async {
        do {
            let _: Notebook = try await api.post("/api/notebooks", body: ["title": newTitle.isEmpty ? "Untitled notebook" : newTitle])
            await load()
        } catch { error = error.localizedDescription }
    }

    private func del(_ nb: Notebook) async {
        do {
            let _: JSONValue = try await api.remove("/api/notebooks/\(nb.id)")
            await load()
        } catch { error = error.localizedDescription }
    }

    private func dup(_ nb: Notebook) async {
        do {
            let _: Notebook = try await api.post("/api/notebooks/\(nb.id)/duplicate")
            await load()
        } catch { error = error.localizedDescription }
    }

    private func seed() async {
        do {
            let _: SeedResp = try await api.post("/api/demo:seed")
            await load()
        } catch { error = error.localizedDescription }
    }
}
