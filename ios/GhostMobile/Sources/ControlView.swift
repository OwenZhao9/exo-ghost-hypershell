import SwiftUI

private enum Palette {
    static let background = Color(red: 0.055, green: 0.075, blue: 0.061)
    static let card = Color(red: 0.115, green: 0.145, blue: 0.119)
    static let lime = Color(red: 0.78, green: 0.94, blue: 0.36)
    static let blue = Color(red: 0.40, green: 0.70, blue: 1.0)
    static let pink = Color(red: 1.0, green: 0.48, blue: 0.71)
}

struct ControlView: View {
    @ObservedObject var connection: ExoConnection
    @State private var showEstopConfirm = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header
                pairing
                device
                curves
                controls
                Text("手机与 Mac 需连接同一局域网。角度曲线只显示外骨骼传来的数据；设备断开时会清空。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 18)
            .padding(.top, 16)
            .padding(.bottom, 30)
        }
        .background(Palette.background.ignoresSafeArea())
        .preferredColorScheme(.dark)
        .safeAreaInset(edge: .bottom) {
            Button(role: .destructive) { showEstopConfirm = true } label: {
                Label("急停", systemImage: "stop.circle.fill")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .frame(height: 52)
            }
            .buttonStyle(.borderedProminent)
            .tint(.red)
            .disabled(!connection.connected)
            .padding(.horizontal, 18)
            .padding(.vertical, 8)
            .background(.ultraThinMaterial)
        }
        .confirmationDialog("确认急停外骨骼？", isPresented: $showEstopConfirm, titleVisibility: .visible) {
            Button("立即急停", role: .destructive) { connection.emergencyStop() }
            Button("取消", role: .cancel) { }
        } message: {
            Text("急停后只能在 Mac 端确认现场安全并重新武装。")
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("GHOST  /  EXO")
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .tracking(3)
                .foregroundStyle(Palette.lime)
            Text("外骨骼控制")
                .font(.system(size: 31, weight: .bold, design: .rounded))
        }
    }

    private var pairing: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("连接 Mac", symbol: "wifi")
            TextField("Mac 地址，例如 192.168.1.8:8765", text: $connection.address)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.numbersAndPunctuation)
                .textContentType(.URL)
                .textFieldStyle(.roundedBorder)
                .accessibilityIdentifier("mac-address")
            SecureField("配对口令", text: $connection.token)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
                .accessibilityIdentifier("pairing-token")
            Button(connection.connected ? "断开连接" : "连接") {
                if connection.connected { connection.disconnect() }
                else { connection.connect() }
            }
            .buttonStyle(.borderedProminent)
            .tint(Palette.lime)
            .foregroundStyle(Palette.background)
            .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .card()
    }

    private var device: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                sectionTitle("设备状态", symbol: "sensor.tag.radiowaves.forward")
                Spacer()
                Circle().fill(connection.ready ? Palette.lime : .orange)
                    .frame(width: 9, height: 9)
            }
            Text(connection.stateText)
                .font(.title3.bold())
                .foregroundStyle(connection.ready ? Palette.lime : .white)
            if connection.connected {
                Text("\(connection.profile == "wearing" ? "穿戴档" : "桌面档")  ·  \(Int(connection.hertz)) Hz  ·  \(modeName(connection.policy))")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 18) {
                angle("左髋", value: connection.leftAngle, color: Palette.blue)
                angle("右髋", value: connection.rightAngle, color: Palette.pink)
            }
        }
        .card()
    }

    private var curves: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("实时角度", symbol: "waveform.path.ecg")
            Text("左髋  ━    右髋  ━")
                .font(.caption)
                .foregroundStyle(Palette.blue)
            GeometryReader { geometry in
                Canvas { context, size in
                    let mid = size.height / 2
                    var baseline = Path()
                    baseline.move(to: CGPoint(x: 0, y: mid))
                    baseline.addLine(to: CGPoint(x: size.width, y: mid))
                    context.stroke(baseline, with: .color(.white.opacity(0.18)), lineWidth: 1)
                    let points = connection.samples
                    guard points.count > 1 else { return }
                    let minTime = points.first!.id
                    let span = max(1, points.last!.id - minTime)
                    for (color, side) in [(Palette.blue, true), (Palette.pink, false)] {
                        var line = Path()
                        for (index, point) in points.enumerated() {
                            let value = side ? point.left : point.right
                            let x = CGFloat((point.id - minTime) / span) * size.width
                            let y = mid - CGFloat(max(-120, min(120, value)) / 120) * mid
                            if index == 0 { line.move(to: CGPoint(x: x, y: y)) }
                            else { line.addLine(to: CGPoint(x: x, y: y)) }
                        }
                        context.stroke(line, with: .color(color), style: StrokeStyle(lineWidth: 2, lineJoin: .round))
                    }
                }
                .frame(width: geometry.size.width, height: geometry.size.height)
            }
            .frame(height: 150)
            .overlay {
                if connection.samples.isEmpty {
                    Text("等待实时数据")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .card()
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("运动控制", symbol: "figure.walk")
            Text("先确认设备固定、两腿周围无人，再选择动作。")
                .font(.footnote)
                .foregroundStyle(.secondary)
            HStack(spacing: 10) {
                Button("阻尼") { connection.select("resist") }
                    .buttonStyle(.borderedProminent)
                    .tint(Palette.blue)
                    .disabled(!connection.ready)
                Button("轻助力") { connection.select("assist") }
                    .buttonStyle(.borderedProminent)
                    .tint(Palette.lime)
                    .foregroundStyle(Palette.background)
                    .disabled(!connection.ready)
                Button("松劲") { connection.zero() }
                    .buttonStyle(.bordered)
                    .disabled(!connection.connected)
            }
            .frame(maxWidth: .infinity)
        }
        .card()
    }

    private func sectionTitle(_ title: String, symbol: String) -> some View {
        Label(title, systemImage: symbol).font(.headline)
    }

    private func angle(_ title: String, value: Double?, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value.map { String(format: "%.1f°", $0) } ?? "—")
                .font(.system(size: 25, weight: .semibold, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(color)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func modeName(_ mode: String) -> String {
        ["zero": "松劲", "resist": "阻尼", "assist": "轻助力"].first { $0.key == mode }?.value ?? mode
    }
}

private extension View {
    func card() -> some View {
        self.padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.card, in: RoundedRectangle(cornerRadius: 18))
    }
}
