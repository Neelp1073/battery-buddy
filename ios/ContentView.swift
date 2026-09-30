import SwiftUI

struct DeviceInfo: Codable, Identifiable {
    var id: String { device_id }
    let device_id: String
    let device_type: String
    let battery_percent: Int
    let is_charging: Bool
    let updated_at: String
}

struct DevicesResponse: Codable {
    let ok: Bool
    let devices: [DeviceInfo]
}

/// App settings. Edit these before running on your iPhone.
enum AppConfig {
    /// Base URL of the Battery Buddy backend running on your Mac.
    /// Replace YOUR-MAC-IP with the Mac's Wi-Fi IP address, e.g. the address
    /// Flask prints as "Running on http://<ip>:5001", or run
    /// `ipconfig getifaddr en0` on the Mac. Both devices must share a network.
    static let baseURL = "http://YOUR-MAC-IP:5001"

    /// Name this iPhone reports to the backend.
    static let deviceId = "neels-iphone"
}

struct ContentView: View {
    let baseURL = AppConfig.baseURL
    let myDeviceId = AppConfig.deviceId

    @State private var devices: [DeviceInfo] = []
    @State private var status = "Ready"

    var body: some View {
        VStack(spacing: 16) {
            Text("Battery Buddy").font(.title)
            Text(status)
                .font(.footnote)
                .multilineTextAlignment(.center)
                .padding(.horizontal)

            Button("Send iPhone battery") {
                Task { await sendBattery() }
            }
            Button("Refresh devices") {
                Task { await loadDevices() }
            }

            List(devices) { d in
                Text("\(d.device_id) (\(d.device_type)): \(d.battery_percent)%")
            }
        }
        .padding()
        .onAppear {
            UIDevice.current.isBatteryMonitoringEnabled = true
            Task { await loadDevices() }
        }
    }

    func sendBattery() async {
        UIDevice.current.isBatteryMonitoringEnabled = true
        let level = UIDevice.current.batteryLevel
        let percent = level < 0 ? -1 : Int((level * 100).rounded())
        let charging = UIDevice.current.batteryState == .charging
            || UIDevice.current.batteryState == .full

        guard percent >= 0 else {
            status = "Battery unavailable. Use a real iPhone (not Mac/Simulator)."
            return
        }
        guard let url = URL(string: "\(baseURL)/battery") else { return }

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = [
            "device_id": myDeviceId,
            "device_type": "iphone",
            "battery_percent": percent,
            "is_charging": charging
        ]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)

        do {
            let (_, resp) = try await URLSession.shared.data(for: req)
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            status = "Sent iPhone \(percent)% (HTTP \(code))"
            await loadDevices()
        } catch {
            status = "Send failed: \(error.localizedDescription)"
        }
    }

    func loadDevices() async {
        guard let url = URL(string: "\(baseURL)/devices") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let decoded = try JSONDecoder().decode(DevicesResponse.self, from: data)
            devices = decoded.devices
            status = "Loaded \(devices.count) device(s)"
        } catch {
            status = "Load failed: \(error.localizedDescription)"
        }
    }
}

#Preview {
    ContentView()
}
