import hashlib
import json
import os
import posixpath
import tempfile
import time
from collections import deque
from pathlib import Path

from .protocol import Failure
from .catalog import CATALOG

FIELDS = {'path', 'name', 'isdir', 'additional'}

def remote_path(value):
    if not isinstance(value, str) or not value.startswith('/') or value == '/' or '\\' in value or any(ord(c)<32 or 127<=ord(c)<=159 or '\u202a'<=c<='\u202e' or '\u2066'<=c<='\u2069' or c in '\u200b\u200c\u200d\ufeff' for c in value):
        raise Failure('INVALID_INPUT', 'Remote path must start with /SHARE and contain no control characters or backslash')
    if any(p in {'.', '..', ''} for p in value[1:].split('/')):
        raise Failure('INVALID_INPUT', 'Remote path must be normalized; no empty, . or .. segments')
    return value

def filename(value):
    remote_path('/share/' + value)
    if '/' in value or '"' in value:
        raise Failure('INVALID_INPUT', 'Name must be one path component without quotes')
    return value

def within(path, scope):
    path, scope = remote_path(path), remote_path(scope)
    if path != scope and not path.startswith(scope+'/'):
        raise Failure('INVALID_INPUT', 'Path is outside --scope', details={'path':path,'scope':scope})
    return path

def project(items, fields):
    if not fields: return items
    keys = set(fields.split(',')) | {'path'}
    if keys - FIELDS:
        raise Failure('INVALID_INPUT', 'Unknown fields', details={'allowed':sorted(FIELDS)})
    return [{k:v for k,v in item.items() if k in keys} for item in items]

def page(c, api, method, params, *, key='files', cap=2, limit=100, offset=0, fields=None):
    result = c.call(api, method, dict(params, offset=offset, limit=limit), cap=cap)
    items = result.get(key, [])
    total = result.get('total', len(items)+offset)
    next_offset = offset+len(items) if offset+len(items)<total else None
    return {'items':project(items,fields), 'pagination':{'limit':limit,'offset':offset,'returned':len(items),'total':total,'truncated':next_offset is not None,'next_offset':next_offset}, **{k:v for k,v in result.items() if k not in {key,'total','offset'}}}

def job(c, api, params, *, cap=2, wait=0, status_method='status'):
    result = c.call(api,'start',params,cap=cap,mutation=api not in {'SYNO.FileStation.Search','SYNO.FileStation.DirSize','SYNO.FileStation.MD5'})
    taskid = result['taskid']
    end = time.monotonic()+wait
    status = result
    while wait and time.monotonic()<end:
        try:
            c.remaining()
            status = c.call(api,status_method,{'taskid':taskid},cap=cap)
        except Failure as exc:
            exc.details.update(taskid=taskid,api=api)
            exc.next_actions=[{'command':f'synology-nas tasks status {api} {taskid}'}]
            raise
        if status.get('finished'):
            if status.get('errors'):
                raise Failure('BACKEND_ERROR','Background task finished with file errors',details={'taskid':taskid,'errors':status['errors']},outcome='unknown')
            break
        time.sleep(min(.3,max(0,end-time.monotonic())))
    return {'taskid':taskid,'api':api,'state':'finished' if status.get('finished') else 'running','status':status,
            'next_action':{'command':f'synology-nas tasks status {api} {taskid}'}}

def ensure_folder(c,path):
    info=c.stat(path)
    if not info['isdir']: raise Failure('INVALID_INPUT','Expected a directory',details={'path':path})
    return info

def scope_check(c, paths, scope):
    if not scope: raise Failure('INVALID_INPUT','File mutations require --scope /SHARE/authorized-root')
    scope=remote_path(scope)
    root_info=ensure_folder(c,scope)
    real_root=root_info.get('additional',{}).get('real_path')
    for path in paths:
        within(path,scope)
        if len(path.strip('/').split('/'))<2:
            raise Failure('INVALID_INPUT','Shared folder roots cannot be mutated')
        # Resolve nearest existing ancestor to reject paths through mounted/symlink escapes.
        probe=path
        while True:
            item=c.exists(probe)
            if item: break
            probe=posixpath.dirname(probe)
            if probe=='/': raise Failure('NOT_FOUND','No existing parent')
        real=item.get('additional',{}).get('real_path')
        if not real_root or not real:
            raise Failure('UNSUPPORTED','NAS did not return real_path needed for scoped mutation')
        if real!=real_root and not real.startswith(real_root.rstrip('/')+'/'):
            raise Failure('INVALID_INPUT','Resolved path escapes scope',details={'path':path})

