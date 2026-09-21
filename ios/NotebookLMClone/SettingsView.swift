import SwiftUI

struct SettingsView: View {
    @Environment(APIClient.self) var api
    @State private var server = ""
    @State private var username = ""
    @State private var password = ""
    @State private var error = ""
    @State private var quotas: Quotas?
    @State private var busy = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    TextField("http://192.168.1.5:8000", text: $server)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button("Save & Connect") {
                        Task {
                            api.saveServer(server)
                            await api.bootstrap()
                            await loadQuotas()
                        }
                    }
                    Text(api.serverReachable ? "● Connected" : "○ Not connected")
                        .font(.caption)
                        .foregroundStyle(api.serverReachable ? .green : .secondary)
                }
                Section("Account") {
                    if let me = api.me, api.authRequired {
                        Text("\(me.username ?? "?") · \(me.role ?? "")")
                        Button("Log out") { Task { await api.logout() } }
                    } else if api.authRequired {
                        TextField("Username", text: $username)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                        SecureField("Password", text: $password)
                        if !error.isEmpty { Text(error).foregroundStyle(.red).font(.caption) }
                        HStack {
                            Button("Log in") { Task { await doAuth(register: false) } }.disabled(busy)
                            Button("Register") { Task { await doAuth(register: true) } }.disabled(busy)
                        }
                    } else {
                        Text("Auth is off on this server — you are the local owner.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                Section("Usage today") {
                    Text(quotaLine).font(.caption)
                }
                Section("About") {
                    Text("NotebookLM Clone for iOS · v1.0").font(.caption)
                    Text("Grounded chat · citations · 9 studio tools · offline media playback")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .task {
                server = api.baseURLString
                await loadQuotas()
            }
        }
    }

    private var quotaLine: String {
        guard let q = quotas else { return "—" }
        return "💬 \(q.chats?.used ?? 0)/\(q.chats?.limit ?? 0) · ✨ \(q.studio?.used ?? 0)/\(q.studio?.limit ?? 0) · 🔎 \(q.research?.used ?? 0)/\(q.research?.limit ?? 0)"
    }

    private func loadQuotas() async {
        do { quotas = try await api.get("/api/quotas") } catch { quotas = nil }
    }

    private func doAuth(register: Bool) async {
        busy = true
        defer { busy = false }
        do {
            if register { try await api.register(username: username, password: password) }
            else { try await api.login(username: username, password: password) }
            error = ""
        } catch {
            error = error.localizedDescription
        }
    }
}
