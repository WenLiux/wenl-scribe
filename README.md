# 留文 · WENL SCRIBE

<p align="center">
  <img src="public/wenl_logo.svg" width="168" alt="留文 WENL SCRIBE">
</p>

<p align="center"><strong>所见所听，皆可留文。</strong></p>

留文是一款本地优先的 B 站视频转录与内容整理工具。粘贴普通链接、`b23.tv` 短链或完整分享文案，即可获得带时间戳的逐字稿、可回看原文依据的结构化总结，以及适合保存和继续编辑的 Markdown 文件。

> 当前处于 Windows 内测阶段。请勿用它处理无权访问、下载或使用的内容；重要信息仍应回看原视频核对。

## 为什么使用留文

- **本地转录**：没有公开字幕时，使用本机 Whisper 转录，音频无需交给第三方转录平台。
- **结果可核对**：总结观点绑定逐字稿原句和视频时间戳，降低“总结得很顺但并非原意”的风险。
- **边看边读**：结果页保留 B 站官方播放器；总结页浮窗默认在左侧，逐字稿页默认在右侧，均可缩略为统一位置的按钮。
- **可继续使用**：逐字稿和总结分别导出为排版清晰的 Markdown，文件名直接使用视频标题。
- **失败可恢复**：转录完成后立即保存；总结失败不会丢失逐字稿，历史任务可单独重新总结。

## 功能概览

| 能力 | 当前状态 |
| :--- | :--- |
| B 站普通链接、短链和分享文案解析 | ✅ |
| 公开字幕优先、本地 Whisper 降级 | ✅ |
| `small`、`medium`、`large-v3-turbo` 模型 | ✅ |
| 中文、英文和自动语言识别 | ✅ |
| Gemini、SenseNova、OpenAI 及兼容接口总结 | ✅ |
| 总结观点与原文依据校验 | ✅ |
| B 站播放器与时间戳定位 | ✅ |
| 桌面与移动端迷你播放器 | ✅ |
| 逐字稿／总结 Markdown 下载 | ✅ |
| Windows 便携版 | 🧪 内测 |
| 在线云端转录 | 暂未提供 |

## Windows 用户

前往 [Releases](../../releases/latest) 下载最新的 Windows 便携版。

1. 完整解压下载的 ZIP。
2. 双击 `WENL Scribe.exe`。
3. 程序会自动打开浏览器。
4. 首次使用某个 Whisper 模型时，需要联网下载模型。
5. 使用结束后，右键系统托盘中的留文图标并选择“退出留文”。

Windows 可能显示“未知发布者”，因为当前内测版本尚未完成代码签名。请只使用本仓库 Release 页面提供的文件。

详细说明请阅读 [Windows 用户指南](docs/user/user-guide.md) 和 [常见问题](docs/user/troubleshooting.md)。

## 从源码运行

当前开发环境在 Windows 上验证，要求：

- Node.js 22.13 或更高版本
- Python 3.14
- 可访问 B 站和所选模型／总结服务

启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

打开 `http://localhost:3001/`。停止服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\stop.ps1
```

首次启动会安装缺少的依赖；首次使用某个 Whisper 模型时会自动下载模型。

### 运行检查

```powershell
npm.cmd test
python -m unittest discover -s tests -p "test_*.py"
npm.cmd run lint
```

### 构建 Windows 便携版

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-portable.ps1
```

发行文件只应通过 GitHub Release 分发，不应提交到 Git 仓库。

## Markdown 导出

导出文件使用视频标题命名：

```text
<视频标题>逐字稿留文.md
<视频标题>总结留文.md
```

内容包含视频信息表、章节分隔、可点击时间戳、原文引用和生成说明。标题中不适用于 Windows 文件名的字符会自动清理。

## 总结服务

留文可以使用 Gemini、SenseNova、OpenAI Responses API、本地 Ollama，以及其他 OpenAI 兼容接口。

在页面右上角打开“设置”，选择接口类型，填写 API 地址、模型和密钥，然后依次点击“保存配置”和“测试连接”。不开启云端总结时，留文仍可提供本地原文重点摘录。

启用云端总结时：

- 音频仍在本机转录；
- 带时间戳逐字稿会发送给你选择的总结服务；
- API 密钥以明文保存在本机应用数据目录，不会提交到仓库。

请阅读完整的 [隐私说明](PRIVACY.md)。

## 数据位置

| 运行方式 | 数据目录 |
| :--- | :--- |
| Windows 便携版 | `%LOCALAPPDATA%\WENL Scribe\data` |
| 源码开发模式 | 项目内 `data/` |

任务记录、模型、总结配置和日志均在本机保存。`data/`、构建产物、日志和发行包已加入 `.gitignore`。

## 文档

- [文档中心](docs/README.md)
- [Windows 用户指南](docs/user/user-guide.md)
- [常见问题与故障排查](docs/user/troubleshooting.md)
- [隐私说明](PRIVACY.md)
- [安全政策](SECURITY.md)
- [贡献指南](CONTRIBUTING.md)
- [版本记录](CHANGELOG.md)

## 反馈

- 使用问题或程序错误：选择“Bug 反馈”模板提交 Issue。
- 产品建议：选择“功能建议”模板提交 Issue。
- 安全漏洞：请按 [安全政策](SECURITY.md) 私下报告，不要在公开 Issue 中粘贴 API Key、日志隐私信息或漏洞细节。

提交问题前，建议在任务结果页下载“脱敏诊断”文件，并再次确认文件中没有不希望公开的信息。

## 内容与责任说明

留文不隶属于哔哩哔哩、Google、商汤科技或其他第三方服务。播放器使用 B 站官方页面；外部模型和 API 的可用性、额度与条款由对应服务商决定。使用者应确保自己有权处理相关内容，并遵守内容来源平台和所在地区的法律与规则。

## 许可证

留文采用**源码公开、仅限非商业使用（Source Available for Noncommercial Use）**的发布方式，不属于符合 OSI 定义的开源软件。

留文自有源代码依据 [PolyForm Noncommercial License 1.0.0](LICENSE) 提供。允许许可证规定的非商业使用、修改和分发；未经项目权利人事先书面授权，不得用于商业目的。再分发时必须按许可证要求同时提供 `LICENSE` 和 [NOTICE](NOTICE)。

“留文”、“WENL”、“WENL Scribe”、Logo、图标和品牌资产不包含在源代码许可中。修改版或分支项目必须更名、更换品牌视觉，并明确说明其不是留文官方版本。详见 [品牌与标识权利声明](docs/legal/trademarks.md)。

留文不主张用户导入内容、逐字稿、总结或导出 Markdown 文件的著作权；但用户仍须确保有权处理相关内容。输出内容归属与软件能否用于商业目的相互独立，详见 [商业使用与用户输出说明](docs/legal/commercial-use.md)。

第三方组件继续适用其各自许可证，详见 [第三方软件与素材说明](docs/legal/third-party-notices.md)。

> The original source code in WENL Scribe is available under the PolyForm Noncommercial License 1.0.0. Commercial use requires prior written authorization. Project names, logos, icons and brand assets are excluded from the source-code license.
