import SwiftUI

struct ContentView: View {
    var body: some View {
        MachineWebView()
            .ignoresSafeArea()                       // the page lays itself out around the safe areas (viewport-fit=cover)
            .background(Color.black)
            .persistentSystemOverlays(.hidden)       // the home indicator dims while performing
            .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
    }
}

#Preview {
    ContentView()
}