def mutation(c, action, *, path, scope, destination=None, source=None, overwrite=False, recursive=False, commit=False, confirm=None, wait=10):
    path=remote_path(path)
    paths=[path]+([remote_path(destination)] if destination else [])
    scope_check(c,paths,scope)
    current=c.exists(path)
    plan={'action':action,'path':path,'destination':destination,'scope':scope,'overwrite':overwrite,'recursive':recursive,'state':'planned','dry_run':not commit}
    target=None
    if action=='mkdir':
        ensure_folder(c,posixpath.dirname(path))
        if current:
            if not current['isdir']: raise Failure('CONFLICT','Non-directory already exists')
            return dict(plan,state='noop')
        api,method,params='SYNO.FileStation.CreateFolder','create',{'folder_path':[posixpath.dirname(path)],'name':[posixpath.basename(path)],'force_parent':False}
        target=path
    elif action=='delete':
        if not current: return dict(plan,state='noop')
        if confirm!=path and commit: raise Failure('INVALID_INPUT','Delete commit requires --confirm equal to the exact path')
        if current['isdir'] and not recursive:
            listing=c.call('SYNO.FileStation.List','list',{'folder_path':path,'limit':1,'offset':0})
            if listing.get('total',len(listing.get('files',[]))): raise Failure('CONFLICT','Directory is not empty; --recursive required')
        api,method,params='SYNO.FileStation.Delete','start',{'path':[path],'recursive':recursive}
    elif action in {'rename','copy','move'}:
        if not current: raise Failure('NOT_FOUND','Source does not exist',details={'path':path})
        ensure_folder(c,posixpath.dirname(destination))
        target=destination
        if path==destination: return dict(plan,state='noop')
        if destination.startswith(path+'/') or (action in {'copy','move'} and posixpath.basename(path)!=posixpath.basename(destination)):
            raise Failure('INVALID_INPUT','copy/move require destination directory preserving basename; cannot target a source descendant')
        if c.exists(destination): raise Failure('CONFLICT','Destination exists; overwrite is not supported for rename/copy/move')
        if action=='rename':
            if posixpath.dirname(path)!=posixpath.dirname(destination): raise Failure('INVALID_INPUT','Rename must stay in the same directory; use move')
            api,method,params='SYNO.FileStation.Rename','rename',{'path':[path],'name':[posixpath.basename(destination)]}
        else:
            api,method,params='SYNO.FileStation.CopyMove','start',{'path':[path],'dest_folder_path':posixpath.dirname(destination),'remove_src':action=='move','overwrite':False}
    elif action=='upload':
        ensure_folder(c,posixpath.dirname(path))
        if current and (not overwrite or current['isdir']): raise Failure('CONFLICT','Remote destination exists; file replacement requires --overwrite')
        source=Path(source)
        if not source.is_file(): raise Failure('INVALID_INPUT','Upload source must be a regular local file')
        filename(posixpath.basename(path))
        plan.update(local_file=str(source.absolute()),bytes=source.stat().st_size)
        if not commit: return plan
        c.upload(source,posixpath.dirname(path),posixpath.basename(path),overwrite=overwrite)
        info=c.stat(path)
        if info.get('additional',{}).get('size')!=source.stat().st_size:
            raise Failure('BACKEND_ERROR','Upload size verification failed',outcome='unknown')
        return dict(plan,state='committed',dry_run=False,verified=info)
    else: raise Failure('INVALID_INPUT','Unknown mutation')
    if not commit: return plan
    if method=='start':
        result=job(c,api,params,cap=3 if action in {'copy','move'} else 2,wait=wait)
        plan.update(result)
        if result['state']!='finished': return dict(plan,dry_run=False)
    else:
        c.call(api,method,params,mutation=True)
    if action=='delete':
        if c.exists(path): raise Failure('BACKEND_ERROR','Deletion not reflected',outcome='unknown')
    else:
        c.stat(target)
        if action in {'rename','move'} and c.exists(path): raise Failure('BACKEND_ERROR','Old source still present',outcome='unknown')
    return dict(plan,state='committed',dry_run=False,verified=True)

def tree(c,roots,*,depth=3,max_dirs=500,max_entries=5000):
    queue=deque((remote_path(r),0) for r in roots)
    records,errors,skipped=[],[],[]
    directory_count=0
    while queue and directory_count<max_dirs and len(records)<max_entries:
        path,level=queue.popleft()
        offset=0
        try:
            directory_count+=1
            while True:
                c.remaining()
                allowance=min(500,max_entries-len(records))
                if allowance<=0:
                    queue.appendleft((path,level)); break
                batch=c.call('SYNO.FileStation.List','list',{'folder_path':path,'limit':allowance,'offset':offset})
                items=batch.get('files',[])
                for item in items:
                    records.append(dict(item,depth=level+1))
                    if item.get('isdir'):
                        if item['name'] in {'#recycle','#snapshot','@eaDir'}: skipped.append({'path':item['path'],'reason':'excluded'})
                        elif level+1<depth: queue.append((item['path'],level+1))
                        else: skipped.append({'path':item['path'],'reason':'depth'})
                offset+=len(items)
                if not items or offset>=batch.get('total',offset): break
        except Failure as exc:
            if exc.code in {'NETWORK_ERROR','DEADLINE'}: raise
            errors.append({'path':path,'code':exc.code})
    return {'roots':roots,'items':records,'directories_scanned':directory_count,'entries':len(records),
            'complete':not queue and not errors and not any(s['reason']=='depth' for s in skipped),
            'truncated':bool(queue) or any(s['reason']=='depth' for s in skipped),
            'pending_directories':[p for p,_ in queue], 'skipped':skipped,'errors':errors,
            'limits':{'depth':depth,'max_dirs':max_dirs,'max_entries':max_entries},
            'note':'Completeness excludes recycle/snapshot/index directories; live scans are not atomic snapshots.'}

