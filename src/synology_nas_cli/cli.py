import argparse
import json
import os
import posixpath
import sys
import tempfile
import time
from pathlib import Path

from . import __version__
from .backend import Client
from .catalog import CATALOG, BINARY
from .protocol import ERRORS, Failure, emit, sanitize
from .service import remote_path, filename, within, page, project, mutation, tree, job, ensure_folder, scope_check, export_json, api_call, validate_archive

class Parser(argparse.ArgumentParser):
    def error(self,message):
        raise Failure('INVALID_INPUT',message,next_actions=[{'command':'synology-nas --help'}])

def globals_parser():
    p=Parser(add_help=False,argument_default=argparse.SUPPRESS,allow_abbrev=False)
    for name in ['url','user','config','password-file','ca-file','scope','fields']:
        p.add_argument('--'+name)
    for name in ['password-stdin','insecure','quiet','no-input','no-color','commit','dry-run','allow-sharing']:
        p.add_argument('--'+name,action='store_true')
    p.add_argument('--timeout',type=float)
    p.add_argument('--deadline',type=float)
    p.add_argument('--output',choices=['json','jsonl','text'])
    return p

def build_parser():
    common=globals_parser()
    p=Parser(prog='synology-nas',parents=[common],allow_abbrev=False,
             description='Headless Synology NAS CLI. JSON by default; writes preview unless --commit. Credentials never saved.',
             epilog='Example: synology-nas list /media --limit 20; synology-nas tree --depth 2 --save structure.json')
    sub=p.add_subparsers(dest='command',required=True,parser_class=Parser)
    registry={}
    def cmd(name,help):
        q=sub.add_parser(name,parents=[common],help=help,description=help,allow_abbrev=False)
        registry[name]=q
        return q
    def paging(q):
        q.add_argument('--limit',type=int,default=100,help='Page size, 1..1000; default 100')
        q.add_argument('--offset',type=int,default=0)
    cmd('version','Show tool and machine schema versions')
    cmd('schema','Machine-readable commands, flags, API method catalog and safety contract')
    cmd('errors','Machine-readable error and exit registry')
    cmd('doctor','Anonymous connection/API diagnostics; never persists credentials')
    q=cmd('discover','Discover APIs advertised by this device; bounded page')
    q.add_argument('--prefix',default='SYNO.'); paging(q)
    q=cmd('auth','Validate supplied credentials; no session persistence')
    q.add_argument('action',choices=['status'])
    cmd('info','File Station capability and hostname information')
    q=cmd('shares','List accessible shared folders'); paging(q)
    q=cmd('list','List one folder page; --pattern supports DSM glob matching')
    q.add_argument('path'); q.add_argument('--pattern'); paging(q)
    q=cmd('stat','Get file/directory metadata, size, permissions and real path'); q.add_argument('path')
    q=cmd('tree','Read bounded tree; export large results with --save FILE; never scan forever')
    q.add_argument('path',nargs='?'); q.add_argument('--depth',type=int,default=3)
    q.add_argument('--max-dirs',type=int,default=500); q.add_argument('--max-entries',type=int,default=5000)
    q.add_argument('--save',help='JSON export path; - returns bounded data on stdout')
    q=cmd('search','Start recursive server-side name search; return bounded results and resumable task ID')
    q.add_argument('path'); q.add_argument('pattern'); q.add_argument('--wait',type=float,default=5); paging(q)
    q=cmd('mkdir','Create one directory; existing directory is noop; default preview')
    q.add_argument('path')
    q=cmd('rename','Rename in the same folder; default preview')
    q.add_argument('path'); q.add_argument('name')
    for name in ['copy','move']:
        q=cmd(name,f'{name.title()} source into an existing destination directory; no overwrite; default preview')
        q.add_argument('path'); q.add_argument('destination'); q.add_argument('--wait',type=float,default=10)
    q=cmd('delete','Delete one scoped target; --commit requires --confirm EXACT_PATH; missing target is noop')
    q.add_argument('path'); q.add_argument('--recursive',action='store_true'); q.add_argument('--confirm')
    q.add_argument('--wait',type=float,default=10)
    q=cmd('upload','Stream local file or stdin (-) to an exact NAS file path; default preview')
    q.add_argument('source'); q.add_argument('path'); q.add_argument('--overwrite',action='store_true')
    q.add_argument('--max-bytes',type=int,default=1073741824)
    for name in ['download','thumbnail']:
        q=cmd(name,'Download binary data atomically to --file; stdout always contains a JSON receipt')
        q.add_argument('path'); q.add_argument('--file',required=True)
        q.add_argument('--max-bytes',type=int,default=1073741824 if name=='download' else 10485760)
        q.add_argument('--overwrite-local',action='store_true')
    for name in ['size','checksum']:
        q=cmd(name,'Compute NAS directory size/counts' if name=='size' else 'Compute NAS file MD5 integrity checksum')
        q.add_argument('path'); q.add_argument('--wait',type=float,default=10)
    q=cmd('favorites','List/add/remove/rename user favorites; writes preview by default')
    q.add_argument('action',choices=['list','add','remove','rename']); q.add_argument('path',nargs='?'); q.add_argument('--name'); paging(q)
    q=cmd('links','Inspect/create/revoke share links; creation broadens access and requires --allow-sharing --commit')
    q.add_argument('action',choices=['list','get','create','delete']); q.add_argument('target',nargs='?')
    q.add_argument('--expires',help='DSM date_expired: YYYY-MM-DD'); q.add_argument('--link-password-file'); paging(q)
    q=cmd('mounts','List existing virtual mount points; does not mount or unmount anything')
    q.add_argument('--type',choices=['cifs','nfs','iso'],default='cifs'); paging(q)
    q=cmd('permissions','Check ability to create named file without creating it')
    q.add_argument('path'); q.add_argument('name')
    q=cmd('archive','List archive contents, compress or extract on NAS; mutations require scope and commit')
    q.add_argument('action',choices=['list','compress','extract']); q.add_argument('path')
    q.add_argument('--destination'); q.add_argument('--wait',type=float,default=10); paging(q)
    q=cmd('tasks','List File Station jobs, inspect/cancel/clean a specific task; no global cancellation')
    q.add_argument('action',choices=['list','status','results','stop','clean']); q.add_argument('api',nargs='?'); q.add_argument('taskid',nargs='?'); paging(q)
    q=cmd('system','Read system info, resource utilization, storage, packages, services, containers and file services')
    q.add_argument('resource',choices=['info','utilization','storage','disks','pools','volumes','packages','services','containers','container-resources','smb','nfs','backup'])
    q=cmd('downloads','Read Download Station info/tasks/statistics; missing package returns unsupported')
    q.add_argument('resource',choices=['info','tasks','statistics']); paging(q)
    q=cmd('api','Inspect curated API methods or invoke an allowlisted JSON method; file mutations use typed commands')
    q.add_argument('action',choices=['catalog','call']); q.add_argument('api',nargs='?'); q.add_argument('method',nargs='?')
    q.add_argument('--params-file',help='UTF-8 JSON object or - for stdin'); q.add_argument('--prefix',default=''); paging(q)
    return p,registry

