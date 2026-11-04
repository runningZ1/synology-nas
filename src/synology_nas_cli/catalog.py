"""Curated method registry. Discovery is availability, not authorization."""
FS_DOC = 'https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf'
COMMUNITY = 'https://github.com/N4S4/synology-api/tree/969216beecf08b25a1559046efb4c1f37fb8136c/synology_api'
CATALOG = {}

def register(api, cap, methods, source=FS_DOC):
    for method, effect, required, optional in methods:
        CATALOG[api + ':' + method] = {'api': api, 'method': method, 'version_cap': cap,
            'effect': effect, 'required': required.split(), 'optional': optional.split(),
            'source': source, 'is_idempotent': effect == 'read',
            'dry_run': effect not in {'read', 'compute'}, 'verification': 'documented; see acceptance report for live coverage'}

PAGE = 'offset limit sort_by sort_direction additional'
for name, cap, methods in [
    ('Info', 2, [('get','read','','')]),
    ('List',2,[('list_share','read','',PAGE),('list','read','folder_path', PAGE+' pattern filetype'),('getinfo','read','path','additional')]),
    ('Search',2,[('start','compute','folder_path','recursive pattern extension filetype size_from size_to mtime_from mtime_to crtime_from crtime_to atime_from atime_to'),('list','read','taskid',PAGE+' pattern filetype'),('stop','job','taskid',''),('clean','job','taskid','')]),
    ('VirtualFolder',2,[('list','read','type',PAGE)]),
    ('Favorite',2,[('list','read','',PAGE),('add','write','path name','index'),('delete','write','path',''),('edit','write','path name','index'),('replace_all','write','path name',''),('clear_broken','write','','')]),
    ('DirSize',2,[('start','compute','path',''),('status','read','taskid',''),('stop','job','taskid','')]),
    ('MD5',2,[('start','compute','file_path',''),('status','read','taskid',''),('stop','job','taskid','')]),
    ('CheckPermission',2,[('write','read','path filename','overwrite create_only')]),
    ('Sharing',3,[('getinfo','read','id',''),('list','read','',PAGE),('create','sharing','path','password date_expired date_available'),('delete','sharing','id',''),('edit','sharing','id','password date_expired date_available'),('clear_invalid','sharing','','')]),
    ('CreateFolder',2,[('create','file-write','folder_path name','force_parent additional')]),
    ('Rename',2,[('rename','file-write','path name','additional search_taskid')]),
    ('CopyMove',3,[('start','file-write','path dest_folder_path','overwrite remove_src accurate_progress search_taskid'),('status','read','taskid',''),('stop','job','taskid','')]),
    ('Delete',2,[('start','file-delete','path','recursive accurate_progress search_taskid'),('delete','file-delete','path','recursive search_taskid'),('status','read','taskid',''),('stop','job','taskid','')]),
    ('Extract',2,[('start','file-write','file_path dest_folder_path','overwrite keep_dir create_subfolder codepage password item_id'),('list','read','file_path',PAGE+' codepage password item_id'),('status','read','taskid',''),('stop','job','taskid','')]),
    ('Compress',3,[('start','file-write','path dest_file_path','level mode format password'),('status','read','taskid',''),('stop','job','taskid','')]),
    ('BackgroundTask',3,[('list','read','',PAGE+' api_filter'),('clear_finished','job','taskid','')]),
]:
    register('SYNO.FileStation.' + name, cap, methods)

for api, method, required, optional in [
    ('SYNO.Core.System','info','',''),
    ('SYNO.Core.System.Utilization','get','','type'),
    ('SYNO.Core.Storage.Disk','list','',''),
    ('SYNO.Core.Storage.Pool','list','',''),
    ('SYNO.Core.Storage.Volume','list','',''),
    ('SYNO.Storage.CGI.Storage','load_info','',''),
    ('SYNO.Core.Package','list','','additional ignore_hidden'),
    ('SYNO.Core.Service','get','',''),
    ('SYNO.Core.Share','list','','offset limit additional'),
    ('SYNO.Core.FileServ.SMB','get','',''),
    ('SYNO.Core.FileServ.NFS','get','',''),
    ('SYNO.Docker.Container','list','','offset limit type'),
    ('SYNO.Docker.Container.Resource','get','',''),
    ('SYNO.Backup.Service.NetworkBackup','get','',''),
    ('SYNO.FileStation.Snapshot','list','path','offset limit'),
    ('SYNO.FileStation.Worm','get','path',''),
]:
    register(api, 1, [(method,'read',required,optional)], COMMUNITY)

DS_DOC = 'https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/DownloadStation/All/enu/Synology_Download_Station_Web_API.pdf'
for api, cap, methods in [
    ('Info',1,[('getinfo','read','',''),('getconfig','read','','')]),
    ('Statistic',1,[('getinfo','read','','')]),
    ('Task',1,[('list','read','','offset limit additional'),('getinfo','read','id','additional')]),
    ('Schedule',1,[('getconfig','read','','')]),
]:
    register('SYNO.DownloadStation.'+api, cap, methods, DS_DOC)

BINARY = {
    'upload': {'api':'SYNO.FileStation.Upload','method':'upload','version_cap':2,'effect':'file-write','source':FS_DOC},
    'download': {'api':'SYNO.FileStation.Download','method':'download','version_cap':2,'effect':'read','source':FS_DOC},
    'thumbnail': {'api':'SYNO.FileStation.Thumb','method':'get','version_cap':2,'effect':'read','source':FS_DOC},
}
