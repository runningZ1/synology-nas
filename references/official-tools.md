# 官方工具检索结论

核查日期：2026-11-03。

检查群晖开发者入口、官方 File Station API 文档、SynologyOpenSource 公开页面，并检索群晖网站中的 Agent Skills、SKILL.md、Model Context Protocol。

本次公开检索未找到群晖官方发布的可直接安装 Agent Skill 或面向文件管理的 MCP 服务。这是检索边界内的结论，不能据此断言所有未公开或后续发布产品都不存在。

官方已有 File Station HTTP/HTTPS API，包含接口发现、账号认证、会话及文件操作。因此自建 Skill 直接调用官方 API，不依赖第三方 SDK。

注意：MailPlus 的 MCP 是 Message Content Protection，不是 Model Context Protocol。https://github.com/Synology 自称 Unofficial Synology Lab，不能根据名称认定官方身份。

官方资料：

- https://www.synology.com/en-us/support/developer
- https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf
- https://kb.synology.com/en-global/DG/DSM_Login_Web_API_Guide/2
- https://github.com/SynologyOpenSource

第三方实例：https://github.com/atom2ueki/mcp-server-synology 。个人作者维护；本次未安装、未审计，不称为群晖官方工具。

## 本 Skill 验证

2026-11-03：skill-creator 的 quick_validate.py 通过；nas.py 从本机对 nas.example.com:5000 完成无凭据接口发现，返回 success=true。离线模拟验证通过：拒绝 HTTP 登录、API 版本交集、无 --write 阻止修改、拒绝非文件管理 API、分页参数检查、登录与登出时传递并清除 SID。

未进行真实 DSM 登录、文件内容读取或 NAS 写入；真实登录、OTP、后台任务及文件写入仍待有授权凭据后验证。上传下载未实现为脚本子命令，按 SKILL.md 使用既有 SMB 或官方协议。