def config(args):
    default=Path(__file__).resolve().parents[2]/'config.json'
    path=Path(getattr(args,'config',os.getenv('SYNOLOGY_CONFIG',str(default))))
    cfg={}
    if path.exists():
        try: cfg=json.loads(path.read_text(encoding='utf-8-sig'))
        except (ValueError,OSError): raise Failure('INVALID_INPUT','Config must be readable UTF-8 JSON') from None
        if not isinstance(cfg,dict) or set(cfg)-{'url','user','ca_file'}:
            raise Failure('INVALID_INPUT','Config supports only url, user and ca_file; no secrets')
    elif hasattr(args,'config'): raise Failure('NOT_FOUND','Explicit config file does not exist')
    get=lambda flag,env,key,default=None: getattr(args,flag,None) or os.getenv(env) or cfg.get(key,default)
    values={'url':get('url','SYNOLOGY_URL','url'),'user':get('user','SYNOLOGY_USER','user'),
            'ca_file':get('ca_file','SYNOLOGY_CA_FILE','ca_file')}
    if not values['url']: raise Failure('INVALID_INPUT','Set --url or SYNOLOGY_URL')
    if getattr(args,'password_stdin',False) and getattr(args,'password_file',None):
        raise Failure('INVALID_INPUT','Choose password-stdin or password-file')
    if getattr(args,'password_stdin',False):
        if sys.stdin.isatty(): raise Failure('INVALID_INPUT','password-stdin requires a pipe; interactive prompts disabled')
        password=sys.stdin.buffer.read(65537)
        if len(password)>65536: raise Failure('INVALID_INPUT','Password input too long')
        values['password']=password.decode('utf-8').rstrip('\r\n')
    elif getattr(args,'password_file',None): values['password']=read_secret(args.password_file)
    else: values['password']=os.getenv('SYNOLOGY_PASSWORD')
    values.update(otp=os.getenv('SYNOLOGY_OTP'),insecure=getattr(args,'insecure',False),timeout=getattr(args,'timeout',30),deadline=getattr(args,'deadline',120))
    return values

