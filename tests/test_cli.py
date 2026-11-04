import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from synology_nas_cli.backend import Client, decode_response
from synology_nas_cli.cli import main, build_parser, execute
from synology_nas_cli.protocol import Failure, sanitize
from synology_nas_cli.service import mutation, page, remote_path, tree, api_call, validate_archive, job

class Fixture:
    def __init__(self):
        self.files={'/test':{'path':'/test','name':'test','isdir':True,'additional':{'real_path':'/volume1/test'}},'/test/source.txt':{'path':'/test/source.txt','name':'source.txt','isdir':False,'additional':{'real_path':'/volume1/test/source.txt','size':3}}}
        self.writes=[]; self.calls=[]
    def stat(self,path):
        if path not in self.files: raise Failure('NOT_FOUND','Missing')
        return self.files[path]
    def exists(self,path): return self.files.get(path)
    def remaining(self): return 30
    def call(self,api,method,params=None,**kwargs):
        params=params or {}; self.calls.append((api,method,params))
        if method=='list':
            items=[i for i in self.files.values() if str(Path(i['path']).parent).replace('\\','/')==params['folder_path']]
            return {'files':items[params.get('offset',0):params.get('offset',0)+params.get('limit',100)],'total':len(items)}
        self.writes.append((api,method,params))
        if method=='create':
            p=params['folder_path'][0]+'/'+params['name'][0]
            self.files[p]={'path':p,'name':params['name'][0],'isdir':True,'additional':{'real_path':'/volume1'+p}}
            return {'folders':[self.files[p]]}
        if method=='rename':
            old=params['path'][0]; new=old.rsplit('/',1)[0]+'/'+params['name'][0]
            self.files[new]=dict(self.files.pop(old),path=new,name=params['name'][0]); return {}
        return {}

class ContractTests(unittest.TestCase):
    def invoke(self,argv):
        stdout,stderr=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr): code=main(argv)
        return code,json.loads(stdout.getvalue()),stdout.getvalue(),stderr.getvalue()
    def test_version(self):
        code,value,raw,err=self.invoke(['version'])
        self.assertEqual(code,0);self.assertEqual(value['data']['version'],'0.2.0');self.assertFalse(err)
        self.assertFalse(raw.startswith('\ufeff'));self.assertNotIn('\x1b',raw)
    def test_schema_covers_commands(self):
        _,s,_,_=self.invoke(['schema']); _,registry=build_parser()
        self.assertEqual(set(registry),{c['name'] for c in s['data']['commands']})
        self.assertGreater(len(s['data']['api_methods']),60)
    def test_jsonl_quiet(self):
        code,v,raw,_=self.invoke(['--output','jsonl','--quiet','version'])
        self.assertEqual(code,0);self.assertEqual(len(raw.splitlines()),1);self.assertTrue(raw.endswith('\n'))
    def test_invalid_command_json(self):
        code,value,_,err=self.invoke(['invented'])
        self.assertEqual(code,2);self.assertEqual(value['error']['code'],'INVALID_INPUT');self.assertFalse(err)
    def test_invalid_limit_before_network(self):
        with patch('synology_nas_cli.cli.Client') as client:
            self.assertEqual(self.invoke(['shares','--limit','0'])[0],2);client.assert_not_called()
    def test_projection_invalid_before_network(self):
        with patch('synology_nas_cli.cli.Client') as client:
            self.assertEqual(self.invoke(['shares','--fields','cookie'])[0],2);client.assert_not_called()
    def test_nonfinite_timeout(self):
        self.assertEqual(self.invoke(['doctor','--timeout','nan'])[0],2)
    def test_password_stdin_payload_conflict(self):
        self.assertEqual(self.invoke(['upload','-','/test/file','--password-stdin'])[0],2)
    def test_config_secret_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'c.json';p.write_text('{"password":"canary"}')
            code,v,raw,_=self.invoke(['doctor','--config',str(p)])
            self.assertEqual(code,2);self.assertNotIn('canary',raw)
    def test_auth_failure_contract(self):
        with patch('synology_nas_cli.cli.Client') as mocked:
            mocked.return_value.sid=None
            mocked.return_value.login.side_effect=Failure('AUTH_FAILED','Rejected')
            code,v,_,_=self.invoke(['auth','status','--url','https://localhost'])
            self.assertEqual(code,3);self.assertFalse(v['error']['retryable'])
    def test_internal_redacted(self):
        with patch('synology_nas_cli.cli.config',side_effect=RuntimeError('canary-secret')):
            code,v,raw,_=self.invoke(['doctor'])
            self.assertEqual(code,1);self.assertNotIn('canary-secret',raw)
    def test_secret_redaction(self):
        value=sanitize({'cookie':'id=secret','nested':{'sid':'abc'},'url':'literal-canary'},['canary'])
        self.assertNotIn('secret',json.dumps(value));self.assertNotIn('abc',json.dumps(value));self.assertNotIn('canary',json.dumps(value))
    def test_end_of_options_and_metacharacters(self):
        p,_=build_parser();a=p.parse_args(['rename','/test/a','--','-a;$(anything)'])
        self.assertEqual(a.name,'-a;$(anything)')
    def test_global_flags_both_positions(self):
        p,_=build_parser();a=p.parse_args(['--insecure','list','/test','--output','json'])
        self.assertTrue(a.insecure);self.assertEqual(a.output,'json')
    def test_help_every_command_installed(self):
        _,registry=build_parser()
        for command in [None,*registry]:
            run=subprocess.run([sys.executable,'-m','synology_nas_cli',*([command] if command else []),'--help'],capture_output=True,timeout=10)
            self.assertEqual(run.returncode,0,command);self.assertTrue(run.stdout);self.assertFalse(run.stderr)

