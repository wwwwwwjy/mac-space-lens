# 测试说明

## 回归测试

在 macOS、仓库根目录运行：

```sh
python3 -m unittest discover -s tests -v
node tests/test_frontend.cjs
node tests/test_app_frontend.cjs
node tests/test_settings_frontend.cjs
```

Python 测试使用标准库，不要求安装模型或启用完全磁盘访问权限。文件操作测试只在自己创建的临时用户目录中运行，模拟数据与实际用户资料隔离；不操作现有应用。

主要覆盖：

- 手动开始扫描、符号链接和跨设备边界、文件变更检测。
- 废纸篓与永久删除的独立确认、单次有效计划、撤回和同名冲突。
- 软件名称确认、本体卸载后残留另行选择、同名残留归属确认。
- 其他版本重新安装、共享目录、厂商目录及运行中进程保护。
- Ryujinx 资料和日志清理、大目录部分占用统计、完整目录移动与撤回。
- 会话认证和来源检查，本地 AI 地址校验及模型发现。
- 原地提示结果、不跳转恢复页，取消操作不修改文件。
- 退出时取消扫描、等待文件操作结束并清理临时会话。

## 打包后检查

先构建完整 App。只读检查后端、软件图标和退出清理可以运行：

```sh
mkdir -p .build
python3 - <<'PY'
import sys
sys.path.insert(0, 'packaging')
from smoke_backend import check
check('arm64')
# Apple Silicon 上需要已安装 Rosetta；Intel 实机需单独验证。
check('x86_64')
PY
```

`check()` 及 `packaging/smoke_backend.py` 的命令行入口默认只读，不执行文件删除。开发者确需验证文件动作时可显式调用 `check(..., file_actions=True)`，它只处理自己创建的临时样本；不要使用个人资料替换测试样本。

原生窗口的只读检查：

```sh
"dist/空间磁盘管家.app/Contents/MacOS/SpaceLens" --smoke-test
"dist/空间磁盘管家.app/Contents/MacOS/SpaceLens" --smoke-features
"dist/空间磁盘管家.app/Contents/MacOS/SpaceLens" --smoke-coffee
```

特征检查会读取已安装应用的元数据，并使用虚构残留项目展示界面；不要把包含实际应用路径的截图直接作为公开素材。

## 已验证范围

1.0.0 的本地验证环境为 macOS 15.7.5、M2 Pro。46 项 Python 测试及三组前端测试通过，打包后的 arm64 和 x86_64（Rosetta）运行、图标显示与退出清理通过。

这些结果不代表所有 Mac、所有权限组合或所有第三方软件都已实测。模型接口测试使用受控模拟服务，不能据此声称真实模型在特定机器上的推理速度或回答质量。

## 设置界面与固定资源检查

覆盖固定资源完整性、路径白名单、不可上传替换及延迟显示测试；设置页和打赏弹窗不启动扫描。收款码源图和排版图分别通过系统 Vision 解码，确认付款地址一致；成品同为 640×640，并保留中心标识。原生界面测试会加载两张图片，检查显示宽高一致且没有支付配置编辑控件。