def read_secret(path):
    if Path(path).stat().st_size>65536: raise Failure('INVALID_INPUT','Secret file exceeds 64 KiB')
    return Path(path).read_text(encoding='utf-8-sig').rstrip('\r\n')

def schema(parser,registry):
    def flags(p):
        return [{'names':a.option_strings or [a.dest],'type':'boolean' if isinstance(a,(argparse._StoreTrueAction,argparse._StoreFalseAction)) else getattr(a.type,'__name__','string'),'required':a.required,'choices':list(a.choices) if a.choices is not None and not isinstance(a.choices,dict) else None,'default':None if a.default==argparse.SUPPRESS else a.default} for a in p._actions if not isinstance(a,argparse._SubParsersAction)]
    writes={'mkdir','rename','copy','move','delete','upload','archive','favorites','links','tasks','api'}
    return {'tool_version':__version__,'schema_version':'1.0','commands':[{'name':n,'description':p.description,'arguments':flags(p),'effect':'mixed; inspect action/API effect' if n in writes else 'read/compute','dry_run':n in writes,'example':f'synology-nas {n} --help'} for n,p in registry.items()],
            'global_flags':flags(parser),'api_methods':list(CATALOG.values()),'binary_commands':BINARY,
            'output':{'formats':['json','jsonl','text'],'default':'json','envelope':{'schema_version':'1.0','ok':'boolean','type':'result|error','data':'object (success only)','error':'object (error only)','meta':'request_id,duration_ms,tls_verified,logout_confirmed'},'jsonl':'one terminal envelope; no progress events','errors':'stdout'},
            'limits':{'page_default':100,'page_max':1000,'tree_default_dirs':500,'tree_max_dirs':10000,'tree_default_entries':5000,'tree_max_entries':100000,'timeout_seconds':30,'deadline_seconds':120},
            'projection':{'commands':['list','shares','search','tasks results'],'fields':['path','name','isdir','additional'],'preserved':['path']},
            'stdin':{'upload source -':'binary spool bounded by max-bytes','api --params-file -':'JSON object up to 1 MiB','password-stdin':'UTF-8 secret up to 64 KiB; cannot share stdin'},
            'safety':{'writes':'preview by default; --commit required','scope':'required on typed file mutations; all source/destination paths checked','delete':'--confirm EXACT_PATH','sharing':'--allow-sharing plus --commit','retries':'none; unknown outcome requires reconciliation','credentials':'not persisted; each command logs out','no_input':True},
            'exit_codes':{k:{'exit':v[0],'retryable':v[1]} for k,v in ERRORS.items()}}

SYSTEM={
 'info':('SYNO.Core.System','info'), 'utilization':('SYNO.Core.System.Utilization','get'),
 'storage':('SYNO.Storage.CGI.Storage','load_info'), 'disks':('SYNO.Core.Storage.Disk','list'),
 'pools':('SYNO.Core.Storage.Pool','list'),'volumes':('SYNO.Core.Storage.Volume','list'),
 'packages':('SYNO.Core.Package','list'),'services':('SYNO.Core.Service','get'),
 'containers':('SYNO.Docker.Container','list'),'container-resources':('SYNO.Docker.Container.Resource','get'),
 'smb':('SYNO.Core.FileServ.SMB','get'),'nfs':('SYNO.Core.FileServ.NFS','get'),
 'backup':('SYNO.Backup.Service.NetworkBackup','get')}

