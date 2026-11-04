# synology-nas

群晖 NAS 文件管理 CLI 与 AI Agent Skill · v0.2.0

[![Tests](https://github.com/runningZ1/synology-nas/actions/workflows/tests.yml/badge.svg)](https://github.com/runningZ1/synology-nas/actions/workflows/tests.yml)

基于群晖 DSM / File Station API 的社区项目，非群晖官方产品。适用于局域网或已有安全连接可达的 NAS。

AI Agent 和人工均可使用的群晖命令行工具。Python标准库实现，运行时零第三方依赖；当前Windows/Python3.12已验证。无需浏览器、常驻服务或Docker。

## 安装

要求 Python 3.10+，构建工具 setuptools>=68。克隆仓库后安装：

```powershell
git clone https://github.com/runningZ1/synology-nas.git
cd synology-nas
python -m pip install -e .
synology-nas version
synology-nas --help
synology-nas schema
```

源码安装要求setuptools>=68。离线可安装wheel：`python -m pip install --no-deps <wheel文件>`。卸载：`python -m pip uninstall osenso-synology-nas-cli`。editable源码更新立即生效；wheel需要重新构建安装。未配置Python Scripts PATH可用 `python -m synology_nas_cli`。不安装也可在本目录运行 `python scripts/cli.py version`。

## 安装为 AI Agent Skill

仓库根目录即 Skill 目录，入口为 [SKILL.md](SKILL.md)，附带 `agents/openai.yaml`。例如安装到 Codex 用户技能目录：

```powershell
git clone https://github.com/runningZ1/synology-nas.git "$HOME/.agents/skills/synology-nas"
python -m pip install -e "$HOME/.agents/skills/synology-nas"
```

让 Agent 重新发现技能后使用 `$synology-nas`；其他 Agent 按其技能目录约定安装。

示例任务：使用 synology-nas 列出 /media 的前 20 个文件；在已授权的 /test 范围内预览文件操作，再按授权执行。

## 配置与认证

复制 `config.example.json` 为源码根目录的 `config.json`，填入自己的地址和账号。该文件已被 Git 忽略，只保存 URL、账号和可选 CA 路径，不保存密码。配置优先级：参数 > 环境变量 > 配置文件。配置文件取自 `--config FILE`、SYNOLOGY_CONFIG或源码根config.json；wheel安装到其他位置时需显式指定配置或环境变量。

```json
{"url":"https://nas.example.com:5001","user":"nas-user"}
```

支持 `--url`、`--user`、`--ca-file`；对应环境变量 SYNOLOGY_URL、SYNOLOGY_USER、SYNOLOGY_CA_FILE。实际使用建议选择已有且只允许目标目录的普通账号，工具不创建账号或修改权限。

凭据支持 `--password-file FILE`（用户自行管理）、`--password-stdin`（管道）、SYNOLOGY_PASSWORD（CI兼容）；OTP使用SYNOLOGY_OTP。不提供明文密码argv参数，不持久化会话，不自动从聊天历史或浏览器提取凭据。环境变量可能被子进程/诊断读取。凭据stdin不能和上传、JSON载荷共用。

```powershell
synology-nas doctor
synology-nas auth status --password-file C:\secure\nas-password.txt
```

HTTPS默认验证。如证书不受信任，优先配置受信域名或 CA；临时诊断可显式加 `--insecure`，响应meta.tls_verified=false，不持久保存。正式使用可用受信域名或CA文件。HTTP仅允许匿名doctor/discover，拒绝传凭据登录。

## 命令索引

| 命令 | 功能 |
|---|---|
| version / schema / errors | 版本、机器能力、错误与退出码 |
| doctor / discover / auth status | 连通、设备API发现、认证检查 |
| info / shares / list / stat | 文件服务信息、共享、分页文件及元数据 |
| tree / search | 有界目录导出、服务器端递归名称搜索 |
| mkdir / rename / copy / move / delete | 文件整理，默认预览 |
| upload / download / thumbnail | 流式传输、原子落盘、缩略图 |
| size / checksum | 目录容量及数量、MD5校验 |
| permissions / mounts | 无写入的权限检查、现有虚拟挂载列表 |
| favorites list/add/remove/rename | 用户收藏夹 |
| links list/get/create/delete | 共享链接查看、预览、创建、撤销 |
| archive list/compress/extract | 包内浏览、压缩、解压 |
| tasks list/status/results/stop/clean | 后台任务与按ID管理 |
| system | info/utilization/storage/disks/pools/volumes/packages/services/containers/container-resources/smb/nfs/backup |
| downloads | Download Station info/tasks/statistics，需已安装套件 |
| api catalog / api call | 参数和影响分类明确的白名单，不是任意DSM管理入口 |

全局选项可放命令前后：`--output json|jsonl|text`、`--quiet`、`--no-input`、`--no-color`、`--timeout 30`、`--deadline 120`、认证选项、`--scope`、`--commit`、`--dry-run`。默认无交互、无颜色、无分页器；quiet/no-input/no-color保持此行为。每个子命令都有help。

## 查询

```powershell
synology-nas shares --limit 20
synology-nas list /media --limit 20 --offset 0 --fields name,isdir
synology-nas list /media --pattern '*.zip' --limit 20
synology-nas tree --depth 3 --max-dirs 500 --max-entries 5000 --save structure.json
synology-nas search /media '*秋冬*' --limit 20 --wait 5
synology-nas size /test --wait 10
synology-nas system storage
synology-nas discover --prefix SYNO.FileStation. --limit 100
synology-nas api catalog --prefix SYNO.FileStation. --limit 100
```

分页默认100、最大1000，跟随pagination.next_offset。字段投影允许path/name/isdir/additional，始终保留path。tree默认3层、500目录、5000条目，最大100层/10000目录/100000条目；回收站、快照、索引内部不递归。导出返回文件路径、字节数、SHA256及完整性；`--save -`返回有界JSON。检查complete/truncated/errors/pending_directories，不能把部分扫描当总量，实时扫描非原子快照。

搜索返回taskid、finished和分页；读取完用 `tasks clean SYNO.FileStation.Search TASKID --commit`。计算/复制/移动/删除/压缩/解压支持0..300秒等待，未完成返回running/taskid，随后 `tasks status API TASKID`。不全局清理任务。

## 写入与传输

```powershell
synology-nas mkdir /test/agent-output --scope /test --dry-run
synology-nas mkdir /test/agent-output --scope /test --commit
synology-nas upload ./probe.txt /test/agent-output/probe.txt --scope /test/agent-output --commit
synology-nas download /test/agent-output/probe.txt --file ./downloaded.txt
synology-nas rename /test/agent-output/probe.txt renamed.txt --scope /test/agent-output --commit
synology-nas delete /test/agent-output/renamed.txt --scope /test/agent-output --commit --confirm /test/agent-output/renamed.txt
```

默认预览会真实认证、解析源目标、检查存在性、范围和冲突，仅跳过实际mutation。文件操作要求scope，校验real_path，禁止共享根变更和已知软链接逃逸；NAS并发变更仍非事务。删除需精确路径confirm，非空目录需recursive。已有明确业务授权无需重复确认；技术标记不代替用户授权。

mkdir已有目录、同名rename、删除缺失目标返回noop。上传覆盖需overwrite；copy/move/rename拒绝覆盖。copy/move第二参数是已存在目录，保留源名。下载默认拒绝已有本地文件，overwrite-local才替换；临时文件写完后原子提交并返回SHA256。上传、下载默认max-bytes=1GiB，可显式调整；大文件未实测。上传源 `-`支持有界stdin；下载不支持binary stdout，以保留JSON协议。

```powershell
synology-nas archive list /test/probe.zip
synology-nas archive extract /test/probe.zip --destination /test/extracted --scope /test --commit
synology-nas archive compress /test/probe.txt --destination /test/probe.zip --scope /test --commit
synology-nas links create /test/probe.txt --scope /test --expires 2026-12-31
```

解压要求已有空目录，并预检嵌套包条目，拒绝路径穿越或超过10000条目的包。压缩仅创建新ZIP，当前NAS返回105，未验收成功。共享创建默认仅预览，实际需用户授权并加allow-sharing和commit；可从link-password-file提供保护口令，不回显秘密。收藏设置变更同样默认预览。

## 协议与长尾接口

默认stdout一个JSON终态信封：成功含schema_version/ok/type/data/meta；失败含error，带稳定code、retryable、outcome、details、next_actions。JSONL同样单条终态，text是转义缩进JSON。无原始异常/控制字符或逐字符输出。meta有request_id、耗时、TLS和登出确认。秘密按键和值脱敏。

退出0成功含noop；1后端/内部；2参数；3认证/权限/资源/接口/TLS；4网络/截止时间；5冲突；130中断。无自动重试；未知写入结果需要stat/tasks status核对，不直接重发。检查API success而非只看HTTP200。

`api call API METHOD --params-file request.json`支持UTF-8对象；文件名 `-`支持stdin，最大1MiB。注册表验证必需和允许字段，禁止认证参数，列表自动有界。通用文件写入拒绝调用，需typed命令；共享变更仍需allow-sharing。参数/来源/影响见schema和api catalog。

## 兼容与范围

scripts/nas.py保留旧参数和success/data输出；旧--write行为不改变。旧资料保留为历史，新行为以本README、SKILL和schema为准。当前注册39个API家族、68个JSON方法和3个二进制方法，官方File Station文档19家族均有对应入口；不等于实现设备公布的全部629个API。

局限：压缩start返回105；缩略图、快照/WORM未实测；收藏/分享变更未真实提交；Download Station未安装；大文件和其他操作系统未验证；自签名证书需自行配置信任。不会自行安装套件、改账户/ACL、公开NAS或改磁盘/网络/备份策略。

## 测试与验证范围

```powershell
python -m unittest discover -s tests -v
python scripts/cli.py version
python scripts/cli.py schema
```

自动测试使用本地夹具，无需 NAS，覆盖输出协议、分页、作用域、预览、冲突、路径穿越、传输完整性和脱敏。GitHub Actions 配置 Windows、Linux、macOS 与 Python 3.10 / 3.12 测试；实际通过情况以工作流结果为准。

历史 Windows / Python 3.12 小文件验收包括真实 CRUD、上传下载、复制移动、MD5、ZIP 浏览解压和系统只读查询；压缩在该设备返回 105。本次公开发布不重复执行 NAS 写入。大文件、断点续传及其他系统的真实 NAS 连接尚未验收。见 [验收说明](references/cli-acceptance.md)。

## 仓库结构

```text
SKILL.md                 Agent 使用约定
config.example.json      配置模板
agents/openai.yaml       Agent 展示信息
src/synology_nas_cli/     CLI、API 注册表与传输实现
scripts/cli.py           源码运行入口
scripts/nas.py           旧版兼容入口
references/              API 覆盖、设计与验收资料
tests/                   无 NAS 依赖的自动测试
```

本地配置、目录树、设备原始快照与真实请求记录不随公开仓库发布。导出文件可能含私人文件名或访问地址，分享前请自行检查。

## 接口资料与贡献

- [接口覆盖与来源](references/api-coverage.md)
- [CLI 设计契约](references/cli-design.md)
- [旧版 API 说明](references/api.md)
- [问题反馈](https://github.com/runningZ1/synology-nas/issues)

反馈时提供 CLI / Python / DSM 版本、脱敏命令、退出码和错误信封。不要提交密码、SID、Cookie、真实目录清单或含凭据的共享链接。新增接口请标明官方或社区来源，提供离线测试，并区分实现与设备验证结果。
