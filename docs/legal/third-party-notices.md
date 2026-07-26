# 第三方软件与素材说明

留文包含、依赖或在构建过程中使用第三方软件。第三方软件继续适用其各自许可证，不因留文采用 [PolyForm Noncommercial License 1.0.0](../../LICENSE) 而改变。

本文件记录当前项目和 Windows 便携版中的主要第三方组件。`package-lock.json`、Python 安装包元数据及最终构建产物中的许可文件共同构成依赖审查依据。发布新版本前必须按实际锁定版本重新核对。

## JavaScript 主要运行时组件

| 组件 | 当前版本 | 项目地址 | 许可证 |
| :--- | :--- | :--- | :--- |
| React | 19.2.6 | <https://github.com/facebook/react> | MIT |
| React DOM | 19.2.6 | <https://github.com/facebook/react> | MIT |
| Next.js | 16.2.6 | <https://github.com/vercel/next.js> | MIT |
| Drizzle ORM | 0.45.2 | <https://github.com/drizzle-team/drizzle-orm> | Apache-2.0 |

构建工具和完整的 JavaScript 传递依赖清单见 `package-lock.json`。开发依赖不一定进入最终发行包，但在源码构建和再分发时仍应遵守其许可证。

## Windows 便携版主要 Python 组件

下表版本来自 v0.7.0 Windows 构建环境；正式发布时应以实际构建环境为准。

| 组件 | 已核对版本 | 项目地址 | 许可证或说明 |
| :--- | :--- | :--- | :--- |
| faster-whisper | 1.2.1 | <https://github.com/SYSTRAN/faster-whisper> | MIT |
| CTranslate2 | 4.8.1 | <https://github.com/OpenNMT/CTranslate2> | MIT |
| PyAV | 18.0.0 | <https://github.com/PyAV-Org/PyAV> | BSD-3-Clause |
| Hugging Face Hub | 1.24.0 | <https://github.com/huggingface/huggingface_hub> | Apache-2.0 |
| tokenizers | 0.23.1 | <https://github.com/huggingface/tokenizers> | Apache-2.0 |
| ONNX Runtime | 1.27.0 | <https://github.com/microsoft/onnxruntime> | MIT |
| NumPy | 2.5.1 | <https://github.com/numpy/numpy> | BSD-3-Clause 及其发行包列明的第三方许可证 |
| Pillow | 12.3.0 | <https://github.com/python-pillow/Pillow> | MIT-CMU |
| pystray | 0.19.5 | <https://github.com/moses-palmer/pystray> | LGPL-3.0 |
| PyInstaller | 6.21.0 | <https://github.com/pyinstaller/pyinstaller> | GPL-2.0-or-later，附带非自由程序分发例外 |

## 音视频组件

PyAV 的发行包可能包含或链接 FFmpeg 库。FFmpeg 的最终许可证取决于实际构建配置和所包含的库，不能仅根据 PyAV 的 BSD 许可证推定。

每次发布 Windows 便携版前，应当检查最终压缩包中的 FFmpeg/PyAV 二进制文件、构建信息及许可证，并满足对应的 LGPL、GPL 或其他适用条款。完成该核对前，不应在本文件中宣称最终安装包已经通过完整的第三方许可审计。

## 转录模型

Whisper/faster-whisper 模型文件通常在用户首次使用时从模型仓库下载，不随本 GitHub 源码仓库提供。模型权重、词表及相关文件适用其模型仓库中列明的许可证和使用条款；本项目许可证不覆盖这些文件。

## 外部平台和 API

哔哩哔哩播放器、视频内容、Gemini、SenseNova、OpenAI、Ollama 及其他第三方服务不属于留文项目资产。使用这些平台或服务时，应遵守其各自条款、内容权利和 API 政策。

## 再分发责任

任何再分发者均应：

- 保留 `LICENSE`、`NOTICE` 和本文件；
- 保留第三方组件要求保留的版权声明、许可证文本和归属说明；
- 不将第三方软件或素材重新描述为留文自有内容；
- 根据实际发行包重新完成依赖与二进制许可审查。

本清单用于提供透明度，不替代任何第三方许可证的完整正文。
