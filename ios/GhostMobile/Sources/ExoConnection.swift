import Foundation
import Security

struct HipSample: Identifiable {
    let id: Double
    let left: Double
    let right: Double
    let leftSpeed: Double
    let rightSpeed: Double
}

@MainActor
final class ExoConnection: ObservableObject {
    @Published var address: String = UserDefaults.standard.string(forKey: "macAddress") ?? ""
    @Published var token: String = PairingSecret.load()
    @Published private(set) var connected = false
    @Published private(set) var message = "输入 Mac 地址和配对口令"
    @Published private(set) var state = "OFFLINE"
    @Published private(set) var profile = ""
    @Published private(set) var policy = "zero"
    @Published private(set) var body = ""
    @Published private(set) var hertz = 0.0
    @Published private(set) var leftAngle: Double?
    @Published private(set) var rightAngle: Double?
    @Published private(set) var leftSpeed: Double?
    @Published private(set) var rightSpeed: Double?
    @Published private(set) var waistPitch: Double?
    @Published private(set) var waistRoll: Double?
    @Published private(set) var waistAcceleration: Double?
    @Published private(set) var telemetryFresh = false
    @Published private(set) var waistFresh = false
    @Published private(set) var statusFresh = false
    @Published private(set) var samples: [HipSample] = []

    private var socket: URLSessionWebSocketTask?
    private var reader: Task<Void, Never>?
    private var heartbeat: Task<Void, Never>?
    private var freshnessMonitor: Task<Void, Never>?
    private var statusAt: Date?
    private var sampleAt: Date?
    private var waistSampleAt: Date?
    private var activePolicy = false

    init() {
        guard let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String,
              UserDefaults.standard.string(forKey: "bundledPairingBuild") != build,
              let info = Bundle.main.infoDictionary,
              let host = info["DemoPairingHost"] as? String,
              let secret = info["DemoPairingToken"] as? String,
              Self.localAddress(host),
              secret.range(of: "^[A-Za-z0-9_-]{32,128}$", options: .regularExpression) != nil
        else { return }
        address = host
        token = secret
        UserDefaults.standard.set(address, forKey: "macAddress")
        PairingSecret.save(token)
        UserDefaults.standard.set(build, forKey: "bundledPairingBuild")
    }

    func connectIfConfigured() {
        guard socket == nil, Self.localAddress(address), token.count >= 32 else { return }
        connect()
    }

    var ready: Bool {
        connected && body == "real" && state == "ARMED" && hertz >= 50 &&
        statusFresh && telemetryFresh
    }

    var stateText: String {
        if !connected { return message }
        if !statusFresh { return "控制服务状态中断" }
        switch state {
        case "ARMED": return ready ? "真机就绪" : "腿部数据中断"
        case "QUIET": return "安全等待"
        case "LEGS_OFF": return "腿板数据异常"
        case "TRIPPED": return "急停锁存"
        case "RECONN": return "设备重连中"
        default: return "等待设备"
        }
    }

    func connect() {
        disconnect()
        let host = address.trimmingCharacters(in: .whitespacesAndNewlines)
        let pass = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.localAddress(host), pass.count >= 32,
              let url = URL(string: "ws://\(host)/") else {
            message = "请输入局域网 Mac 地址和完整口令"
            return
        }
        UserDefaults.standard.set(host, forKey: "macAddress")
        PairingSecret.save(pass)
        message = "正在配对…"
        let task = URLSession.shared.webSocketTask(with: url)
        socket = task
        task.resume()
        reader = Task { await receiveLoop(task) }
        send(["op": "pair", "token": pass], on: task)
        heartbeat = Task { await heartbeatLoop(task) }
        freshnessMonitor = Task { await freshnessLoop(task) }
    }

    func disconnect() {
        let old = socket
        socket = nil
        reader?.cancel()
        reader = nil
        heartbeat?.cancel()
        heartbeat = nil
        freshnessMonitor?.cancel()
        freshnessMonitor = nil
        if activePolicy, let old {
            send(["op": "zero"], on: old)
        }
        old?.cancel(with: .normalClosure, reason: nil)
        clearReading("未连接")
    }

    func select(_ mode: String) {
        guard ready, mode == "resist" || mode == "assist" else { return }
        let gain = mode == "resist" ? 0.3 : 0.2
        let limit = mode == "resist" ? 1.5 : 0.8
        send(["op": "policy", "policy": mode, "gain": gain, "max": limit])
        activePolicy = true
    }

    func zero() {
        send(["op": "zero"])
        activePolicy = false
        policy = "zero"
    }

    func emergencyStop() {
        send(["op": "estop"])
        activePolicy = false
    }

