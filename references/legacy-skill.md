---
name: synology-nas
description: 通过群晖官方 DSM/File Station API 或已有 SMB 挂载管理局域网 NAS，执行目录浏览、搜索和文件归档。用于群晖存储接入 AI Agent、文件操作及接口排查。
---

# 群晖 NAS 存储

本地自建 Skill，基于官方 API，不是群晖官方发布的 Skill 或 MCP 服务。脚本需要 Python 3.10+，仅依赖标准库。

## 选择访问方式

- 目录浏览、搜索、新建目录、重命名、NAS 内复制和移动：使用 File Station API。
- 处理文件内容、上传下载大文件：若执行主机已有授权 SMB 挂载，使用文件系统工具。脚本不实现 multipart 上传或二进制下载，不用 JSON 调用代替。
- 需要统一 MCP 工具时，按用户要求另建适配服务；不自动安装第三方组件或开放公网。

先确认 NAS、目标目录与授权范围。请配置自己的 NAS 地址，执行前重新验证连通性。Ubuntu SSH 账号、SMB 账号和 DSM 应用权限不能混为一谈。

## 配置与调用

以下路径相对本 Skill 目录。`python scripts/nas.py --help` 查看参数。

环境变量：

- `SYNOLOGY_URL`：例如 `https://nas.example.lan:5001`。
- `SYNOLOGY_USER`、`SYNOLOGY_PASSWORD`：专用普通账号，具有目标共享目录和 File Station 权限。
- `SYNOLOGY_CA_FILE`：可选，内部 CA 的 PEM 文件。
- `SYNOLOGY_OTP`：可选，当次登录验证码。

不把真实密码、SID 写进命令记录、Skill 或报告。缺凭据时只做 discover，说明认证未验证，不猜密码、不读取 SMB 凭据文件尝试复用。

```powershell
python scripts/nas.py discover
python scripts/nas.py shares
python scripts/nas.py list /media --limit 100 --offset 0
python scripts/nas.py call SYNO.FileStation.CreateFolder create --params-file task-params.json --write
```

新建目录的参数文件内容示例：

```json
{"folder_path":["/media"],"name":["agent-output"],"force_parent":false}
```

也支持 `--params '<JSON对象>'`；PowerShell 传 JSON 不稳定时优先使用任务目录里的 UTF-8 参数文件。

脚本动态发现接口路径，采用已实现版本上限与设备版本范围的交集。通过 POST 登录，退出前登出，不输出 SID。仅允许列出的文件 API，不提供任意 DSM 管理请求。修改状态的方法需 `--write`，此标记不是用户授权的替代品。

已有明确文件操作授权时直接执行，不重复确认。仅检查服务或创建 Skill 不代表获准修改 NAS 文件。

TLS 默认校验；证书失败时优先用匹配域名或内部 CA。`--insecure` 只用于用户允许的临时诊断，不写入持久配置。脚本仅允许 HTTP 无凭据 discover，拒绝通过 HTTP 登录。

## 执行要点

详细方法及参数见 [api.md](api.md)。

- API 路径从共享目录开始，如 `/media/output`；不是 `/volume1/...` 或 Ubuntu 的 `/mnt/...`。
- list 需 offset/limit 分页，不能把第一页当成全部。
- 搜索、复制移动、删除可能返回 taskid。启动成功不等于完成，继续查 status，核对 finished 及逐文件错误，按对应文档清理任务。
- 删除、覆盖、批量移动前核对精确路径与授权范围。复制和上传默认不覆盖已有文件；已有授权无需再次询问。
- 文件系统方式同样限制在授权根目录内，规范化路径并检查软链接，避免越界。
- 区分接口发现成功、登录成功、目录可读和实测写入成功。写入测试只在用户授权的测试目录进行。
- HTTP 200 不代表业务成功，必须检查 JSON success/error。119 表示 SID 不存在。认证/权限错误检查会话、File Station 应用权限和共享目录 ACL，停止自动重试账号，避免触发封锁。
- 连接失败先确认运行位置能访问局域网。需要通过 Ubuntu 连接时使用 remote-server-ops 技能解析既有 SSH 别名，再用原生 SSH。

最小只读验收：discover → shares → 指定目录 list。缺凭据不阻止完成匿名接口探测。官方工具检索依据见 [official-tools.md](official-tools.md)。
