# API 调研和覆盖

检查日期：2026-11-03（America/Los_Angeles）。CLI 0.2.0。

## 来源

- [群晖官方开发者入口](https://www.synology.com/en-us/support/developer)：公开提供 File Station、DSM 登录、Download Station、Surveillance Station、Virtual Machine Manager、Calendar、Office Suite 等开发资料。DiskStation CLI Guide 是 NAS 侧管理脚本资料，不等同于本地 Agent 文件 CLI。
- [File Station 官方 API](https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf)：本工具文件功能的主要依据。按语义独立实现，不复制整份文档。
- [DSM 登录官方指南](https://kb.synology.com/en-global/DG/DSM_Login_Web_API_Guide/2)：发现、认证、会话、错误处理。
- [Download Station 官方 API](https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/DownloadStation/All/enu/Synology_Download_Station_Web_API.pdf)：可选下载服务只读接口；此设备未公布这些接口，未自动安装套件。
- [N4S4/synology-api](https://github.com/N4S4/synology-api)，参考提交 `969216beecf08b25a1559046efb4c1f37fb8136c`，MIT。Python接口封装覆盖很多非公开稳定接口，特别参考其JSON编码、Storage Manager及容器只读请求设计。
- [kwent/syno](https://github.com/kwent/syno)，参考提交 `977941111a900af214612c8a432705abb8e9ed96`，Node封装及CLI。用于命令组织的比较，不引入其运行时。

两个仓库已下载到本次任务work目录，仅作参考，没有把整个第三方仓库装进Skill，也没有执行其代码或其安装脚本。CLI运行时使用标准库；接口参数名和业务协议来自官方/设备证据，社区来源明确标注，不冒充官方公开保证。

## 本机发现与能力等级

NAS实际返回629个API名称，其中SYNO.FileStation前缀46个，SYNO.Core396个，另有Storage、Docker、备份、资源监控等。原始快照保留在本机，不公开；使用 `synology-nas discover` 查询自己的设备。这是名称和版本发现，不含完整方法定义、权限承诺或兼容保证。

CLI提供31个命令，注册68个JSON方法与3个二进制方法，共39个API家族。官方File Station文档的19个家族均有对应入口。实现、设备公布、真实通过是三个不同等级；不能将“629名称”写成“629接口已全部实现”。

## File Station 覆盖

| API 家族 | CLI入口/方法 | 本机证据 |
|---|---|---|
| Info | info | 成功 |
| List | shares/list/stat/tree，list_share/list/getinfo | 分页、元数据、字段投影、目录导出成功 |
| Search | search，tasks results/stop/clean | 搜索及清理成功；按taskid分页 |
| VirtualFolder | mounts | CIFS挂载列表调用成功 |
| Favorite | favorites；raw list/add/delete/edit/replace_all/clear_broken | list成功，变更不实际提交 |
| Thumb | thumbnail --file | 二进制实现，未实测适配图片 |
| DirSize | size，tasks status/stop | 目录字节数、文件/目录数量成功 |
| MD5 | checksum，tasks status/stop | 与本地文件MD5一致 |
| CheckPermission | permissions | 不创建文件的权限检查成功 |
| Upload | upload | UTF-8文件上传、覆盖、读回成功；路由字段在前且Cookie认证 |
| Download | download --file | 原字节匹配、原子落盘、SHA256收据 |
| Sharing | links；raw getinfo/list/create/delete/edit/clear_invalid | list和create预览成功；真实链接变更未执行 |
| CreateFolder | mkdir | 创建、已存在noop、预览零变更通过 |
| Rename | rename | 改名并核对旧路径不存在 |
| CopyMove | copy/move；tasks status/stop | 任务完成与源目标状态核对成功 |
| Delete | delete；tasks status/stop | 精确确认、独立测试内容删除与清理成功 |
| Extract | archive list/extract；tasks status/stop | 上传ZIP、包内浏览、NAS解压、下载逐字节一致 |
| Compress | archive compress；tasks status/stop | 已按文档实现，但当前NAS start返回105，未成功验收，不自动改权限 |
| BackgroundTask | tasks list；raw clear_finished | list成功；只按明确ID管理，不全局清理 |

家族计数由注册表中的官方来源API名称集合生成；以 `schema` 的真实集合为准。

长尾方法通过 `api call API METHOD --params-file FILE`，默认预览、字段白名单、分页有界。通用文件写方法被禁止，避免绕过scope，文件任务走typed命令。二进制不走JSON raw方法。参数、版本上限、effect、来源URL可从schema/api catalog取得。

## 额外只读功能

| 能力 | 实现 | 本机 |
|---|---|---|
| 系统/资源 | Core.System info，System.Utilization get | 成功 |
| 磁盘/存储池/卷 | Storage.CGI.Storage load_info，并投影disks/storagePools/volumes | 成功；避免旧Core.Storage接口兼容问题 |
| 套件 | Core.Package list | 成功 |
| 容器及资源 | Docker.Container list，Container.Resource get | 成功，type/limit有界 |
| SMB/NFS | FileServ.SMB/NFS get | 成功 |
| 备份服务状态 | Backup.Service.NetworkBackup get | 成功；不是备份任务创建/恢复 |
| 快照/WORM信息 | FileStation.Snapshot list / Worm get | 受控raw注册；未验证数据存在及权限 |
| Download Station | Info/Statistic/Task/Schedule查询 | 已注册官方方法；套件未安装，明确unsupported |

Core、Storage、Docker及额外Snapshot/WORM来源是社区与设备接口，非官方公开API稳定性承诺。没有实现重启/关机/磁盘创建删除/账户ACL/网络公网/套件安装/容器执行/备份恢复等管理员变更。没有凭一个API名称猜测方法并自动运行。

## 后续扩展边界

Calendar、Office、VMM、Surveillance等官方文档可作后续适配依据，但此NAS没有对应套件和真实验收环境，不生成虚假的可用命令。需要新增时先安装/授权由用户明确决定，再验证该套件API和权限；当前工具不会为扩大覆盖率自动安装或开放服务。
