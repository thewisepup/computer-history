// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "CaptureAgent",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "computer-history-agent", targets: ["computer-history-agent"]),
    ],
    targets: [
        .target(name: "CaptureAgent"),
        .executableTarget(name: "computer-history-agent", dependencies: ["CaptureAgent"]),
        .testTarget(name: "CaptureAgentTests", dependencies: ["CaptureAgent"]),
    ]
)
