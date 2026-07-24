# 贡献指南

感谢你关注留文。当前项目仍处于内测阶段，优先接受兼容性修复、转录准确率改进、总结可信度改进和文档完善。

## 提交问题

- 程序错误请使用 Bug 模板。
- 新功能建议请使用功能建议模板。
- 安全问题请阅读 `SECURITY.md`，不要公开披露。
- 请勿提交 API Key、个人信息、受限内容或未经授权的视频文件。

## 本地开发

环境要求：

- Windows 10/11
- Node.js 22.13+
- Python 3.14

启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

测试：

```powershell
npm.cmd test
python -m unittest discover -s tests -p "test_*.py"
npm.cmd run lint
```

## Pull Request

提交 Pull Request 前，请先阅读并同意 [贡献者许可协议](CONTRIBUTOR_LICENSE_AGREEMENT.md)。该协议不转让贡献者的所有权，但允许项目维护者继续维护公开非商业版本，并在必要时对包含该贡献的版本进行单独商业授权。

如果贡献属于雇主、客户或其他实体，请先取得有权代表该实体作出的授权。权属不清、无法完成许可确认或包含未标明第三方内容的贡献不会被合并。

提交前请确认：

- 改动范围清晰，没有混入运行数据或构建产物；
- 新增行为有相应测试或清楚的手动验证说明；
- 前端和 Python 测试通过；
- 没有提交 `data/`、`.env`、日志、模型、压缩包和 API Key；
- 已标明贡献中包含的所有第三方代码、素材及其许可证；
- 已阅读并同意贡献者许可协议，且有权授予其中约定的许可；
- 用户可见变化已经更新 README 或相关文档。

项目维护者可能会要求拆分过大的改动，或拒绝与产品方向不一致的功能。