def execute(args,c):
    name=args.command
    paging={'limit':getattr(args,'limit',100),'offset':getattr(args,'offset',0),'fields':getattr(args,'fields',None)}
    commit=getattr(args,'commit',False)
    scope=getattr(args,'scope',None)
    if name=='auth':
        c.call('SYNO.FileStation.Info','get')
        return {'authenticated':True,'user':c.user,'credential_source':'stdin' if getattr(args,'password_stdin',False) else 'file' if getattr(args,'password_file',None) else 'environment','session_persisted':False}
    if name=='info': return c.call('SYNO.FileStation.Info','get')
    if name=='shares': return page(c,'SYNO.FileStation.List','list_share',{},key='shares',**paging)
    if name=='list':
        path=remote_path(args.path)
        params={'folder_path':path}
        if args.pattern: params['pattern']=args.pattern
        return dict(page(c,'SYNO.FileStation.List','list',params,**paging),path=path)
    if name=='stat': return c.stat(remote_path(args.path))
    if name=='tree':
        if args.path: roots=[remote_path(args.path)]
        else:
            roots=[]; offset=0
            while True:
                r=page(c,'SYNO.FileStation.List','list_share',{},key='shares',limit=1000,offset=offset)
                roots.extend(i['path'] for i in r['items'])
                if r['pagination']['next_offset'] is None: break
                offset=r['pagination']['next_offset']
        result=tree(c,roots,depth=args.depth,max_dirs=args.max_dirs,max_entries=args.max_entries)
        if args.save and args.save!='-':
            receipt=export_json(result,args.save)
            return {**receipt,**{k:v for k,v in result.items() if k not in {'items','skipped','pending_directories'}},'pending_directories':len(result['pending_directories'])}
        return result
    if name in {'mkdir','rename','copy','move','delete','upload'}:
        path=remote_path(args.path)
        kwargs={'scope':scope,'commit':commit,'wait':getattr(args,'wait',10)}
        if name=='rename': kwargs['destination']=posixpath.join(posixpath.dirname(path),filename(args.name))
        if name in {'copy','move'}:
            ensure_folder(c,remote_path(args.destination))
            kwargs['destination']=posixpath.join(args.destination,posixpath.basename(path))
        if name=='delete': kwargs.update(confirm=args.confirm,recursive=args.recursive)
        if name=='upload':
            if args.source=='-':
                if getattr(args,'password_stdin',False): raise Failure('INVALID_INPUT','Upload and password cannot both use stdin')
                with tempfile.TemporaryDirectory(prefix='nascli-') as tmp:
                    source=Path(tmp)/'upload'
                    with source.open('wb') as f:
                        total=0
                        while True:
                            chunk=sys.stdin.buffer.read(min(1048576,args.max_bytes-total+1))
                            if not chunk: break
                            total+=len(chunk)
                            if total>args.max_bytes: raise Failure('INVALID_INPUT','stdin exceeds max-bytes')
                            f.write(chunk)
                    return mutation(c,name,path=path,source=source,overwrite=args.overwrite,**kwargs)
            if Path(args.source).stat().st_size>args.max_bytes: raise Failure('INVALID_INPUT','Source exceeds max-bytes')
            kwargs.update(source=args.source,overwrite=args.overwrite)
        return mutation(c,name,path=path,**kwargs)
    if name in {'download','thumbnail'}:
        path=remote_path(args.path); c.stat(path)
        if args.file=='-': raise Failure('INVALID_INPUT','Binary stdout is disabled to preserve JSON; use --file PATH')
        api='SYNO.FileStation.'+('Download' if name=='download' else 'Thumb')
        params={'path':[path],'mode':'download'} if name=='download' else {'path':path,'size':'medium','rotate':0}
        return c.download(api,'download' if name=='download' else 'get',params,args.file,max_bytes=args.max_bytes,overwrite=args.overwrite_local)
    if name in {'search','size','checksum'}:
        path=remote_path(args.path); c.stat(path)
        if name=='search':
            api='SYNO.FileStation.Search'
            r=c.call(api,'start',{'folder_path':[path],'pattern':args.pattern,'recursive':True})
            taskid=r['taskid']; end=time.monotonic()+args.wait
            while True:
                result=page(c,api,'list',{'taskid':taskid},**paging)
                if result.get('finished') or time.monotonic()>=end: break
                time.sleep(.3)
            return dict(result,taskid=taskid,api=api,next_actions=[{'command':f'synology-nas tasks results {api} {taskid} --offset {result["pagination"]["next_offset"] or 0}'},{'command':f'synology-nas tasks clean {api} {taskid} --commit'}])
        api='SYNO.FileStation.'+('DirSize' if name=='size' else 'MD5')
        return job(c,api,{'path':[path]} if name=='size' else {'file_path':path},wait=args.wait)
    if name=='favorites':
        api='SYNO.FileStation.Favorite'
        if args.action=='list': return page(c,api,'list',{},key='favorites',**paging)
        if not args.path: raise Failure('INVALID_INPUT','favorites mutation requires path')
        path=remote_path(args.path); c.stat(path)
        method={'add':'add','remove':'delete','rename':'edit'}[args.action]
        params={'path':path}
        if method in {'add','edit'}: params['name']=args.name or posixpath.basename(path)
        return api_call(c,api,method,params,args)
    if name=='links':
        api='SYNO.FileStation.Sharing'
        if args.action=='list': return page(c,api,'list',{},key='links',cap=3,**paging)
        if not args.target: raise Failure('INVALID_INPUT','links action requires target path or link ID')
        if args.action=='get': return c.call(api,'getinfo',{'id':args.target},cap=3)
        if args.action=='delete': return api_call(c,api,'delete',{'id':args.target},args)
        path=remote_path(args.target); c.stat(path)
        if not scope: raise Failure('INVALID_INPUT','Creating share links requires --scope')
        within(path,scope)
        params={'path':[path]}
        if args.expires:
            import datetime
            try: datetime.date.fromisoformat(args.expires)
            except ValueError: raise Failure('INVALID_INPUT','expires must be YYYY-MM-DD') from None
            params['date_expired']=args.expires
        if args.link_password_file: params['password']=read_secret(args.link_password_file)
        plan={'state':'planned','dry_run':True,'action':'share-link-create','path':path,'expires':args.expires,'password_protected':bool(args.link_password_file),'access_change':True}
        if not commit: return plan
        if not getattr(args,'allow_sharing',False): raise Failure('INVALID_INPUT','Share link creation requires --allow-sharing')
        return {'state':'committed','result':c.call(api,'create',params,cap=3,mutation=True)}
    if name=='mounts': return page(c,'SYNO.FileStation.VirtualFolder','list',{'type':args.type},key='folders',**paging)
    if name=='permissions':
        return c.call('SYNO.FileStation.CheckPermission','write',{'path':remote_path(args.path),'filename':filename(args.name),'overwrite':False,'create_only':True})
    if name=='archive':
        path=remote_path(args.path); c.stat(path)
        if args.action=='list': return page(c,'SYNO.FileStation.Extract','list',{'file_path':path},key='items',**paging)
        if not args.destination: raise Failure('INVALID_INPUT','Archive mutation requires --destination')
        destination=remote_path(args.destination)
        scope_check(c,[path,destination],scope)
        if args.action=='compress':
            if destination==path or destination.startswith(path+'/'):
                raise Failure('INVALID_INPUT','Archive destination cannot be inside its source')
            ensure_folder(c,posixpath.dirname(destination))
            if c.exists(destination): raise Failure('CONFLICT','Archive destination exists')
            if not destination.lower().endswith('.zip'): raise Failure('INVALID_INPUT','Compression destination must end in .zip')
            api,params,cap='SYNO.FileStation.Compress',{'path':[path],'dest_file_path':destination,'format':'zip','level':'moderate','mode':'add'},3
        else:
            ensure_folder(c,destination)
            validate_archive(c,path)
            contents=c.call('SYNO.FileStation.List','list',{'folder_path':destination,'offset':0,'limit':1})
            if contents.get('total',len(contents.get('files',[]))): raise Failure('CONFLICT','Extract destination must be empty to avoid overwrites')
            api,params,cap='SYNO.FileStation.Extract',{'file_path':path,'dest_folder_path':destination,'overwrite':False,'keep_dir':True,'create_subfolder':False},2
        if not commit: return {'state':'planned','dry_run':True,'api':api,'params':params,'scope':scope}
        return job(c,api,params,cap=cap,wait=args.wait)
    if name=='tasks':
        if args.action=='list': return page(c,'SYNO.FileStation.BackgroundTask','list',{},key='tasks',cap=3,**paging)
        api=args.api
        if not api or not args.taskid: raise Failure('INVALID_INPUT','tasks action requires api and taskid')
        if api not in {'SYNO.FileStation.'+n for n in ['Search','DirSize','MD5','CopyMove','Delete','Extract','Compress','BackgroundTask']}:
            raise Failure('UNSUPPORTED','Unknown task API')
        method={'status':'list' if api.endswith('.Search') else 'status','results':'list','stop':'stop','clean':'clean' if api.endswith('.Search') else 'clear_finished'}[args.action]
        if args.action=='results':
            if not api.endswith('.Search'): raise Failure('INVALID_INPUT','results applies to Search tasks only')
            return page(c,api,'list',{'taskid':args.taskid},**paging)
        spec=CATALOG.get(api+':'+method)
        if not spec: raise Failure('UNSUPPORTED','Task method unsupported for this API')
        return api_call(c,api,method,{'taskid':args.taskid},args)
    if name=='system':
        api,method=SYSTEM[args.resource]
        if args.resource in {'disks','pools','volumes'}:
            # Storage Manager is the current device endpoint; avoid obsolete Core.Storage calls.
            overview=c.call('SYNO.Storage.CGI.Storage','load_info',cap=1)
            candidates={'disks':['disks'],'pools':['storagePools','storage_pools','detected_pools'],'volumes':['volumes']}[args.resource]
            key=next((key for key in candidates if key in overview),None)
            if key is None: raise Failure('UNSUPPORTED','Storage Manager did not return this resource',details={'resource':args.resource,'available_fields':list(overview)})
            return {'source':'SYNO.Storage.CGI.Storage:load_info','items':overview[key]}
        if args.resource=='containers':
            return {'source':'community/device API','result':api_call(c,api,method,{'type':'all','offset':0,'limit':100},args)}
        if args.resource=='services':
            return {'source':'file-service APIs','smb':c.call('SYNO.Core.FileServ.SMB','get',cap=1),'nfs':c.call('SYNO.Core.FileServ.NFS','get',cap=1)}
        return {'source':'community/device API; not a public stability guarantee','result':api_call(c,api,method,{},args)}
    if name=='downloads':
        if args.resource=='tasks': return page(c,'SYNO.DownloadStation.Task','list',{},key='tasks',cap=1,**paging)
        return c.call('SYNO.DownloadStation.'+('Info' if args.resource=='info' else 'Statistic'),'getinfo',cap=1)
    if name=='api':
        if not args.api or not args.method: raise Failure('INVALID_INPUT','api call requires API and method')
        params={}
        if args.params_file:
            if args.params_file=='-':
                if getattr(args,'password_stdin',False): raise Failure('INVALID_INPUT','Password and params cannot both use stdin')
                raw=sys.stdin.buffer.read(1048577)
            else:
                if Path(args.params_file).stat().st_size>1048576: raise Failure('INVALID_INPUT','Params exceed 1 MiB')
                raw=Path(args.params_file).read_bytes()
            if len(raw)>1048576: raise Failure('INVALID_INPUT','Params exceed 1 MiB')
            try: params=json.loads(raw.decode('utf-8-sig'))
            except (ValueError,UnicodeError): raise Failure('INVALID_INPUT','params-file must contain a JSON object') from None
        return api_call(c,args.api,args.method,params,args)
    raise Failure('INVALID_INPUT','Unknown command')

