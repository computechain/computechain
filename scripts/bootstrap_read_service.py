#!/usr/bin/env python3
"""Source-allowlisted TLS-only bootstrap reads; native RPC stays loopback.

Server identity is authenticated by an operator-pinned CA. Source IP filtering is
not mutual TLS or end-user authentication. No keys, node DBs or write RPC are read.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import http.client
from http.server import HTTPServer
import ipaddress
import json
from pathlib import Path
import ssl
import threading
import time

from computechain.scripts import rpc_read_gateway as reads


def configuration(value):
    if not isinstance(value,dict) or set(value)!={'format','listen','upstream','allowed_sources'} or type(value['format']) is not int or value['format']!=1:
        raise ValueError('invalid TLS read-service configuration')
    host,port=value['listen'].rsplit(':',1)
    address=ipaddress.IPv4Address(host)
    if str(address)!=host or address.is_unspecified or address.is_multicast or address.is_reserved or not 1024<=int(port)<=65535:
        raise ValueError('explicit unicast listener required')
    reads.upstream_address(value['upstream'])
    sources=value['allowed_sources']
    if not isinstance(sources,list) or not 1<=len(sources)<=16 or len(set(sources))!=len(sources):
        raise ValueError('bounded explicit source allowlist required')
    for source in sources:
        address=ipaddress.IPv4Address(source)
        if str(address)!=source or address.is_unspecified or address.is_multicast or address.is_reserved:
            raise ValueError('invalid source IPv4')
    return value


class LimitedInput:
    """Bound the entire single request, including headers, before HTTP parsing."""
    def __init__(self,stream): self.stream=stream; self.remaining=16384+reads.MAX_BODY
    def take(self,method,size=-1):
        limit=self.remaining+1 if size<0 else min(size,self.remaining+1)
        raw=getattr(self.stream,method)(limit)
        self.remaining-=len(raw)
        if self.remaining<0: raise http.client.LineTooLong('bounded bootstrap request')
        return raw
    def readline(self,size=-1): return self.take('readline',size)
    def read(self,size=-1): return self.take('read',size)
    def close(self): self.stream.close()
    @property
    def closed(self): return self.stream.closed


class Handler(reads.Handler):
    def setup(self):
        super().setup()
        self.rfile=LimitedInput(self.rfile)


class TLSServer(HTTPServer):
    request_queue_size=8
    def __init__(self,config,cert,key,reader=reads.read_native):
        config=configuration(config)
        self.allowed=set(config['allowed_sources'])
        self.upstream=reads.upstream_address(config['upstream']); self.reader=reader
        self.context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.minimum_version=ssl.TLSVersion.TLSv1_3
        self.context.load_cert_chain(str(cert),str(key))
        self.slots=threading.BoundedSemaphore(4)
        self.pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='bootstrap-read')
        self.rate_lock=threading.Lock(); self.buckets={}; self.accepted=0; self.rejected=0
        host,port=config['listen'].rsplit(':',1)
        super().__init__((host,int(port)),Handler)

    def permitted(self,source,now=None):
        if source not in self.allowed: return False
        now=time.monotonic() if now is None else now
        with self.rate_lock:
            tokens,stamp=self.buckets.get(source,(20.,now))
            tokens=min(20.,tokens+max(0.,now-stamp)*10.)
            if tokens<1:
                self.buckets[source]=(tokens,now); return False
            self.buckets[source]=(tokens-1,now)
        return True

    def process_request(self,request,client_address):
        if not self.permitted(client_address[0]) or not self.slots.acquire(blocking=False):
            self.rejected+=1; self.shutdown_request(request); return
        self.accepted+=1
        self.pool.submit(self.work,request,client_address)

    def work(self,request,client_address):
        tls=None
        try:
            request.settimeout(2)
            tls=self.context.wrap_socket(request,server_side=True,do_handshake_on_connect=False)
            tls.do_handshake()
            self.finish_request(tls,client_address)
        except (OSError,ValueError,http.client.HTTPException):
            pass  # bounded malformed clients; no bodies/credentials logged
        finally:
            self.shutdown_request(tls if tls is not None else request)
            self.slots.release()

    def handle_error(self,*args): pass

    def server_close(self):
        super().server_close(); self.pool.shutdown(wait=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--cert',type=Path,required=True)
    parser.add_argument('--key',type=Path,required=True)
    args=parser.parse_args()
    server=TLSServer(json.loads(args.config.read_text()),args.cert,args.key)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__': main()
