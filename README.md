# 空间磁盘管家 · Space Lens

一款用中文说明“文件是什么、能不能清理、删后有什么影响”的 macOS 本地空间管理工具。

支持磁盘占用分析、软件卸载、卸载残留核对，以及可选的本地 AI 解释。默认等待用户点击开始扫描；所有清理均需手动选择并确认。

**当前版本：1.1.2 · macOS 12+ · Apple Silicon / Intel 通用版**

## 下载与安装

在本仓库的 [Releases](https://github.com/wwwwwwjy/mac-space-lens/releases) 下载 `SpaceLens-1.1.2-universal.zip`，解压后将完整 `.app` 拖入“应用程序”。正式 App 内置 Python 运行环境，不需要另外安装 Python、Node.js 或浏览器扩展。

当前安装包为本地 ad-hoc 签名，尚未获得 Apple Developer ID 公证。通过网络下载后，macOS 可能要求在“系统设置 → 隐私与安全性”中确认允许打开。请核对下载来源及发布页的 SHA-256 校验值。

首次启动会显示统一访问权限引导。需要扫描受保护位置时，在 macOS 的“完全磁盘访问权限”中添加并开启整个 App，然后按提示重新启动。权限开关由使用者亲自确认。

完整步骤见 [使用说明](使用说明.md)。

## 主要功能

| 功能 | 使用方式 |
| --- | --- |
| 空间概览 | 手动扫描，按目录查看磁盘占用，逐层寻找大文件 |
| 通俗用途说明 | 显示文件类型、常见内容、清理建议和删除影响 |
| 批量清理 | 全选当前列表、移入废纸篓，或单独确认永久删除 |
| 软件卸载 | 只扫描应用目录，显示 macOS 提供的真实名称和图标；确认软件名称后卸载 |
| 卸载残留 | 按应用标识和专属目录查找，展示归属依据，手动选择后清理 |
| 同名目录核对 | 允许勾选，清理前需要额外确认它只属于已卸载的软件 |
| 清理记录与撤回 | 保存移入废纸篓的记录，可在原位置没有冲突时撤回 |
| 可选本地 AI | 检测 Ollama / LM Studio，关联本机模型辅助解释和检索建议 |

离线规则覆盖剪映 / CapCut、达芬奇、Steam、微信、照片资料库、虚拟机、开发依赖和本地 AI 模型等常见目录。规则只能辅助判断，不能证明工程已经不再引用某个文件。

## 推荐使用流程

1. 打开 App，点击“开始扫描”。软件卸载页的扫描只读取应用目录。
2. 查看用途、完整路径和清理影响；对重要工程、草稿、存档先备份。
3. 勾选需要处理的内容，在确认窗口核对后执行。
4. 操作完成后原地显示结果，不跳转到恢复页面。
5. 优先使用“移入废纸篓”，确认工作正常后再自行清空废纸篓。

卸载软件会先移除本体，再自动检索该软件的残留。残留不会随本体一并自动删除，需要另行勾选确认。

## 本地运行与隐私

- 文件检索主要读取路径、大小、时间、应用公开元数据等信息，不读取个人文档正文进行分类。
- 后端仅监听本机回环地址，使用会话令牌并检查请求来源；不提供局域网访问服务。
- AI 默认不启用。手动请求 AI 解释时，只向本机模型服务发送所选项目的元数据和已有说明，不发送文件正文；主目录替换为 `~`。
- 检测到 ChatGPT、Codex、豆包、DeepSeek 或 Claude 客户端，不代表可以调用其中的模型。当前可关联的是 Ollama / LM Studio 的本地接口。
- 关闭 App 窗口会停止本应用后端、释放监听端口并清理会话临时目录；正在进行的文件操作结束后才退出。
- 为支持撤回，清理记录、应用身份记录、AI 设置和权限确认保存在 `~/Library/Application Support/SpaceLens/`。

更多细节见 [架构与数据流](docs/ARCHITECTURE.md)。

## 清理边界

永久删除不能撤回。移入废纸篓也不会立即释放全部空间，清空后才会释放相应占用。

系统文件、凭据、其他用户、共享数据、云盘数据和仍被其他已安装软件使用的目录有额外保护。后台驱动、系统扩展或特权组件应使用厂商卸载器。工具不使用 `sudo`，不声称能保证任何应用都“零残留”。

APFS 克隆、快照、稀疏文件和权限限制会影响占用统计，因此列表大小不等于保证可释放的空间。

## 从源码运行和构建

源码后端使用 Python 标准库，界面使用原生 HTML / CSS / JavaScript，App 外壳及系统接口使用 Swift。

```sh
# 源码浏览器调试入口，需要本机 Python 3.10+
python3 server.py
```

源码模式的废纸篓接口和真实图标需要先编译 Swift helper；完整 `.app` 打包需要 macOS、Apple Command Line Tools，以及 **universal2 Python 3.14**。

```sh
python3 -m venv .build/venv
.build/venv/bin/python -m pip install -r packaging/build-requirements.txt
.build/venv/bin/python packaging/build_app.py
```

详细步骤、签名限制及产物说明见 [构建指南](docs/BUILDING.md)。

## 测试

```sh
python3 -m unittest discover -s tests -v
node tests/test_frontend.cjs
node tests/test_app_frontend.cjs
```

文件移动与删除测试在 macOS 上运行，使用测试专属临时目录。不要用个人资料代替测试样本。

1.1.2 已在 macOS 15.7.5 / M2 Pro 上验证 42 项 Python 测试、两组前端测试，以及打包后的 arm64 / x86_64（Rosetta）运行和退出清理。Intel 实机、其他系统版本及真实模型推理仍需要对应环境验证。见 [测试说明](docs/TESTING.md)。

## 目录结构

```text
native/                 Swift App 外壳、图标读取与应用图标生成
web/                    中文界面
tests/                  后端与前端回归测试
packaging/              通用 App 构建与打包验证脚本
docs/                   构建、架构与测试资料
server.py               本机 HTTP API
storage.py              文件元数据扫描与索引
descriptions.py         离线用途和影响说明
actions.py              确认、废纸篓、永久删除及撤回
app_management.py       软件身份、卸载与残留核对
application_catalog.py  应用元数据识别
app_presentation.py     真实软件名称与图标
local_ai.py             本地 AI 服务检测与解释
trash-helper.swift      macOS 原生废纸篓接口
```

## 反馈与贡献

欢迎通过 Issues 描述问题，提交时请提供系统版本、App 版本、操作步骤及脱敏后的错误信息。请勿上传带个人路径、文件清单、账号信息或会话令牌的扫描库和日志。

修改方式见 [贡献说明](CONTRIBUTING.md)，版本变化见 [更新记录](CHANGELOG.md)。本仓库目前未指定开源许可证；公开代码不代表已经授予额外的软件使用或再分发许可。
