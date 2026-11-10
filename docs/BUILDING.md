# 运行与构建

## 开发环境

- macOS：文件操作依赖 macOS 原生接口。
- Python 3.10+ 可运行源码；打包环境使用 python.org 的 universal2 Python 3.14。
- Apple Command Line Tools：提供 Swift 编译器、`lipo`、签名和图标工具。
- Node.js 18+：仅运行前端回归测试，App 使用者不需要安装。

在终端运行 `xcode-select --install` 安装命令行工具。完整打包时请确认 Python 框架本身同时包含 arm64 与 x86_64；单架构 Python 无法打出本项目要求的通用版。

## 源码浏览器模式

在仓库根目录执行：

```sh
mkdir -p bin
xcrun swiftc -O trash-helper.swift -o bin/space-lens-trash
xcrun swiftc -O native/AppPresentation.swift -framework AppKit -o bin/space-lens-app-info
python3 server.py
```

helper 在本机编译，不提交预编译二进制。未编译时仍可阅读部分列表，但废纸篓接口不可用，图标会回退为通用图标。

后端默认使用本地端口 8769，冲突时自动分配端口。控制台输出带本次会话令牌的地址，不能向他人转发。源码调试状态保存在被 Git 忽略的 `.state/`。

关闭普通浏览器标签页不会退出源码后端，请使用页面的退出按钮；原生 App 的关闭行为不同，会退出 App 及其本机服务。

## 完整通用 App

```sh
python3 -m venv .build/venv
.build/venv/bin/python -m pip install -r packaging/build-requirements.txt
.build/venv/bin/python packaging/build_app.py
```

脚本会编译两种架构的 Swift 组件，使用 PyInstaller 打包后端，生成图标、隐私用途说明和第三方许可文件，进行本地签名，并逐个检查 Mach-O 文件是否包含两种架构。

产物：

```text
dist/空间磁盘管家.app
dist/空间磁盘管家-1.1.2-universal.zip
dist/build-report.json
```

`.state/`、用户清理记录、AI 配置和本机权限确认不会进入安装包。`.build/` 和 `dist/` 都不提交到源码仓库。

## 签名和权限

当前构建使用 ad-hoc 签名，不包含 Developer ID 公证。公开发行前可以接入自己的 Apple Developer 签名身份及公证流程；不要把证书、私钥或公证密码提交到仓库。

本地重新签名、升级或移动 App 后，macOS 可能需要重新核对完全磁盘访问权限。程序不能代替使用者开启系统授权。

## 发布

1. 运行 [回归测试](TESTING.md)。
2. 打包并验证 App 签名和架构。
3. 计算 ZIP 的 SHA-256 校验值。
4. 在 GitHub Release 附加 ZIP、校验文件和版本说明；公开附件使用 `SpaceLens-1.1.2-universal.zip`，内容与本机构建的中文名 ZIP 一致。源码仓库保留源文件，不堆积构建缓存。

版本号分别出现在 `packaging/build_app.py`、`web/index.html` 和说明文档中，发布前保持一致。
