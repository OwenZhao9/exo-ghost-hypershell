import AVFoundation
import SwiftUI

final class PairingPreview: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }

    var previewLayer: AVCaptureVideoPreviewLayer {
        layer as! AVCaptureVideoPreviewLayer
    }
}

struct PairingScanner: UIViewRepresentable {
    let onScan: (String) -> Void
    let onError: (String) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onScan: onScan, onError: onError)
    }

    func makeUIView(context: Context) -> PairingPreview {
        let view = PairingPreview()
        view.previewLayer.videoGravity = .resizeAspectFill
        view.previewLayer.session = context.coordinator.session
        context.coordinator.start()
        return view
    }

    func updateUIView(_ uiView: PairingPreview, context: Context) { }

    static func dismantleUIView(_ uiView: PairingPreview, coordinator: Coordinator) {
        coordinator.stop()
    }

    final class Coordinator: NSObject, AVCaptureMetadataOutputObjectsDelegate {
        let session = AVCaptureSession()
        private let queue = DispatchQueue(label: "com.owenzhao.exoghost.pairing-camera")
        private let onScan: (String) -> Void
        private let onError: (String) -> Void
        private var stopped = false
        private var didScan = false

        init(onScan: @escaping (String) -> Void, onError: @escaping (String) -> Void) {
            self.onScan = onScan
            self.onError = onError
        }

        func start() {
            switch AVCaptureDevice.authorizationStatus(for: .video) {
            case .authorized:
                configure()
            case .notDetermined:
                AVCaptureDevice.requestAccess(for: .video) { [weak self] allowed in
                    guard let self else { return }
                    if allowed { self.configure() }
                    else { self.fail("请在 iPhone 设置中允许相机访问后重试") }
                }
            default:
                fail("请在 iPhone 设置中允许相机访问后重试")
            }
        }

        private func configure() {
            queue.async { [self] in
                guard !stopped else { return }
                guard let camera = AVCaptureDevice.default(for: .video) else {
                    fail("相机不可用，请手动输入配对信息")
                    return
                }
                do {
                    let input = try AVCaptureDeviceInput(device: camera)
                    let output = AVCaptureMetadataOutput()
                    session.beginConfiguration()
                    guard session.canAddInput(input), session.canAddOutput(output) else {
                        session.commitConfiguration()
                        fail("无法启动扫码，请手动输入配对信息")
                        return
                    }
                    session.addInput(input)
                    session.addOutput(output)
                    output.setMetadataObjectsDelegate(self, queue: .main)
                    output.metadataObjectTypes = [.qr]
                    session.commitConfiguration()
                    session.startRunning()
                } catch {
                    fail("无法启动扫码，请手动输入配对信息")
                }
            }
        }

        func metadataOutput(_ output: AVCaptureMetadataOutput,
                            didOutput metadataObjects: [AVMetadataObject],
                            from connection: AVCaptureConnection) {
            guard !didScan,
                  let code = metadataObjects.compactMap({ $0 as? AVMetadataMachineReadableCodeObject })
                      .first(where: { $0.type == .qr })?.stringValue else { return }
            didScan = true
            onScan(code)
        }

        func stop() {
            queue.async { [self] in
                stopped = true
                if session.isRunning { session.stopRunning() }
            }
        }

        private func fail(_ message: String) {
            DispatchQueue.main.async { self.onError(message) }
        }
    }
}