def main(argv=None):
    started=time.monotonic(); client=None; args=None; secrets=[]; result=None; error=None; meta={}
    raw=list(sys.argv[1:] if argv is None else argv)
    output='json'
    if '--output' in raw:
        i=raw.index('--output')
        if i+1<len(raw) and raw[i+1] in {'json','jsonl','text'}: output=raw[i+1]
    try:
        parser,registry=build_parser()
        args=parser.parse_args(raw)
        output=getattr(args,'output',output)
        for key,lo,hi in [('limit',1,1000),('offset',0,1000000000),('timeout',.1,300),('deadline',.1,3600),('wait',0,300),('depth',1,100),('max_dirs',1,10000),('max_entries',1,100000),('max_bytes',1,1099511627776)]:
            value=getattr(args,key,None)
            if value is not None and (not lo<=value<=hi): raise Failure('INVALID_INPUT',f'{key.replace("_","-")} must be between {lo} and {hi}')
        if getattr(args,'fields',None): project([],args.fields)
        if getattr(args,'commit',False) and getattr(args,'dry_run',False): raise Failure('INVALID_INPUT','commit and dry-run are mutually exclusive')
        if getattr(args,'password_stdin',False) and ((args.command=='upload' and args.source=='-') or (args.command=='api' and args.params_file=='-')):
            raise Failure('INVALID_INPUT','Password and payload cannot both consume stdin')
        if args.command=='version': result={'version':__version__,'schema_version':'1.0'}
        elif args.command=='schema': result=schema(parser,registry)
        elif args.command=='errors': result={k:{'exit':v[0],'retryable_for_reads':v[1]} for k,v in ERRORS.items()}
        elif args.command=='api' and args.action=='catalog':
            items=[s for s in CATALOG.values() if s['api'].startswith(args.prefix)]
            selected=items[args.offset:args.offset+args.limit]
            result={'items':selected,'total':len(items),'limit':args.limit,'offset':args.offset,'next_offset':args.offset+len(selected) if args.offset+len(selected)<len(items) else None}
        else:
            cfg=config(args)
            secrets=[cfg.get('password'),cfg.get('otp')]
            client=Client(**cfg)
            available=client.discover()
            meta['tls_verified']=not cfg['insecure'] and cfg['url'].startswith('https://')
            if args.command=='doctor':
                result={'reachable':True,'url':client.url,'advertised_apis':len(available),'credentials_configured':bool(cfg['user'] and cfg['password']),'tls_verified':meta['tls_verified'],'sessions_persisted':False,'config_keys':['url','user','ca_file'],'next_action':{'command':'synology-nas auth status'}}
            elif args.command=='discover':
                keys=sorted(k for k in available if k.startswith(args.prefix))
                selected=keys[args.offset:args.offset+args.limit]
                result={'items':[{ 'api':k,**available[k]} for k in selected],'total':len(keys),'limit':args.limit,'offset':args.offset,'next_offset':args.offset+len(selected) if args.offset+len(selected)<len(keys) else None}
            else:
                client.login()
                secrets.append(client.sid)
                result=execute(args,client)
    except Failure as exc: error=exc
    except KeyboardInterrupt: error=Failure('INTERRUPTED','Interrupted; reconcile any dispatched write before retrying',outcome='unknown' if args and getattr(args,'commit',False) else 'not_started')
    except (OSError,UnicodeError,ValueError) as exc:
        error=Failure('INVALID_INPUT','Local file, encoding or configuration could not be read',details={'exception':type(exc).__name__})
    except Exception as exc:
        error=Failure('INTERNAL_ERROR','Unexpected failure; no raw exception or secret is printed',details={'exception':type(exc).__name__},outcome='unknown' if args and getattr(args,'commit',False) else 'not_started')
    finally:
        if client and client.sid: meta['logout_confirmed']=client.logout()
    if error and client and client.mutation_dispatched and error.code in {'NETWORK_ERROR','DEADLINE','INTERNAL_ERROR','INVALID_RESPONSE'}:
        error.outcome='unknown'
        if not error.next_actions and args and getattr(args,'path',None):error.next_actions=[{'command':'synology-nas stat '+args.path}]
    return emit(result,error,started=started,output=output,meta=meta,secrets=secrets)
