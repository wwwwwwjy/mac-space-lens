import AppKit
import Foundation
import Darwin

// This read-only helper must not outlive the application if an icon service stalls.
let ownerPID = getppid()
let ownerWatch = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
ownerWatch.schedule(deadline: .now() + .milliseconds(500), repeating: .milliseconds(500))
ownerWatch.setEventHandler { if getppid() != ownerPID { _exit(0) } }
ownerWatch.resume()

// Read Finder's presentation of known app bundles. Never launch the application.
func describeApp(_ path: String) -> [String: String]? {
    guard path.hasPrefix("/"), path.lowercased().hasSuffix(".app"),
          FileManager.default.fileExists(atPath: path) else { return nil }
    var name = FileManager.default.displayName(atPath: path)
    if name.lowercased().hasSuffix(".app") { name.removeLast(4) }
    if name.isEmpty { name = URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent }
    var row = ["path": path, "name": name]
    let dimension = 96
    guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: dimension, pixelsHigh: dimension,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
        let context = NSGraphicsContext(bitmapImageRep: bitmap) else { return row }
    let icon = NSWorkspace.shared.icon(forFile: path)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    icon.draw(in: NSRect(x: 0, y: 0, width: dimension, height: dimension), from: .zero,
              operation: .copy, fraction: 1, respectFlipped: false, hints: nil)
    context.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()
    if let png = bitmap.representation(using: .png, properties: [:]) {
        row["icon"] = "data:image/png;base64," + png.base64EncodedString()
    }
    return row
}

let raw = FileHandle.standardInput.readDataToEndOfFile()
guard raw.count <= 2_000_000,
      let paths = try? JSONDecoder().decode([String].self, from: raw), paths.count <= 2000 else { exit(2) }
var result = [[String: String]]()
for path in paths {
    autoreleasepool {
        if let item = describeApp(path) { result.append(item) }
    }
}
if let encoded = try? JSONSerialization.data(withJSONObject: result) {
    FileHandle.standardOutput.write(encoded)
}
