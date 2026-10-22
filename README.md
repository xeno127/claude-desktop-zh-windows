# Claude Desktop 默认中文补丁（Windows）

安装一次，以后从开始菜单或 Windows 搜索直接打开 **Claude**，默认显示简体中文，日常不会弹出 CMD。

这是非官方补丁，目前仅支持 **Claude Desktop 3.1623.1.0 x64 的第三方网关模式**。其他版本会停止安装，官方账号模式不在本次验证范围。

## 快速使用

需要 Windows、Python 3.10 或更新版本，以及本机已安装的受支持版本 Claude Desktop。Python 仅使用标准库，无需安装 pip 依赖。

1. 下载发布 ZIP 并完整解压，保留 `setup.cmd`、Python 文件和 `language-pack` 的相对位置。
2. 从右下角托盘完全退出 Claude。
3. 双击 **`setup.cmd`**。
4. 阅读提示。如检测到商店版，输入 **`REPLACE`** 确认替换；其他输入会取消。
5. 等待显示“安装完成”，关闭安装窗口。
6. 以后直接在开始菜单或 Windows 搜索打开 **Claude**，不用再运行 CMD。

请使用自己的普通 Windows 用户会话运行。安装器不会申请管理员权限、接管 WindowsApps 或自动启动 Claude。如果系统策略拒绝卸载，请保留报错，按[恢复说明](docs/恢复与卸载.md)处理，不要反复修改目录权限。

## 安装器会做什么

1. 检查程序版本、源文件 SHA256、语言包条目以及 Claude 是否已经退出。
2. 完整备份相关用户数据，为每个文件记录 SHA256；备份不完整或文件发生变化时停止。
3. 从本机安装目录复制程序到 `%LOCALAPPDATA%\Programs\Claude`，导入中文资源并校验。
4. 在你确认后移除**当前用户**的商店版；不卸载其他用户的注册。
5. 保留用户配置和聊天相关数据，只将语言字段 `locale` 设置为 `zh-CN`。
6. 更新当前用户开始菜单的 `Claude` 快捷方式，直接指向中文程序，带 `--lang=zh-CN` 参数。

**替换会取消商店对该安装的自动更新，并移除该商店包提供的 Cowork 服务。** 本项目没有安装替代服务；Cowork、官方账号模式及中文程序自身的自动更新尚未完整验证。需要这些能力时，请先评估是否使用此补丁。

安装在本机只读复制原程序，不分发 Claude EXE、DLL、ASAR 或完整前端 JavaScript。`claude.exe` 与 `app.asar` 保持原样，只增加中文 JSON 并局部修改前端语言列表。

## 文件位置

| 内容 | 默认位置 |
| --- | --- |
| 中文程序 | `%LOCALAPPDATA%\Programs\Claude` |
| 数据备份与迁移记录 | `%LOCALAPPDATA%\ClaudeZhPatch\backups\时间戳` |
| 最近一次安装记录 | `%LOCALAPPDATA%\ClaudeZhPatch\last-install.json` |
| 待完成迁移记录 | `%LOCALAPPDATA%\ClaudeZhPatch\pending.json` |
| 第三方模式现有配置 | `%LOCALAPPDATA%\Claude-3p\config.json` |

请预留“约 1 GB + 用户数据大小”的系统盘空间。备份保留在本机，可能包含 API 密钥、聊天数据和登录状态，**不要上传 GitHub 或贴到 issue**。程序使用原来的账户数据，不是隔离账户。安装完成后移动或删除下载的补丁文件不影响开始菜单启动；请保留数据备份。

## 检查与其他用法

在补丁目录打开 PowerShell：

```powershell
.\setup.cmd check
```

这只检查当前环境和安装资源，不卸载、不写配置、不启动应用。遇到找不到 Python 时，请安装 Python 并勾选加入 PATH；也可以给 `CLAUDE_ZH_PYTHON` 环境变量设置自己 `python.exe` 的完整路径。

高级用法、配置路径和故障排查见[安装与使用](docs/安装与使用.md)。中断后继续、恢复语言和重新安装商店版见[恢复与卸载](docs/恢复与卸载.md)。

## 翻译范围

- 前端 36,153 条，桌面菜单 861 条，动态文案 49 条，共 37,063 条，对应受支持版本的完整英文键集合。
- 构建时经过 FormatJS ICU 语法、分支变量和富文本标签结构校验，报告在 `language-pack/validation.json`。
- 中文词表基于上游译文、官方桌面中文资源、机器翻译和人工修订；尚未逐条人工审校全部页面。
- 品牌、模型名、代码和路径会保留原文；硬编码文字或在线页面仍可能出现英文。

Gateway 的 HTTP 503、`model_not_found` 或“分组下无可用渠道”是另一个问题，需要核对服务端路由和分组。不能凭这条报错断定模型长期不支持；本项目不会修改网关、密钥或模型 ID。

## 开源与贡献

上传仓库和打包方法见[GitHub 发布指南](docs/GitHub发布指南.md)，开发及验证步骤见[贡献说明](CONTRIBUTING.md)。本项目保留上游 MIT 许可和出处，详见 [NOTICE.md](NOTICE.md) 与 [LICENSE](LICENSE)。

请只发布源码、中文 JSON 和文档。不要上传程序副本、运行日志、数据备份或整个自己的 Claude 目录。
