import SwiftUI

struct ContentView: View {
    @Environment(APIClient.self) var api
    @State private var gate = 0 // 0 checking, 1 needsServer, 2 needsLogin, 3 ready

    var body: some View {
        Group {
            if gate == 3 { NotebookListView() }
            else if gate == 2 { LoginView() }
            else if gate == 1 { SettingsView() }
            else { ProgressView("Connecting…") }
        }
        .task { await refresh() }
        .onChange(of: api.me?.username) { _, _ in Task { await refresh() } }
        .onChange(of: api.baseURLString) { _, _ in Task { await refresh() } }
    }

    private func refresh() async {
        if api.baseURLString.isEmpty { gate = 1; return }
        await api.bootstrap()
        if !api.serverReachable { gate = 1; return }
        if api.authRequired && api.me == nil { gate = 2; return }
        gate = 3
    }
}

struct LoginView: View {
    @Environment(APIClient.self) var api
    @State private var username = ""
    @State private var password = ""
    @State private var error = ""
    @State private var busy = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Team login") {
                    TextField("Username", text: $username)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("Password", text: $password)
                }
                if !error.isEmpty { Text(error).foregroundStyle(.red) }
                Button("Log in") { Task { await doAuth(register: false) } }.disabled(busy)
                Button("Register") { Task { await doAuth(register: true) } }.disabled(busy)
                Section {
                    Button("Change server") { api.saveServer("") }
                }
                if busy { ProgressView() }
            }
            .navigationTitle("NBClone")
        }
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
