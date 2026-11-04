# 文件 API 参考

> 本文保留旧版 scripts/nas.py 的接口说明。0.2.0 已提供完整 CLI（含流式上传下载），请优先阅读 ../README.md、api-coverage.md 和 `synology-nas schema`。下面“脚本不实现上传下载”等描述仅指兼容旧脚本。

参数、版本和错误定义以[官方文档](https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf)及设备 SYNO.API.Info 为准。

下表 API 使用前缀 `SYNO.FileStation.`：

| API | 方法 | 常用参数 |
|---|---|---|
| List | list_share | offset, limit |
| List | list | folder_path, offset, limit |
| List | getinfo | path 数组 |
| Search | start/status/list/stop/clean | start 使用 folder_path、pattern；后续 taskid |
| CreateFolder | create | folder_path 数组、name 数组、force_parent |
| Rename | rename | path 数组、name 数组 |
| CopyMove | start/status/stop | path 数组、dest_folder_path、remove_src、overwrite |
| Delete | start/status/stop | path 数组、recursive |

复制使用 remove_src=false、overwrite=false；移动使用 remove_src=true。后台任务的具体方法按对应章节核对，不能假设所有任务都有 clean。

示例复制参数：

```json
{"path":["/media/inbox/a.txt"],"dest_folder_path":"/media/archive","remove_src":false,"overwrite":false}
```

脚本只处理 JSON/form 请求。Upload 使用 multipart/form-data，Download 返回二进制，应按官方文档另做流式实现，或使用已有授权的 SMB 挂载。大文件复制后检查大小/校验值；存在目标默认不覆盖。

## 本机兼容性实测

2026-11-04：Upload v2 的 multipart 请求将 SID 仅放表单时返回 119；增加 `Cookie: id=<SID>` 后上传成功。Cookie 只在请求内存中使用，不输出或持久化。文件 part 必须放最后；v2 overwrite 为 true/false，v3 改为 overwrite/skip，不能混用。

Download v2 使用 form POST、path JSON 数组、mode=download，已验证下载原始文件内容。Delete v2 另有阻塞方法 delete，返回时删除已完成；已实测用于小测试文件及目录。本 Skill 通用 call 当前只列出 start/status/stop，阻塞 delete 需在明确授权的调用脚本里实现。无需用后台任务启动响应代替完成验证。
