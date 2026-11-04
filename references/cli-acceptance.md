# CLI 0.2.0 验收记录

日期：2026-11-03（America/Los_Angeles）。环境：Windows、Python3.12。以下是公开发布前的历史验收摘要。路径已改为通用示例，设备原始响应不公开。当前自动测试结果以实际运行和 GitHub Actions 为准。

## 自动测试

运行：`python -m unittest discover -s <Skill目录>/tests -v`。

39项通过。覆盖：所有命令help、schema与注册表一致、JSON/JSONL输出纯净、错误退出映射、字段投影、分页、范围和软链接逃逸、精确删除确认、预览零变更、重复mkdir noop、未知结果保留taskid、raw认证/文件写入绕过拒绝、嵌套压缩包路径穿越、HTTP拒绝登录、截止时间、真实本地HTTP响应解析与503分类、下载大小限制、临时文件清理、原子no-clobber、SHA256、秘密脱敏、控制字符与shell元字符作为数据。

本地HTTP服务是测试夹具，仅用于验证传输/错误/二进制契约，不是NAS生产证据。

## 真实NAS

连接HTTPS5001，临时显式关闭证书校验；没有改变NAS证书或安全设置。凭据仅在测试进程内存和环境中使用，没有保存。报告不含凭据/会话。

最后完整运行51个命令结果，50个成功，1个预期记录的权限拒绝：`archive compress`被当前设备返回105。成功包含：

- 认证、Info、共享分页（两页）、目录字段投影、stat、全共享两层有界树导出。
- 收藏/共享链接/虚拟挂载/后台任务读取，创建权限检查。
- 系统信息、CPU/内存资源、Storage Manager、磁盘、存储池、卷、套件、服务、容器、容器资源、SMB、NFS、备份服务状态。
- 新建目录前预览并验证不存在；提交创建；重复创建noop。
- 上传含中文文件、下载逐字节一致；覆盖上传并再次下载一致。
- 远程MD5与本地MD5一致；目录容量计算。
- 文件搜索命中、清理本次搜索临时任务。
- 复制、重命名、移动并等待完成和核对源目标。
- 本地构造ZIP后上传，NAS包内浏览、NAS解压、下载逐字节一致。
- 共享链接创建仅预览，不创建真实链接。
- 删除测试文件、唯一测试目录并再次列目录确认不存在。

独立测试在专用共享下的唯一新建目录进行，内容已清理，业务文件未变更。原始记录仅保留在本机，不随公开仓库发布。

集成时发现并修复：multipart路由字段顺序；API公布requestFormat=JSON时字符串业务参数编码；Cookie认证；旧Core.Storage接口与Storage Manager兼容；容器列表type参数。先前失败测试目录也已清理。没有通过自动修改权限“修好”压缩错误。

## 已安装入口与兼容

安装：`python -m pip install --no-deps --no-build-isolation -e <Skill目录>`，成功。

实测安装后的 `synology-nas.EXE`：version、auth status（口令由stdin传入）、shares分页。分别捕获stdout/stderr，stdout可解析JSON、stderr空，exit0。`downloads info`因套件未安装返回UNSUPPORTED/exit3，符合约定。旧 `scripts/nas.py --url ... --insecure shares --limit 2` 仍返回旧success/data信封并exit0。

另构建wheel，使用 `python -m venv --without-pip` 创建独立环境，再从本地wheel离线安装，无运行时第三方依赖。该环境的独立synology-nas.exe执行version与真实NAS shares --limit 2均exit0、JSON可解析、返回2条共享记录。此证据验证Windows wheel安装，不代表其他平台通过。

## 未验收和限制

- 压缩start当前返回105，命令实现和预览存在，但不能宣称本机可压缩。
- 缩略图、快照、WORM未挑选业务文件作真实验证；收藏变更、真实分享创建/编辑/撤销、全局清理未执行，避免更改用户设置或访问范围。
- 其他未安装套件（Download Station、Calendar、Office、VMM、Surveillance等）未自动安装，未做虚假验收。
- TB级传输、并发修改、链路中断恢复、其他操作系统未实测。流式上传不提供断点续传；发生未知结果需先核对目标。
- HTTPS证书信任仍待单独处理；insecure只在单次诊断中显式启用。
- CLI级测试通过不代表生产部署、全部629个设备API或所有共享目录权限验收。
