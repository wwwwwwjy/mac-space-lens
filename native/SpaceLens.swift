import Cocoa
import WebKit
import Darwin

final class PermissionPage: NSView {
    override var isFlipped: Bool { true }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var webView: WKWebView!
    var process: Process?
    var outputPipe: Pipe?
    var runtime: URL?
    var testData: URL?
    var serviceURL: URL?
    var closing = false
    var launched = false
    var pendingText = Data()
    var startupTimer: Timer?
    var permissionCheck: NSButton?
    var permissionContinue: NSButton?
    var relaunchProcess: Process?
    let permissionSmoke = CommandLine.arguments.contains("--smoke-permission")
    let featureSmoke = CommandLine.arguments.contains("--smoke-features")
    let supportSmoke = CommandLine.arguments.contains("--smoke-coffee")
    let smoke = CommandLine.arguments.contains("--smoke-test") || CommandLine.arguments.contains("--smoke-permission") || CommandLine.arguments.contains("--smoke-features") || CommandLine.arguments.contains("--smoke-coffee")
    let setupRevision = 1

    var permissionRecord: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/SpaceLens/access-setup.json")
    }

    func permissionSetupWasConfirmed() -> Bool {
        guard let data = try? Data(contentsOf: permissionRecord),
              let record = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        return (record["revision"] as? Int) == setupRevision &&
            (record["userConfirmed"] as? Bool) == true &&
            (record["build"] as? String) == (Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String) &&
            (record["appPath"] as? String) == Bundle.main.bundleURL.resolvingSymlinksInPath().path
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if !smoke, let id = Bundle.main.bundleIdentifier,
           let existing = NSRunningApplication.runningApplications(withBundleIdentifier: id).first(where: { $0.processIdentifier != getpid() && !$0.isTerminated }) {
            existing.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
            NSApp.terminate(nil)
            return
        }
        NSApp.setActivationPolicy(.regular)
        makeMenu()
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1220, height: 840), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "空间磁盘管家"
        window.minSize = NSSize(width: 860, height: 620)
        window.center()
        window.delegate = self
        window.isReleasedWhenClosed = false
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.add(self, name: "spaceLens")
        webView = WKWebView(frame: window.contentView!.bounds, configuration: configuration)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if permissionSmoke || (!smoke && !permissionSetupWasConfirmed()) {
            showPermissionSetup()
        } else {
            showMessage("正在启动磁盘管家", "打开后点击“开始扫描”，再读取这台 Mac 的文件占用。")
            startBackend()
        }
    }

    func makeMenu() {
        let main = NSMenu()
        let item = NSMenuItem()
        let app = NSMenu()
        app.addItem(withTitle: "关于空间磁盘管家", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        let access = app.addItem(withTitle: "访问权限设置…", action: #selector(openFullDiskAccess), keyEquivalent: "")
        access.target = self
        app.addItem(NSMenuItem.separator())
        app.addItem(withTitle: "退出空间磁盘管家", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = app
        main.addItem(item)
        let editItem = NSMenuItem(title: "编辑", action: nil, keyEquivalent: "")
        let edit = NSMenu(title: "编辑")
        for (title, selector, key) in [("撤销", "undo:", "z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: NSSelectorFromString(selector), keyEquivalent: key)
        }
        editItem.submenu = edit
        main.addItem(editItem)
        let windowItem = NSMenuItem(title: "窗口", action: nil, keyEquivalent: "")
        let menu = NSMenu(title: "窗口")
        menu.addItem(withTitle: "关闭窗口并退出", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windowItem.submenu = menu
        main.addItem(windowItem)
        NSApp.mainMenu = main
    }

    func showMessage(_ title: String, _ text: String) {
        // Only fixed application strings, never file names or untrusted backend text.
        webView.loadHTMLString("<html><meta charset='UTF-8'><body style='font:16px -apple-system;background:#f6f7f5;color:#24352d;padding:70px'><h2>\(title)</h2><p>\(text)</p></body></html>", baseURL: nil)
    }

    func showPermissionSetup() {
        // No backend, catalogue or directory scan is started before this screen.
        let scroll = NSScrollView(frame: window.contentView!.bounds)
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.drawsBackground = false
        let page = PermissionPage(frame: scroll.bounds)
        page.translatesAutoresizingMaskIntoConstraints = false
        scroll.documentView = page
        page.appearance = NSAppearance(named: .aqua)
        page.wantsLayer = true
        page.layer?.backgroundColor = NSColor(calibratedWhite: 0.965, alpha: 1).cgColor
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 18
        stack.translatesAutoresizingMaskIntoConstraints = false
        page.addSubview(stack)
        NSLayoutConstraint.activate([
            page.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor),
            page.heightAnchor.constraint(greaterThanOrEqualTo: scroll.contentView.heightAnchor),
            stack.centerXAnchor.constraint(equalTo: page.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: page.centerYAnchor),
            stack.widthAnchor.constraint(equalTo: page.widthAnchor, constant: -120),
            page.heightAnchor.constraint(greaterThanOrEqualTo: stack.heightAnchor, constant: 100)
        ])
        let preferredHeight = page.heightAnchor.constraint(equalTo: stack.heightAnchor, constant: 100)
        preferredHeight.priority = .defaultHigh
        preferredHeight.isActive = true
        func label(_ text: String, size: CGFloat = 14, bold: Bool = false) -> NSTextField {
            let field = NSTextField(wrappingLabelWithString: text)
            field.font = bold ? .boldSystemFont(ofSize: size) : .systemFont(ofSize: size)
            field.textColor = NSColor(calibratedRed: 0.16, green: 0.25, blue: 0.20, alpha: 1)
            field.translatesAutoresizingMaskIntoConstraints = false
            stack.addArrangedSubview(field)
            field.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
            return field
        }
        _ = label("先统一设置权限，再开始扫描", size: 28, bold: true)
        _ = label("现在还没有扫描你的文件。请先为这个 App 开启“完全磁盘访问权限”，避免扫描到文稿、桌面、下载等位置时逐项询问。")
        _ = label("1. 打开系统权限设置", size: 16, bold: true)
        let settings = NSButton(title: "打开「完全磁盘访问权限」", target: self, action: #selector(openFullDiskAccess))
        settings.bezelStyle = .rounded
        stack.addArrangedSubview(settings)
        _ = label("2. 开启列表中的「空间磁盘管家」", size: 16, bold: true)
        _ = label("如果列表里没有它，点击「＋」选择下面这个 App，或把 App 拖入列表。请开启整个 App，不要选择它内部的程序文件。")
        let pathLabel = label(Bundle.main.bundleURL.path, size: 12)
        pathLabel.isSelectable = true
        let reveal = NSButton(title: "在 Finder 中显示这个 App", target: self, action: #selector(revealThisApp))
        reveal.bezelStyle = .rounded
        stack.addArrangedSubview(reveal)
        _ = label("3. 完成设置后，重启进入软件", size: 16, bold: true)
        let check = NSButton(checkboxWithTitle: "我已在系统设置中开启此 App 的完全磁盘访问权限", target: self, action: #selector(permissionCheckboxChanged))
        permissionCheck = check
        stack.addArrangedSubview(check)
        let go = NSButton(title: "已完成设置，重启进入软件", target: self, action: #selector(confirmPermissionSetup))
        go.bezelStyle = .rounded
        go.isEnabled = false
        permissionContinue = go
        stack.addArrangedSubview(go)
        _ = label("这个开关必须由你在 macOS 中开启；上面的勾选只是确认已设置，不会代替系统授权。统一授权扩大读取范围，清理文件仍需你选择并确认。", size: 12)
        window.contentView = scroll
        if permissionSmoke {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                page.layoutSubtreeIfNeeded()
                if let bitmap = page.bitmapImageRepForCachingDisplay(in: page.bounds) {
                    page.cacheDisplay(in: page.bounds, to: bitmap)
                    if let png = bitmap.representation(using: .png, properties: [:]) {
                        let preview = FileManager.default.temporaryDirectory.appendingPathComponent("space-lens-permission-preview-" + UUID().uuidString + ".png")
                        try? png.write(to: preview)
                        print("SMOKE_PREVIEW " + preview.path)
                    }
                }
                print("SMOKE_PERMISSION backend_started=\(self.process != nil) checkbox_off=\(check.state == .off) continue_disabled=\(!go.isEnabled)")
                self.window.performClose(nil)
            }
        }
    }

    @objc func openFullDiskAccess() {
        let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")!
        if !NSWorkspace.shared.open(url) {
            let alert = NSAlert()
            alert.messageText = "请打开系统设置"
            alert.informativeText = "进入“隐私与安全性 → 完全磁盘访问权限”，添加并开启“空间磁盘管家”。"
            alert.runModal()
        }
    }

    @objc func revealThisApp() {
        NSWorkspace.shared.activateFileViewerSelecting([Bundle.main.bundleURL])
    }

    @objc func permissionCheckboxChanged() {
        permissionContinue?.isEnabled = permissionCheck?.state == .on
    }

    @objc func confirmPermissionSetup() {
        guard permissionCheck?.state == .on, !smoke else { return }
        do {
            // This records a USER CONFIRMATION, not a fabricated permission test.
            let record: [String: Any] = [
                "revision": setupRevision,
                "build": Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "",
                "appPath": Bundle.main.bundleURL.resolvingSymlinksInPath().path,
                "userConfirmed": true
            ]
            let data = try JSONSerialization.data(withJSONObject: record)
            try FileManager.default.createDirectory(at: permissionRecord.deletingLastPathComponent(),
                                                    withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            try data.write(to: permissionRecord, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: permissionRecord.path)
            guard let executable = Bundle.main.executableURL else { throw NSError(domain: "SpaceLens", code: 2) }
            let next = Process()
            next.executableURL = executable
            next.arguments = ["--wait-for-exit", String(getpid())]
            next.standardInput = FileHandle.nullDevice
            next.standardOutput = FileHandle.nullDevice
            next.standardError = FileHandle.nullDevice
            try next.run()
            relaunchProcess = next
            NSApp.terminate(nil)
        } catch {
            let alert = NSAlert()
            alert.messageText = "请关闭并重新打开 App"
            alert.informativeText = "系统权限需要重新启动应用后生效。若权限引导再次出现，请再次确认设置。"
            alert.runModal()
        }
    }

    func startBackend() {
        do {
            let fm = FileManager.default
            let dir = fm.temporaryDirectory.appendingPathComponent("space-lens-" + UUID().uuidString, isDirectory: true)
            try fm.createDirectory(at: dir, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
            runtime = dir
            var data = fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/SpaceLens", isDirectory: true)
            if smoke {
                data = fm.temporaryDirectory.appendingPathComponent("space-lens-test-data-" + UUID().uuidString, isDirectory: true)
                testData = data
            }
            guard let resources = Bundle.main.resourceURL else { throw NSError(domain: "SpaceLens", code: 1) }
            let executable = resources.appendingPathComponent("backend/space-lens-server")
            let child = Process()
            child.executableURL = executable
            child.currentDirectoryURL = dir
            child.arguments = ["--desktop", "--no-browser", "--port", "0", "--parent-pid", String(getpid())]
            var environment = ProcessInfo.processInfo.environment
            for key in ["PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT", "DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES"] { environment.removeValue(forKey: key) }
            environment["SPACE_LENS_STATE"] = dir.path
            environment["SPACE_LENS_DATA"] = data.path
            child.environment = environment
            let pipe = Pipe()
            outputPipe = pipe
            child.standardOutput = pipe
            child.standardError = FileHandle.nullDevice
            child.standardInput = FileHandle.nullDevice
            pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let bytes = handle.availableData
                if bytes.isEmpty { handle.readabilityHandler = nil; return }
                DispatchQueue.main.async { self?.readOutput(bytes) }
            }
            child.terminationHandler = { [weak self] _ in DispatchQueue.main.async { self?.backendStopped() } }
            process = child
            try child.run()
            startupTimer = Timer.scheduledTimer(withTimeInterval: 35, repeats: false) { [weak self] _ in
                guard let self = self, !self.launched, !self.closing else { return }
                self.showFailure("本地服务启动超时。请关闭应用后重试；确认整个 .app 已完整复制到本机。")
            }
        } catch {
            showFailure("无法启动内置运行环境。请将完整的 App 复制到“应用程序”后重试。")
        }
    }

    func readOutput(_ data: Data) {
        pendingText.append(data)
        guard pendingText.count < 65536 else { return }
        while let range = pendingText.firstRange(of: Data([10])) {
            let line = pendingText.subdata(in: 0..<range.lowerBound)
            pendingText.removeSubrange(0...range.lowerBound)
            guard !closing, !launched,
                  let json = try? JSONSerialization.jsonObject(with: line) as? [String: String],
                  let value = json["ready"], let url = URL(string: value),
                  url.scheme == "http", url.host == "127.0.0.1", url.port != nil, url.fragment != nil else { continue }
            launched = true
            startupTimer?.invalidate()
            serviceURL = url
            webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
        }
    }

    func showFailure(_ message: String) {
        guard !closing else { return }
        let alert = NSAlert()
        alert.messageText = "磁盘管家未能启动"
        alert.informativeText = message
        alert.addButton(withTitle: "关闭")
        alert.runModal()
        NSApp.terminate(nil)
    }

    func backendStopped() {
        outputPipe?.fileHandleForReading.readabilityHandler = nil
        startupTimer?.invalidate()
        cleanup()
        if closing {
            if smoke { print("SMOKE_EXIT backend_stopped=true runtime_removed=true") }
            NSApp.reply(toApplicationShouldTerminate: true)
        } else if smoke {
            fputs("SMOKE_FAILED backend stopped unexpectedly\n", stderr)
            NSApp.terminate(nil)
        } else {
            showFailure("本地服务已经退出。重新打开 App 可以重新扫描，文件清理记录会保留。")
        }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if closing { return .terminateLater }
        closing = true
        startupTimer?.invalidate()
        guard let child = process, child.isRunning else { cleanup(); return .terminateNow }
        // SIGTERM requests cooperative cancellation, not abrupt process termination.
        // The backend finishes any file operation before releasing its listener.
        if window.contentView === webView {
            showMessage("正在退出", "扫描会立即停止；若正在处理文件，将在本次操作结束后自动退出。")
        }
        child.terminate()
        return .terminateLater
    }

    func cleanup() {
        if let dir = runtime { try? FileManager.default.removeItem(at: dir) }
        if let dir = testData { try? FileManager.default.removeItem(at: dir) }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        NSApp.terminate(nil)
        return false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !closing { window?.makeKeyAndOrderFront(nil) }
        return true
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let url = message.frameInfo.request.url,
              url.host == "127.0.0.1", url.port == serviceURL?.port else { return }
        guard let command = message.body as? String else { return }
        switch command {
        case "quit": NSApp.terminate(nil)
        case "permissions": openFullDiskAccess()
        case "project":
            if let project = URL(string: "https://github.com/wwwwwwjy/mac-space-lens") { NSWorkspace.shared.open(project) }
        default: break
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.absoluteString == "about:blank" || (url.scheme == "http" && url.host == "127.0.0.1" && url.port == serviceURL?.port) {
            decisionHandler(.allow)
        } else {
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard smoke, !closing, webView.url?.host == "127.0.0.1" else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [weak self] in
            guard let self = self, !self.closing else { return }
            if self.supportSmoke {
                self.checkSupportInterface()
                return
            }
            if self.featureSmoke {
                self.checkFeatureInterface()
                return
            }
            self.webView.evaluateJavaScript("document.title + '|' + document.getElementById('scan-status').textContent + '|' + document.getElementById('ai-settings-open').textContent") { result, error in
                if error != nil { fputs("SMOKE_FAILED web render\n", stderr) }
                else { print("SMOKE_READY " + String(describing: result ?? "")) }
                self.window.performClose(nil)
            }
        }
    }

    func snapshotFeature(_ name: String, next: @escaping () -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            self.webView.takeSnapshot(with: nil) { image, error in
                if let data = image?.tiffRepresentation, let bitmap = NSBitmapImageRep(data: data),
                   let png = bitmap.representation(using: .png, properties: [:]) {
                    let url = FileManager.default.temporaryDirectory.appendingPathComponent("space-lens-\(name)-\(UUID().uuidString).png")
                    try? png.write(to: url)
                    print("SMOKE_PREVIEW " + url.path)
                } else {
                    fputs("SMOKE_FAILED feature snapshot\n", stderr)
                }
                next()
            }
        }
    }

    func checkSupportInterface() {
        let initial = """
        if(document.getElementById('coffee-alipay').hasAttribute('src')||document.getElementById('coffee-wechat').hasAttribute('src'))throw Error('Eager receipt load');
        await view('settings');
        const status=await api('status');if(status.scan.running||status.scan.started)throw Error('Unexpected scan');
        document.getElementById('author-support').scrollIntoView({block:'end'});
        return {settings:!document.getElementById('settings-section').hidden,receipt_open:document.getElementById('coffee-dialog').open,scan_started:status.scan.started};
        """
        webView.callAsyncJavaScript(initial, arguments: [:], in: nil, in: .page) { result in
            print("SMOKE_SETTINGS " + String(describing: result))
            self.snapshotFeature("settings") {
                let open = """
                document.getElementById('coffee-open').onclick();
                const images=[document.getElementById('coffee-alipay'),document.getElementById('coffee-wechat')];
                await Promise.all(images.map(x=>x.decode()));
                const boxes=images.map(x=>x.getBoundingClientRect());
                if(images.some(x=>x.naturalWidth!==640||x.naturalHeight!==640))throw Error('Receipt dimensions');
                if(Math.abs(boxes[0].width-boxes[1].width)>0.1||Math.abs(boxes[0].height-boxes[1].height)>0.1||boxes.some(b=>Math.abs(b.width-b.height)>0.1))throw Error('Unequal visual size or stretched receipt');
                if(document.querySelectorAll('#coffee-dialog input,#coffee-dialog select,#coffee-dialog textarea').length)throw Error('Editable payment settings');
                return {loaded:images.length,width:boxes[0].width,height:boxes[0].height,editable:false};
                """
                self.webView.callAsyncJavaScript(open, arguments: [:], in: nil, in: .page) { result in
                    print("SMOKE_COFFEE " + String(describing: result))
                    self.snapshotFeature("coffee") {
                        self.webView.evaluateJavaScript("document.getElementById('coffee-close').onclick()") { _, _ in self.window.performClose(nil) }
                    }
                }
            }
        }
    }

    func checkFeatureInterface() {
        // Read installed bundle metadata; do not scan personal folders or mutate apps.
        webView.callAsyncJavaScript("const before=await api('status'); if(before.scan.running||before.scan.started)throw Error('Unexpected startup scan'); await view('applications'); if(appState.entries.length)throw Error('Unexpected application scan'); await loadApplications(true); const after=await api('status'); if(after.scan.running||after.scan.started)throw Error('Application scan started disk scan'); return {apps:appState.entries.length,icons:document.querySelectorAll('img.app-icon').length,disk_scan_started:after.scan.started};", arguments: [:], in: nil, in: .page) { result in
            print("SMOKE_APPLICATIONS " + String(describing: result))
            self.snapshotFeature("applications") {
                let fixture = """
                appState.target = {id:'fixture',name:'示例剪辑软件',identifier:'org.example.editor',needs_confirmation:false};
                appState.rows = [
                  {id:'fixture-cache',explain_id:'fixture-explain',name:'org.example.editor',path:'~/Library/Caches/org.example.editor',kind:'缓存',bytes:123000000,deletable:true,risk:'caution',basis:'路径完整匹配应用标识 org.example.editor',advice:'核对后可勾选移入废纸篓。',impact:'重新安装后需要重新下载。'},
                  {id:'fixture-named',explain_id:'fixture-named-explain',name:'示例剪辑软件',path:'~/Library/Application Support/示例剪辑软件',kind:'应用支持数据',bytes:350000000,deletable:true,risk:'caution',needs_ownership_confirmation:true,basis:'目录名与该软件的完整名称一致；清理前还需你确认归属',advice:'可以勾选；确认窗口中需额外确认这个同名目录只属于已卸载软件。',impact:'可能包含本地草稿、资料和设置。清理后需要重新导入或恢复备份。'},
                  {id:null,explain_id:'fixture-shared',name:'Shared',path:'~/Library/Group Containers/Shared',kind:'共享数据',bytes:456000000,deletable:false,risk:'protected',basis:'仅名称相关，归属不足以确定',advice:'共享目录只读；请使用官方卸载器核对。',impact:'可能影响其他应用的资料。',blocked:'共享目录'}
                ];
                document.getElementById('app-list').innerHTML='';
                document.getElementById('residual-panel').hidden=false;
                document.getElementById('residual-title').textContent='示例剪辑软件 · 残留核对（界面测试）';
                document.getElementById('residual-identity').textContent='org.example.editor';
                document.getElementById('residual-notice').textContent='可全选残留后核对清理。同名目录在确认窗口核对归属。';
                renderResiduals(); window.scrollTo(0,0);
                return appState.selected.size;
                """
                self.webView.callAsyncJavaScript(fixture, arguments: [:], in: nil, in: .page) { result in
                    print("SMOKE_RESIDUAL_SELECTION " + String(describing: result))
                    self.snapshotFeature("residuals") {
                        self.webView.callAsyncJavaScript("await document.getElementById('ai-settings-open').onclick(); return document.getElementById('ai-services').children.length;", arguments: [:], in: nil, in: .page) { result in
                            print("SMOKE_AI_DISCOVERY " + String(describing: result))
                            self.snapshotFeature("ai") { self.window.performClose(nil) }
                        }
                    }
                }
            }
        }
    }
}

// Relaunch only after the old window/process is gone, without a shell or login item.
if let index = CommandLine.arguments.firstIndex(of: "--wait-for-exit"),
   CommandLine.arguments.count > index + 1, let oldPID = Int32(CommandLine.arguments[index + 1]),
   oldPID > 1, oldPID != getpid() {
    for _ in 0..<200 {
        if kill(oldPID, 0) != 0 { break }
        usleep(50_000)
    }
    if kill(oldPID, 0) == 0 { exit(1) }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.run()
