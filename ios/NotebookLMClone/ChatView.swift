import SwiftUI

struct ChatView: View {
    @Environment(APIClient.self) var api
    let notebookID: String
    @State private var messages: [ChatMsg] = []
    @State private var input = ""
    @State private var sending = false
    @State private var prompts: [String] = []
    @State private var error = ""
    @State private var selectedCite: Citation?
    @State private var showCite = false
    @State private var savedFlash = false

    var body: some View {
        VStack(spacing: 0) {
            if !prompts.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack {
                        ForEach(prompts, id: \.self) { p in
                            Button(p) { input = p; Task { await send() } }
                                .font(.caption)
                                .buttonStyle(.bordered)
                                .lineLimit(1)
                        }
                    }
                    .padding(.horizontal, 8)
                }
                .padding(.vertical, 6)
            }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        ForEach(messages.indices, id: \.self) { i in
                            MessageRow(msg: messages[i],
                                       onCite: { c in selectedCite = c; showCite = true },
                                       onSave: { let m = messages[i]; Task { await saveChat(m) } })
                                .id(i)
                        }
                        if sending { ProgressView().padding(.leading) }
                        if !error.isEmpty { Text(error).foregroundStyle(.red).font(.caption) }
                    }
                    .padding(8)
                }
                .onChange(of: messages.count) { _, _ in
                    if let last = messages.indices.last {
                        withAnimation { proxy.scrollTo(last, anchor: .bottom) }
                    }
                }
            }
            HStack {
                TextField("Ask about your sources…", text: $input)
                    .textFieldStyle(.roundedBorder)
                    .disabled(sending)
                Button("Send") { Task { await send() } }
                    .disabled(sending || input.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(8)
        }
        .task { await load() }
        .sheet(isPresented: $showCite) {
            if let c = selectedCite {
                VStack(alignment: .leading, spacing: 12) {
                    Text("[\(c.ref ?? 0)] \(c.source_title ?? "Source")").font(.headline)
                    ScrollView { Text("“\(c.quote ?? "")”") }
                    Button("Close") { showCite = false }
                }
                .padding()
                .presentationDetents([.medium])
            }
        }
        .alert("Saved to Notes", isPresented: $savedFlash) { Button("OK") {} }
    }

    private func load() async {
        do {
            messages = try await api.get("/api/notebooks/\(notebookID)/chat")
            let s: SuggestResp = try await api.post("/api/notebooks/\(notebookID)/chat:suggest")
            prompts = s.prompts ?? []
        } catch { error = error.localizedDescription }
    }

    private func send() async {
        let m = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !m.isEmpty else { return }
        input = ""
        sending = true
        error = ""
        messages.append(ChatMsg(id: nil, role: "user", content: m, citations: nil, created_at: nil))
        do {
            let r: ChatResp = try await api.post("/api/notebooks/\(notebookID)/chat", body: ["message": m], timeout: 180)
            messages.append(ChatMsg(id: r.id, role: "assistant", content: r.answer_md, citations: r.citations, created_at: nil))
        } catch { error = error.localizedDescription }
        sending = false
    }

    private func saveChat(_ m: ChatMsg) async {
        guard let id = m.id else { return }
        do {
            let _: NoteInfo = try await api.post("/api/notebooks/\(notebookID)/notes:from-chat", body: ["chat_id": id])
            savedFlash = true
        } catch { error = error.localizedDescription }
    }
}

struct MessageRow: View {
    let msg: ChatMsg
    let onCite: (Citation) -> Void
    let onSave: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(msg.role == "user" ? "You" : "Assistant")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(md(msg.content ?? ""))
                .frame(maxWidth: .infinity, alignment: .leading)
            if let cites = msg.citations, !cites.isEmpty {
                HStack {
                    ForEach(cites) { c in
                        Button("[\(c.ref ?? 0)]") { onCite(c) }
                            .buttonStyle(.bordered)
                            .font(.caption)
                    }
                }
            }
            if msg.role == "assistant" {
                Button("Save to note") { onSave() }.font(.caption)
            }
        }
        .padding(8)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }
}