    private func receiveLoop(_ task: URLSessionWebSocketTask) async {
        do {
            while !Task.isCancelled {
                let frame = try await task.receive()
                guard socket === task else { return }
                let text: String
                switch frame {
                case .string(let value): text = value
                case .data(let value): text = String(decoding: value, as: UTF8.self)
                @unknown default: continue
                }
                guard let data = text.data(using: .utf8),
                      let item = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let kind = item["k"] as? String else { continue }
                switch kind {
                case "paired":
                    connected = true
                    message = "已配对，等待真机数据"
                case "st":
                    state = item["state"] as? String ?? "OFFLINE"
                    body = item["body"] as? String ?? ""
                    profile = item["profile"] as? String ?? ""
                    policy = item["policy"] as? String ?? "zero"
                    hertz = item["hz"] as? Double ?? 0
                    statusAt = Date()
                    statusFresh = true
                    if body != "real" {
                        clearTelemetry()
                    } else if state == "LEGS_OFF" || state == "RECONN" || state == "OFFLINE" {
                        clearLegTelemetry()
                    }
                    if state != "ARMED" || body != "real" || hertz < 50 {
                        stopActivePolicy()
                    }
                case "s":
                    guard body == "real", let values = item["v"] as? [Any], values.count >= 16,
                          let left = values[0] as? Double,
                          let right = values[1] as? Double,
                          let leftSpeed = values[2] as? Double,
                          let rightSpeed = values[3] as? Double,
                          let pitch = values[7] as? Double,
                          let roll = values[8] as? Double,
                          let ax = values[13] as? Double,
                          let ay = values[14] as? Double,
                          let az = values[15] as? Double,
                          let moment = item["t"] as? Double else { continue }
                    let numbers = [left, right, leftSpeed, rightSpeed, pitch, roll, ax, ay, az, moment]
                    guard numbers.allSatisfy(\.isFinite) else { continue }
                    waistPitch = pitch
                    waistRoll = roll
                    waistAcceleration = (ax * ax + ay * ay + az * az).squareRoot()
                    waistSampleAt = Date()
                    waistFresh = true
                    guard state != "LEGS_OFF" && state != "RECONN" && state != "OFFLINE" else { continue }
                    guard samples.last.map({ moment >= $0.id }) ?? true else { continue }
                    leftAngle = left
                    rightAngle = right
                    self.leftSpeed = leftSpeed
                    self.rightSpeed = rightSpeed
                    sampleAt = Date()
                    telemetryFresh = true
                    samples.append(HipSample(id: moment, left: left, right: right,
                                             leftSpeed: leftSpeed, rightSpeed: rightSpeed))
                    samples.removeAll { moment - $0.id > 10 }
                    if samples.count > 600 { samples.removeFirst(samples.count - 600) }
                default: break
                }
            }
        } catch {
            if socket === task {
                socket = nil
                heartbeat?.cancel()
                freshnessMonitor?.cancel()
                clearReading(connected ? "连接断开，设备将回到松劲" : "配对失败或连接断开")
            }
        }
    }

    private func heartbeatLoop(_ task: URLSessionWebSocketTask) async {
        while !Task.isCancelled, socket === task {
            try? await Task.sleep(nanoseconds: 500_000_000)
            guard socket === task else { return }
            if activePolicy {
                if ready { send(["op": "heartbeat"], on: task) }
                else { stopActivePolicy() }
            }
        }
    }

    private func freshnessLoop(_ task: URLSessionWebSocketTask) async {
        while !Task.isCancelled, socket === task {
            try? await Task.sleep(nanoseconds: 250_000_000)
            guard socket === task else { return }
            let now = Date()
            let hasStatus = statusAt.map { now.timeIntervalSince($0) < 2 } == true
            let hasLegs = sampleAt.map { now.timeIntervalSince($0) < 1 } == true
            let hasWaist = waistSampleAt.map { now.timeIntervalSince($0) < 1 } == true
            if statusFresh != hasStatus { statusFresh = hasStatus }
            if waistFresh != hasWaist {
                waistFresh = hasWaist
                if !hasWaist { clearWaistTelemetry() }
            }
            if telemetryFresh != hasLegs {
                telemetryFresh = hasLegs
                if !hasLegs { clearLegTelemetry() }
            }
            if !hasStatus || !hasLegs { stopActivePolicy() }
        }
    }

    private func stopActivePolicy() {
        guard activePolicy else { return }
        send(["op": "zero"])
        activePolicy = false
    }

    private func clearReading(_ notice: String) {
        connected = false
        message = notice
        state = "OFFLINE"
        profile = ""
        policy = "zero"
        body = ""
        hertz = 0
        statusFresh = false
        clearTelemetry()
        activePolicy = false
        statusAt = nil
        sampleAt = nil
    }

    private func clearLegTelemetry() {
        leftAngle = nil
        rightAngle = nil
        leftSpeed = nil
        rightSpeed = nil
        samples = []
        sampleAt = nil
        telemetryFresh = false
    }

    private func clearTelemetry() {
        clearLegTelemetry()
        clearWaistTelemetry()
    }

    private func clearWaistTelemetry() {
        waistPitch = nil
        waistRoll = nil
        waistAcceleration = nil
        waistSampleAt = nil
        waistFresh = false
    }

    private func send(_ payload: [String: Any], on task: URLSessionWebSocketTask? = nil) {
        guard let target = task ?? socket,
              let data = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: data, encoding: .utf8) else { return }
        Task { try? await target.send(.string(text)) }
    }

    private static func localAddress(_ input: String) -> Bool {
        let parts = input.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2, let port = Int(parts[1]), 1...65535 ~= port else { return false }
        let octets = parts[0].split(separator: ".", omittingEmptySubsequences: false)
        let bytes = octets.compactMap { UInt8($0) }
        guard octets.count == 4, bytes.count == 4 else { return false }
        return bytes[0] == 10 || (bytes[0] == 192 && bytes[1] == 168) ||
            (bytes[0] == 172 && 16...31 ~= bytes[1]) || bytes[0] == 127
    }
}

private enum PairingSecret {
    private static let service = "com.owenzhao.exoghost.mobile.pairing"

    static func load() -> String {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var found: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &found) == errSecSuccess,
              let data = found as? Data else { return "" }
        return String(decoding: data, as: UTF8.self)
    }

    static func save(_ token: String) {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service]
        let data = Data(token.utf8)
        let update: [String: Any] = [kSecValueData as String: data,
                                     kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        if SecItemUpdate(query as CFDictionary, update as CFDictionary) != errSecSuccess {
            let item = query.merging(update) { _, new in new }
            SecItemAdd(item as CFDictionary, nil)
        }
    }
}
