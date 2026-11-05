// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ElichikaMac",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "Elichika", targets: ["ElichikaMac"])],
    targets: [
        .executableTarget(name: "ElichikaMac", path: "App"),
        .testTarget(name: "ElichikaMacTests", dependencies: ["ElichikaMac"], path: "Tests"),
    ]
)
