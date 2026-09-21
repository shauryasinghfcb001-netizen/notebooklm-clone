import SwiftUI

@main
struct NotebookLMCloneApp: App {
    @State private var api = APIClient()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(api)
        }
    }
}
