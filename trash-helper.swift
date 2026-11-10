import Foundation
import Darwin

// The helper uses macOS's supported Trash API, without enumerating ~/.Trash.
// File identities are checked again inside this process before an operation.
func fail(_ text: String) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: ["error": text])
    FileHandle.standardOutput.write(data)
    exit(1)
}

let args = CommandLine.arguments
guard args.count >= 5 else { fail("系统接口参数不完整") }
let operation = args[1]
let source = URL(fileURLWithPath: args[2])
guard let inode = UInt64(args[3]), let device = Int64(args[4]) else { fail("文件标识不正确") }
var info = stat()
guard lstat(source.path, &info) == 0 else { fail("无法访问文件，可能需要在系统设置中允许文件访问") }
guard UInt64(info.st_ino) == inode && Int64(info.st_dev) == device else { fail("文件已发生变化，停止操作") }
guard (info.st_mode & S_IFMT) != S_IFLNK else { fail("不处理符号链接") }
do {
    if operation == "trash" {
        var destination: NSURL?
        try FileManager.default.trashItem(at: source, resultingItemURL: &destination)
        guard let path = destination?.path else { fail("系统未返回废纸篓路径，请在 Finder 中检查") }
        let data = try JSONSerialization.data(withJSONObject: ["destination": path])
        FileHandle.standardOutput.write(data)
    } else if operation == "restore" {
        guard args.count == 6 else { fail("缺少恢复位置") }
        let destination = URL(fileURLWithPath: args[5])
        // renameatx_np is atomic and refuses to replace an existing destination.
        guard renameatx_np(AT_FDCWD, source.path, AT_FDCWD, destination.path, UInt32(RENAME_EXCL)) == 0 else {
            fail(errno == EEXIST ? "原位置已有同名文件，未覆盖" : "恢复失败：" + String(cString: strerror(errno)))
        }
        FileHandle.standardOutput.write(Data("{\"restored\":true}".utf8))
    } else {
        fail("不支持的操作")
    }
} catch {
    fail(error.localizedDescription)
}
