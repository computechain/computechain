"""Actual read-only Nginx gateway on owned ephemeral loopback ports. Never touch host Nginx."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import subprocess
import threading
import time
import uuid

import pytest

from computechain.scripts import multisite as fleet
from computechain.scripts import rpc_read_gateway as reads


def test_real_gateway_allows_read_paths_and_denies_writes_and_foreign_sources(tmp_path):
    if subprocess.run(['docker','image','inspect',fleet.NGINX],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        pytest.skip('pinned Nginx image/Docker required')
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            body=json.dumps({'jsonrpc':'2.0','result':{'path':self.path}}).encode()
            self.send_response(200); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self,*args): pass
    backend=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    rpc=backend.server_port
    port=rpc+3
    if port>65535:
        backend.server_close(); pytest.skip('ephemeral range too high')
    # Fail early on a port collision instead of killing any unrelated listener.
    try:
        for candidate in (port,rpc+4):
            with socket.socket() as reservation: reservation.bind(('127.0.0.1',candidate))
    except OSError:
        backend.server_close(); pytest.skip('ephemeral gateway port in use')
    node={'name':'test-gateway','host':'127.0.0.1'}
    value={'base_port':rpc-1,'nodes':[node],'readers':[]}
    path=tmp_path / 'nginx.conf'; path.write_text(fleet.gateway(value,node)); path.chmod(0o644)
    name='cpc-rpc-test-'+uuid.uuid4().hex
    thread=threading.Thread(target=backend.serve_forever,daemon=True); thread.start()
    adapter=reads.BoundedServer(('127.0.0.1',rpc+4),f'http://127.0.0.1:{rpc}')
    adapter_thread=threading.Thread(target=adapter.serve_forever,daemon=True); adapter_thread.start()
    def request(method,path,source='127.0.0.1',headers=None,body=None):
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=3,source_address=(source,0))
        try:
            connection.request(method,path,body=body,headers=headers or {})
            response=connection.getresponse(); return response.status,response.read()
        finally: connection.close()
    try:
        subprocess.run(['docker','run','-d','--name',name,'--network','host','--user','101:101','--read-only',
            '--cap-drop','ALL','--security-opt','no-new-privileges:true','--memory','128m','--pids-limit','64',
            '--tmpfs','/tmp:rw,noexec,nosuid,size=16m,mode=1777','-v',f'{path}:/etc/nginx/nginx.conf:ro',
            '--entrypoint','nginx',fleet.NGINX,'-g','daemon off;'],check=True,capture_output=True)
        deadline=time.monotonic()+10
        while True:
            try:
                if request('GET','/status')[0]==200: break
            except OSError: pass
            if time.monotonic()>deadline:
                logs=subprocess.check_output(['docker','logs',name],stderr=subprocess.STDOUT,text=True)
                pytest.fail('owned gateway did not start: '+logs[-1500:])
            time.sleep(.1)
        for method in fleet.RPC_METHODS:
            path='/'+method+('' if method in ('status','genesis') else '?height=1')
            code,body=request('GET',path)
            assert code==200 and json.loads(body)['result']['path'].rstrip('?')==path
        code,body=request('POST','/',body=json.dumps({'jsonrpc':'2.0','id':17,'method':'commit','params':{'height':'1'}}))
        assert code==200 and json.loads(body)['id']==17
        assert json.loads(body)['result']['path']=='/commit?height=1'
        before=len(calls)
        for method,path,expected in [('POST','/status',405),('POST','/',413),('GET','/broadcast_tx_commit?tx=0x00',404),
                ('GET','/abci_query?path=/state',404),('GET','/unsafe_flush_mempool',404),('GET','/websocket',404),
                ('GET','/blockchain',404),('GET','/status/../broadcast_tx_sync',404)]:
            assert request(method,path)[0]==expected
        assert len(calls)==before
        assert request('POST','/',body=json.dumps({'jsonrpc':'2.0','id':1,'method':'broadcast_tx_commit','params':{'tx':'0x00'}}))[0]==403
        assert len(calls)==before
        assert request('GET','/status',source='127.0.0.2',headers={'X-Forwarded-For':'127.0.0.1'})[0]==403
        assert len(calls)==before
    finally:
        subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        backend.shutdown(); backend.server_close(); thread.join(timeout=5)
        adapter.shutdown(); adapter.server_close(); adapter_thread.join(timeout=5)
