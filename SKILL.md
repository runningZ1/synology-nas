---
name: synology-nas
description: 使用 synology-nas 命令行管理群晖 NAS：浏览搜索、结构导出、上传下载、文件整理、校验统计、压缩包、收藏共享链接和系统存储状态查询。用于局域网 NAS 文件及状态任务；不用于磁盘格式化、账户权限或公网部署。
metadata:
  tested-cli-version: "0.2.0"
---

# 群晖 NAS CLI

本地工具，基于群晖公开 API 和明确标注的社区接口，不是群晖官方 Skill。使用 `synology-nas`，不再临时编写操作脚本。需要 Python 3.10+；本机 Windows/Python 3.12 已验证。

## 安装与发现

```powershell
synology-nas version
synology-nas schema
synology-nas doctor
synology-nas auth status
```

未安装时，在本 Skill 目录运行 `python -m pip install --no-deps --no-build-isolation -e .`；也可 `python -m synology_nas_cli`。安装、认证、参数和完整命令见 [README.md](README.md)。

配置只存 URL 和账号。凭据从 `--password-file`、`--password-stdin` 或 `SYNOLOGY_PASSWORD` 提供；环境变量可能被子进程或诊断读取。每次调用登录后登出，无持久会话。不把真实凭据写入命令参数、Skill、报告，不读取聊天记录或 SMB 凭据猜测复用。缺凭据仍可 doctor/discover。

HTTPS 默认校验证书。证书验证失败时优先配置受信域名或 CA，已授权临时诊断可显式加 `--insecure`，不保存该设置。

## 查询与整理

```powershell
synology-nas shares --limit 20
synology-nas list /media --limit 50 --fields name,isdir
synology-nas stat /media
synology-nas tree --depth 3 --max-dirs 500 --max-entries 5000 --save structure.json
synology-nas search /media '*秋冬*' --limit 20 --wait 5
synology-nas size /test --wait 10
synology-nas checksum /test/probe.txt --wait 10
synology-nas download /test/probe.txt --file ./probe.txt
synology-nas system storage
synology-nas system utilization
synology-nas system packages
synology-nas system containers
```

分页遵循 `pagination.next_offset`，不能把第一页当成全部。目录树默认有深度/目录数/条目数上限，检查 complete/truncated/errors。不递归回收站、快照、索引内部；未完整扫描不能报告全 NAS 总量。

搜索返回 taskid，读取后用 `tasks clean SYNO.FileStation.Search TASKID --commit` 清理本次任务。长操作返回 running 时继续 `tasks status API TASKID`；启动成功不等于完成。不全局取消/清理他人任务。

## 写操作

默认预览，`--dry-run` 可显式表达。文件写入必须指定授权范围 `--scope`，程序检查源、目标和实际路径，禁止修改共享根。上传默认不覆盖；复制/移动保留原名且拒绝覆盖；rename 仅同目录改名。

```powershell
synology-nas mkdir /test/agent-output --scope /test --dry-run
synology-nas mkdir /test/agent-output --scope /test --commit
synology-nas upload ./probe.txt /test/agent-output/probe.txt --scope /test/agent-output --commit
synology-nas rename /test/agent-output/probe.txt renamed.txt --scope /test/agent-output --commit
synology-nas delete /test/agent-output/renamed.txt --scope /test/agent-output --commit --confirm /test/agent-output/renamed.txt
```

commit/scope 是技术机制，不替代用户授权。已有明确授权时直接执行，不重复询问。只做检查或制作工具不代表获准整理业务文件。测试只在 test 下本次唯一新建目录进行。

共享链接创建会改变访问范围，先 `links create PATH --scope ROOT --expires YYYY-MM-DD` 预览；真实创建需 `--allow-sharing --commit` 和用户对目标内容的明确授权。验收没有创建业务共享链接。系统、磁盘、套件、容器命令均只读。

## 输出与恢复

默认 stdout 一个 JSON 信封；jsonl 也是一个终态事件，text 为转义后的可读 JSON。检查 ok/data 或 error.code/retryable/outcome/next_actions 与退出码。用 schema、api catalog 发现参数，不猜枚举和接口。

| 退出码 | 处理 |
|---|---|
| 2 | 修正参数，查看 help；不重试 |
| 3 | 认证、权限、资源、TLS、套件问题；状态变化后再调用 |
| 4 | 网络/超时；只读且 retryable=true 才有限重试 |
| 5 | 检查目标冲突，不默认覆盖 |
| 1 | 后端/内部问题，保存脱敏信封，不循环调用 |
| 130 | 已中断，按任务或路径核对实际状态 |

写入没有自动重试。outcome=unknown 时核对任务/路径，禁止直接重发。完整错误表见 `synology-nas errors`。

## 覆盖与限制

31 命令、68 JSON 方法及上传/下载/缩略图3个二进制方法，涵盖官方File Station文档19个家族。长尾方法可通过受控 `api call --params-file FILE` 调用；通用文件写入拒绝执行，必须用类型化命令。额外系统接口标记 community/device，不当作官方稳定承诺。

已实测：分页、树、搜索、真实CRUD、上传覆盖、下载内容匹配、MD5、容量统计、复制移动、ZIP浏览解压、收藏/链接读取、系统存储/资源/套件/容器/SMB/NFS/备份服务状态。压缩 start 被当前NAS以105拒绝；不宣称压缩可用，不自动改权限。缩略图、收藏/分享变更、快照/WORM未做真实变更验收。Download Station未安装。

只验证Windows和小文件，不代表TB级传输或其他平台通过。`scripts/nas.py` 保留旧参数与输出，新任务使用CLI。

公开仓库不包含本地目录树、配置或设备原始响应。操作前查询当前 API。[接口覆盖](references/api-coverage.md)；[验收记录](references/cli-acceptance.md)。
