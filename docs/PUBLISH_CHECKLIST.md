# GitHub 发布前检查清单

## 必须由维护者确认

- [ ] GitHub 仓库名称（推荐：`wenl-scribe`）
- [ ] GitHub 所有者账号或组织
- [ ] 仓库公开还是先私有
- [x] 软件许可证：`PolyForm-Noncommercial-1.0.0`
- [ ] 首发版本号（推荐：`v0.6.1`）
- [ ] 是否允许外部 Pull Request
- [ ] 安全问题的私下联系渠道

## 许可证与权利文件

项目采用“源码公开、仅限非商业使用”的发布方式，不宣传为符合 OSI 定义的开源软件：

- 自有源代码：`PolyForm-Noncommercial-1.0.0`；
- 商业使用：需要事先取得书面授权；
- 名称、Logo、图标与品牌资产：不包含在源代码许可中；
- 用户输入与输出：留文不主张其著作权，但用户负责确保拥有处理权利；
- 第三方组件：继续适用其原始许可证；
- 外部贡献：合并前必须完成贡献者许可确认。

`COMMERCIAL_USE.md`、`TRADEMARKS.md` 等说明文件不得修改或替代 `LICENSE` 正文。

## 代码与隐私

- [ ] 已撤销所有曾出现在截图、聊天或日志中的旧 API Key
- [ ] `data/` 未进入提交
- [ ] `.env`、`config.json`、日志和任务文件未进入提交
- [ ] Whisper 模型未进入提交
- [ ] `release/`、`dist/`、`desktop-dist/` 和打包中间文件未进入提交
- [ ] 对 Git 暂存区再次执行密钥扫描
- [ ] 没有未经授权的视频、音频、字幕或封面文件

## 功能验收

- [ ] B 站普通链接
- [ ] `b23.tv` 短链
- [ ] 完整分享文案
- [ ] 有公开字幕的视频
- [ ] 无字幕视频的本地 Whisper 转录
- [ ] 小、中、大三种模型至少完成基本启动检查
- [ ] Gemini 或 SenseNova 总结
- [ ] 总结观点与时间戳
- [ ] 总结页左侧浮窗和缩略按钮
- [ ] 逐字稿页右侧浮窗和缩略按钮
- [ ] 总结 Markdown 下载与中文文件名
- [ ] 逐字稿 Markdown 下载与中文文件名
- [ ] 历史记录、删除、取消、重试和重新总结

## Windows 干净环境

- [ ] 在没有 Node.js 和 Python 的 Windows 10/11 x64 电脑运行
- [ ] 解压后可双击启动
- [ ] 系统托盘可打开和退出
- [ ] 第一次模型下载提示清楚
- [ ] Windows Defender 扫描完成
- [ ] 记录 SmartScreen 实际提示

## GitHub 仓库

- [ ] README 中下载链接、文档链接可用
- [ ] About 描述和 Topics 已填写
- [ ] Issues 已开启
- [ ] Private vulnerability reporting 已开启
- [ ] Actions 首次运行通过
- [ ] Bug／功能建议模板显示正常
- [x] 已添加未经修改的标准 `LICENSE`
- [x] 已添加 `NOTICE`、`COMMERCIAL_USE.md` 和 `TRADEMARKS.md`
- [x] 已添加 `CONTRIBUTOR_LICENSE_AGREEMENT.md` 并更新 PR 模板
- [ ] 按最终发行包完成第三方依赖、PyAV/FFmpeg 和 LGPL 组件许可审查
- [ ] 将真实个人姓名或公司主体补充到正式商业合同与商标申请资料
- [ ] 检索并评估“留文”、WENL、WENL Scribe 与 Logo 的商标注册
- [ ] 如开放社区贡献，补充维护者联系方式和行为准则

## Release

- [ ] 最终代码提交完成
- [ ] 更新版本号和 `CHANGELOG.md`
- [ ] 重新构建便携包
- [ ] 实际从最终 ZIP 解压并启动
- [ ] 确认 ZIP 包含 `LICENSE`、`NOTICE`、商业使用、品牌和第三方许可说明
- [ ] 计算 SHA-256
- [ ] Release 先保存为 Draft
- [ ] 上传便携包和校验文件
- [ ] 核对 Release 文案、文件名和版本号
- [ ] 发布后从 GitHub 下载一次并复验

## 宣传素材

- [ ] 首页截图
- [ ] 内容总结截图
- [ ] 完整转录截图
- [ ] 左侧与右侧迷你播放器截图
- [ ] Markdown 导出效果截图
- [ ] 30–60 秒演示视频
- [ ] 确认演示视频内容可公开使用
