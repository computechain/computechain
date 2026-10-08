"""Bounded LOOPBACK JSON-RPC adapter for native light clients, behind the private Nginx ACL.

Only validated read methods are translated to native REST GET requests. JSON-RPC
POST is NOT transaction broadcast permission. No node keys/storage are opened.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import re
import threading
import urllib.parse
import urllib.request

MAX_BODY=8192
MAX_REPLY=4*1024*1024
PARAMS={'status':{},'genesis':{},'block':{'height':2**63-1},'commit':{'height':2**63-1},
        'validators':{'height':2**63-1,'page':1_000_000,'per_page':100},'consensus_params':{'height':2**63-1}}


def pairs(values):
    result={}
    for key,value in values:
        if key in result: raise ValueError('duplicate JSON field')
        result[key]=value
    return result


def parameters(method,values):
    if method not in PARAMS: raise ValueError('method is not allowed')
    if values is None: values={}
    if not isinstance(values,dict) or set(values)-set(PARAMS[method]): raise ValueError('invalid RPC parameter fields')
    result={}
    for name,value in values.items():
        if value is None: continue  # native Go pointer arguments may serialize null
        if type(value) is int: value=str(value)
        if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,18}',value) or int(value)>PARAMS[method][name]:
            raise ValueError('invalid bounded RPC parameter')
        result[name]=value
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise ValueError('upstream redirects forbidden')


def upstream_address(value):
    url=urllib.parse.urlsplit(value)
    try:
        if url.scheme!='http' or not ipaddress.ip_address(url.hostname).is_loopback or url.username or url.password or url.path not in ('','/') or url.query or url.fragment or not 1024<=url.port<=65535:
            raise ValueError
    except (ValueError,TypeError): raise ValueError('upstream must be a literal loopback HTTP origin') from None
    return value.rstrip('/')


def read_native(upstream,method,params):
    upstream=upstream_address(upstream)
    values=parameters(method,params)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    url=upstream+'/'+method+'?'+urllib.parse.urlencode(values)
    with opener.open(url,timeout=5) as response: raw=response.read(MAX_REPLY+1)
    if len(raw)>MAX_REPLY: raise ValueError('upstream reply too large')
    value=json.loads(raw,object_pairs_hook=pairs)
    if not isinstance(value,dict) or value.get('jsonrpc')!='2.0' or ('result' in value)==('error' in value):
        raise ValueError('invalid native RPC response')
    return value


class BoundedServer(HTTPServer):
    def __init__(self,address,upstream,reader=read_native):
        if not ipaddress.ip_address(address[0]).is_loopback: raise ValueError('adapter listener must be loopback')
        self.upstream=upstream_address(upstream); self.reader=reader
        self.slots=threading.BoundedSemaphore(8)
        self.pool=ThreadPoolExecutor(max_workers=8,thread_name_prefix='read-rpc')
        super().__init__(address,Handler)

    def process_request(self,request,client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request); return
        self.pool.submit(self.work,request,client_address)

    def work(self,request,client_address):
        try: self.finish_request(request,client_address)
        finally:
            self.shutdown_request(request); self.slots.release()

    def server_close(self):
        super().server_close(); self.pool.shutdown(wait=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'  # bounded one request per connection; native clients reconnect normally
    server_version='CPCReadRPC'

    def setup(self):
        super().setup(); self.connection.settimeout(5)

    def log_message(self,*args): pass  # do not log bodies/identifiers supplied by clients

    def answer(self,status,value):
        raw=json.dumps(value,separators=(',',':')).encode()
        self.send_response(status); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store')
        self.end_headers()
        if self.command!='HEAD': self.wfile.write(raw)

    def invoke(self,method,values,identifier):
        try: clean=parameters(method,values)
        except (ValueError,TypeError):
            self.answer(400,{'jsonrpc':'2.0','id':identifier,'error':{'code':-32602,'message':'read method/parameters rejected'}}); return
        try:
            reply=self.server.reader(self.server.upstream,method,clean)
            reply={**reply,'id':identifier}
            self.answer(200,reply)
        except Exception:
            self.answer(502,{'jsonrpc':'2.0','id':identifier,'error':{'code':-32603,'message':'read source unavailable'}})

    def do_POST(self):
        if self.path!='/': self.answer(405,{'error':'POST is only supported for read-only JSON-RPC at /'}); return
        try:
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:
                raise ValueError
            length=int(self.headers['Content-Length'])
            if not 0<length<=MAX_BODY:
                self.answer(413,{'error':'bounded JSON-RPC body required'}); return
            raw=self.rfile.read(length)
            if len(raw)!=length: raise ValueError
            request=json.loads(raw,object_pairs_hook=pairs)
            if not isinstance(request,dict) or set(request)-{'jsonrpc','id','method','params'} or request.get('jsonrpc')!='2.0' or 'id' not in request:
                raise ValueError
            identifier=request['id']
            if not (type(identifier) is int and abs(identifier)<2**63 or isinstance(identifier,str) and len(identifier)<=128): raise ValueError
            method=request.get('method')
            if not isinstance(method,str) or method not in PARAMS:
                self.answer(403,{'jsonrpc':'2.0','id':identifier,'error':{'code':-32601,'message':'read method is not allowed'}}); return
            self.invoke(method,request.get('params',{}),identifier)
        except (ValueError,TypeError,UnicodeError,RecursionError): self.answer(400,{'error':'invalid bounded JSON-RPC request'})

    def do_GET(self):
        try:
            path=urllib.parse.urlsplit(self.path)
            method=path.path.removeprefix('/')
            if method not in PARAMS or path.path!='/'+method:
                self.answer(404,{'error':'read route not found'}); return
            values=urllib.parse.parse_qs(path.query,keep_blank_values=True,max_num_fields=4)
            if any(len(v)!=1 for v in values.values()): raise ValueError
            self.invoke(method,{k:v[0] for k,v in values.items()},-1)
        except (ValueError,TypeError): self.answer(400,{'error':'invalid read parameters'})

    do_HEAD=do_GET


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--listen',default='127.0.0.1:26661')
    parser.add_argument('--upstream',required=True)
    args=parser.parse_args()
    host,port=args.listen.rsplit(':',1)
    if not 1024<=int(port)<=65535: parser.error('listener port must be 1024..65535')
    server=BoundedServer((host,int(port)),args.upstream)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__': main()