class PlannerTests(unittest.TestCase):
    def test_hostile_paths(self):
        for value in ['/','/test/../x','/test//x','/test/./x','/test/\x1b[2J','/test/\u202ex','/test/\u200bx','/test\\x']:
            with self.assertRaises(Failure): remote_path(value)
    def test_pagination_and_projection(self):
        f=Fixture();a=page(f,'SYNO.FileStation.List','list',{'folder_path':'/test'},limit=1,fields='name')
        self.assertEqual(a['items'],[{'path':'/test/source.txt','name':'source.txt'}]);self.assertFalse(a['pagination']['truncated'])
    def test_preview_no_mutation(self):
        f=Fixture();plan=mutation(f,'mkdir',path='/test/new',scope='/test')
        self.assertTrue(plan['dry_run']);self.assertFalse(f.writes);self.assertNotIn('/test/new',f.files)
    def test_mkdir_commit_noop_repeat(self):
        f=Fixture();r=mutation(f,'mkdir',path='/test/new',scope='/test',commit=True)
        self.assertEqual(r['state'],'committed')
        r=mutation(f,'mkdir',path='/test/new',scope='/test',commit=True)
        self.assertEqual(r['state'],'noop');self.assertEqual(len(f.writes),1)
    def test_whole_share_blocked(self):
        with self.assertRaises(Failure):mutation(Fixture(),'delete',path='/test',scope='/test',commit=True,confirm='/test')
    def test_outside_scope(self):
        with self.assertRaises(Failure):mutation(Fixture(),'mkdir',path='/other/new',scope='/test',commit=True)
    def test_symlink_scope_escape(self):
        f=Fixture();f.files['/test/link']={'path':'/test/link','isdir':True,'additional':{'real_path':'/volume1/private'}}
        with self.assertRaises(Failure):mutation(f,'mkdir',path='/test/link/new',scope='/test',commit=True)
        self.assertFalse(f.writes)
    def test_delete_requires_exact_confirm(self):
        f=Fixture()
        with self.assertRaises(Failure):mutation(f,'delete',path='/test/source.txt',scope='/test',commit=True,confirm='/test/other')
        self.assertFalse(f.writes)
    def test_rename_preview_and_commit(self):
        f=Fixture();r=mutation(f,'rename',path='/test/source.txt',destination='/test/new.txt',scope='/test')
        self.assertEqual(r['state'],'planned');self.assertFalse(f.writes)
        r=mutation(f,'rename',path='/test/source.txt',destination='/test/new.txt',scope='/test',commit=True)
        self.assertEqual(r['state'],'committed');self.assertIn('/test/new.txt',f.files)
    def test_raw_mutation_cannot_bypass_scope(self):
        a=type('Args',(),{'commit':True})()
        with self.assertRaises(Failure):api_call(Fixture(),'SYNO.FileStation.Delete','start',{'path':['/test/source.txt']},a)
    def test_raw_pagination_bounded(self):
        with self.assertRaises(Failure):api_call(Fixture(),'SYNO.FileStation.List','list',{'folder_path':'/test','limit':0},object())
    def test_tree_bounds(self):
        f=Fixture();r=tree(f,['/test'],depth=1,max_dirs=1,max_entries=1)
        self.assertEqual(r['entries'],1);self.assertLessEqual(r['directories_scanned'],1)
    def test_nested_archive_traversal_rejected(self):
        f=Fixture()
        def response(api,method,params,**kwargs):
            if 'item_id' not in params:return {'items':[{'path':'folder','name':'folder','is_dir':True,'item_id':2}],'total':1}
            return {'items':[{'path':'../../escape','name':'escape','is_dir':False}],'total':1}
        f.call=response
        with self.assertRaises(Failure):validate_archive(f,'/test/archive.zip')
    def test_job_poll_failure_keeps_task_identity(self):
        f=Fixture()
        def response(api,method,params,**kwargs):
            if method=='start':return {'taskid':'operation-123'}
            raise Failure('NETWORK_ERROR','Read interrupted')
        f.call=response
        with self.assertRaises(Failure) as cm:job(f,'SYNO.FileStation.CopyMove',{},wait=1)
        self.assertEqual(cm.exception.details['taskid'],'operation-123')
        self.assertIn('operation-123',cm.exception.next_actions[0]['command'])
    def test_sharing_raw_requires_scope(self):
        with self.assertRaises(Failure):api_call(Fixture(),'SYNO.FileStation.Sharing','create',{'path':['/test/source.txt']},object())
    def test_raw_reserved_auth_fields_rejected(self):
        with self.assertRaises(Failure):api_call(Fixture(),'SYNO.FileStation.Info','get',{'_sid':'canary'},object())
    def test_backend_error_mapping(self):
        for code,expected in [(119,'AUTH_FAILED'),(105,'PERMISSION_DENIED'),(408,'NOT_FOUND'),(407,'CONFLICT'),(103,'UNSUPPORTED')]:
            with self.assertRaises(Failure) as cm:decode_response({'success':False,'error':{'code':code}})
            self.assertEqual(cm.exception.code,expected)

