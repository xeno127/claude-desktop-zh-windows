# 贡献说明

欢迎改进译文、Windows兼容性和恢复流程。提交问题时提供应用版本、Windows版本、使用模式和去除个人信息后的报错，不要提交API密钥、用户配置、聊天记录或完整备份。

## 开发验证

Python3.10+，不需要第三方Python依赖：

```powershell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 .\setup.py check
python -X utf8 .\setup.py verify
python -X utf8 .\release.py
```

单元测试在临时目录中使用真实文件验证安装、回滚、恢复、备份损坏及版本冲突；不会卸载本机程序、写入官方安装或启动Claude。check与verify只读。UAC和真实GUI/Cowork任务需要在有受支持安装的测试机确认，不能用模拟测试替代兼容性结论。

安装和恢复通过claude_zh.py的资源事务完成，setup.py只负责Windows注册发现、参数、同用户UAC和状态显示，release.py负责白名单打包。不允许加入移除官方包、接管ACL、替换官方核心、创建替代Cowork服务或默认关闭更新的逻辑。

## 译文与版本适配

三个中文JSON必须与受支持版本英文键集合一致，保留ICU变量、选择/复数分支与标签。修改翻译后要重新运行FormatJS ICU语法与结构检查，并更新词表SHA256、条目数和验证报告，不能只改报告来绕过校验。

适配新版本必须取得合法本机安装，核对包族、版本、EXE/ASAR及源资源哈希，检查语言数组结构，计算原样UTF8/LF补丁哈希，确认完整安装与恢复、默认语言、官方启动和真实Cowork任务。当前版本白名单是明确的边界，不应改成“忽略哈希继续”。

原英文资源、应用二进制和完整JS不会提交仓库；仅提交必要的补丁逻辑、中文资源、摘要和报告。保留MIT许可和NOTICE出处。
