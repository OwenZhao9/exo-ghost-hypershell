import SwiftUI

@main
struct GhostMobileApp: App {
    @StateObject private var connection = ExoConnection()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ControlView(connection: connection)
                .task { connection.connectIfConfigured() }
                .onChange(of: scenePhase) { phase in
                    if phase != .active {
                        connection.disconnect()
                    } else {
                        connection.connectIfConfigured()
                    }
                }
        }
    }
}