def export_json(value,file):
    target=Path(file).absolute()
    target.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(value,ensure_ascii=True,indent=2)+'\n').encode('utf-8')
    name=None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as f:
            name=f.name; f.write(raw)
        os.replace(name,target); name=None
    finally:
        if name: os.unlink(name)
    return {'file':str(target),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

def validate_archive(c,path,*,max_items=10000):
    """Inspect nested archive entries before extraction; reject traversal and output floods."""
    queue=deque([None]); seen=set(); count=0
    while queue:
        item_id=queue.popleft(); offset=0
        while True:
            params={'file_path':path,'offset':offset,'limit':min(500,max_items-count+1)}
            if item_id is not None:params['item_id']=item_id
            data=c.call('SYNO.FileStation.Extract','list',params)
            entries=data.get('items',[])
            for item in entries:
                count+=1
                if count>max_items:raise Failure('INVALID_INPUT','Archive has too many entries for safe preflight; maximum 10000')
                relative=item.get('path',item.get('name','')).replace('\\','/')
                if relative.startswith('/') or any(segment=='..' for segment in relative.split('/')) or ':' in relative or any(ord(ch)<32 for ch in relative):
                    raise Failure('INVALID_INPUT','Archive contains unsafe paths; extraction refused')
                if item.get('is_dir'):
                    child=item.get('item_id',item.get('itemid'))
                    if child is None:raise Failure('INVALID_RESPONSE','Archive directory has no item ID for traversal checks')
                    if child not in seen:seen.add(child);queue.append(child)
            offset+=len(entries)
            if not entries or offset>=data.get('total',offset):break
    return count

def api_call(c,api,method,params,args):
    spec=CATALOG.get(api+':'+method)
    if not spec: raise Failure('UNSUPPORTED','API method is not in the curated catalog; use api catalog')
    required,allowed=set(spec['required']),set(spec['required']+spec['optional'])
    if not isinstance(params,dict) or required-set(params) or set(params)-allowed:
        raise Failure('INVALID_INPUT','Invalid API parameters',details={'required':sorted(required),'allowed':sorted(allowed)})
    params=dict(params)
    for key in required:
        if params[key] is None or params[key]=='' or params[key]==[]:
            raise Failure('INVALID_INPUT','Required API parameter cannot be empty',details={'field':key})
    if api=='SYNO.FileStation.Favorite' and method=='replace_all':
        if not isinstance(params['path'],list) or not isinstance(params['name'],list) or len(params['path'])!=len(params['name']):
            raise Failure('INVALID_INPUT','replace_all requires equally-sized path and name arrays')
    if 'limit' in allowed:
        params.setdefault('limit',100)
        params.setdefault('offset',0)
        if isinstance(params['limit'],bool) or not isinstance(params['limit'],int) or not 1<=params['limit']<=1000 or not isinstance(params['offset'],int) or params['offset']<0:
            raise Failure('INVALID_INPUT','API pagination requires integer limit 1..1000 and offset >=0')
    if any(k in params for k in {'password','passwd','_password'}):
        raise Failure('INVALID_INPUT','Use typed commands for secret input; raw secret fields are not accepted')
    effect=spec['effect']
    if effect in {'file-write','file-delete'}:
        raise Failure('INVALID_INPUT','Use typed mkdir/rename/copy/move/delete/upload/archive commands for file mutations')
    if effect=='sharing' and getattr(args,'commit',False) and not getattr(args,'allow_sharing',False):
        raise Failure('INVALID_INPUT','Sharing changes require explicit --allow-sharing and --commit')
    if effect=='sharing' and method=='create':
        scope=getattr(args,'scope',None)
        if not scope:raise Failure('INVALID_INPUT','Sharing creation requires --scope')
        values=params['path'] if isinstance(params['path'],list) else [params['path']]
        for value in values:within(value,scope)
    for key in ('path','folder_path','file_path','dest_folder_path','dest_file_path'):
        if key in params:
            values=params[key] if isinstance(params[key],list) else [params[key]]
            for value in values:
                remote_path(value)
                c.stat(value)
    if effect not in {'read','compute'} and not getattr(args,'commit',False):
        return {'state':'planned','dry_run':True,'api':api,'method':method,'params':params,'effect':effect}
    return c.call(api,method,params,cap=spec['version_cap'],mutation=effect not in {'read','compute'})