class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                n=int(self.headers.get('Content-Length',0));self.rfile.read(n)
                route=self.path.rsplit('/',1)[-1]
                if route=='unavailable':self.send_response(503);self.end_headers();return
                self.send_response(200);self.send_header('Content-Type','application/octet-stream' if route=='binary' else 'application/json');self.end_headers()
                self.wfile.write(b'abc\x00\xff' if route=='binary' else b'not-json' if route=='invalid' else b'{"success":true,"data":{"value":"ok"}}')
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def client(self):return Client('http://127.0.0.1:'+str(self.server.server_port),timeout=2)
    def test_real_form_transport(self):self.assertEqual(self.client().request('query.cgi',{})['value'],'ok')
    def test_invalid_json(self):
        with self.assertRaises(Failure) as cm:self.client().request('invalid',{})
        self.assertEqual(cm.exception.code,'INVALID_RESPONSE')
    def test_transient_unknown_write(self):
        with self.assertRaises(Failure) as cm:self.client().request('unavailable',{},mutation=True)
        self.assertEqual(cm.exception.code,'NETWORK_ERROR');self.assertEqual(cm.exception.outcome,'unknown')
    def test_no_http_login(self):
        with self.assertRaises(Failure) as cm:self.client().login()
        self.assertEqual(cm.exception.code,'INVALID_INPUT')
    def test_deadline_before_dispatch(self):
        c=self.client();c.until=0
        with self.assertRaises(Failure) as cm:c.request('query.cgi',{})
        self.assertEqual(cm.exception.code,'DEADLINE');self.assertEqual(cm.exception.outcome,'not_started')
    def test_download_atomic_bounded_checksum(self):
        c=self.client();c.info={'binary':{'path':'binary','minVersion':1,'maxVersion':2}}
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'file.bin'
            with self.assertRaises(Failure):c.download('binary','download',{},target,max_bytes=2)
            self.assertFalse(target.exists());self.assertEqual(list(Path(d).iterdir()),[])
            r=c.download('binary','download',{},target,max_bytes=5)
            self.assertEqual(target.read_bytes(),b'abc\x00\xff');self.assertEqual(r['sha256'],hashlib.sha256(target.read_bytes()).hexdigest())
            with self.assertRaises(Failure):c.download('binary','download',{},target)
    def test_json_string_serialization(self):
        c=self.client();c.info={'SYNO.FileStation.MD5':{'minVersion':1,'maxVersion':2,'path':'entry.cgi','requestFormat':'JSON'}}
        _,fields=c.fields('SYNO.FileStation.MD5','status',{'taskid':'abc'},2)
        self.assertEqual(fields['taskid'],'"abc"');self.assertEqual(fields['method'],'status')

if __name__=='__main__':unittest.main()
