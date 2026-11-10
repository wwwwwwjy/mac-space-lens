import Cocoa
let directory = CommandLine.arguments[1]
try FileManager.default.createDirectory(atPath: directory, withIntermediateDirectories: true)
for size in [16, 32, 64, 128, 256, 512, 1024] {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                                  bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                  isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    let d = CGFloat(size)
    NSColor(calibratedRed: 0.12, green: 0.25, blue: 0.20, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: d*0.04, y: d*0.04, width: d*0.92, height: d*0.92), xRadius: d*0.22, yRadius: d*0.22).fill()
    let center = NSPoint(x: d*0.50, y: d*0.53)
    let ring = NSBezierPath()
    ring.appendArc(withCenter: center, radius: d*0.26, startAngle: 0, endAngle: 360)
    ring.lineWidth = d*0.075
    NSColor(calibratedRed: 0.67, green: 0.85, blue: 0.73, alpha: 1).setStroke()
    ring.stroke()
    let accent = NSBezierPath()
    accent.appendArc(withCenter: center, radius: d*0.26, startAngle: 25, endAngle: 110)
    accent.lineWidth = d*0.075
    NSColor(calibratedRed: 0.85, green: 0.68, blue: 0.37, alpha: 1).setStroke()
    accent.stroke()
    let box = NSBezierPath(roundedRect: NSRect(x: d*0.40, y: d*0.43, width: d*0.20, height: d*0.20), xRadius: d*0.045, yRadius: d*0.045)
    NSColor.white.setFill(); box.fill()
    NSGraphicsContext.restoreGraphicsState()
    let data = bitmap.representation(using: .png, properties: [:])!
    for (base, retina) in [(size, false), (size/2, true)] where [16,32,128,256,512].contains(base) {
        let name = "icon_\(base)x\(base)" + (retina ? "@2x" : "") + ".png"
        try data.write(to: URL(fileURLWithPath: directory).appendingPathComponent(name))
    }
}
