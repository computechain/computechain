"""Read JSON-RPC validation: owned loopback server, fake read-only native backend."""
import http.client
import json
import threading

import pytest

from computechain.scripts import rpc_read_gateway as reads


@pytest.fixture
def adapter():
    calls=[]
    def reader(upstream,method,params):
        calls.append((method,params))
        return {'jsonrpc':'2.0','id':-1,'result':{'ok':True}}
    server=reads.BoundedServer(('127.0.0.1',0),'http://127.0.0.1:26657',reader)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    def post(value):
        raw=value if isinstance(value,str) else json.dumps(value)
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
        try:
            client.request('POST','/',body=raw,headers={'Content-Type':'application/json'})
            response=client.getresponse(); return response.status,json.loads(response.read())
        finally: client.close()
    try: yield post,calls
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


@pytest.mark.parametrize('method',list(reads.PARAMS))
def test_native_post_reads_preserve_id_and_never_forward_post(adapter,method):
    post,calls=adapter
    params={} if method in ('status','genesis') else {'height':'17'}
    code,value=post({'jsonrpc':'2.0','id':7,'method':method,'params':params})
    assert code==200 and value['id']==7 and calls==[(method,params)]


@pytest.mark.parametrize('value',[
    {'jsonrpc':'2.0','id':1,'method':'broadcast_tx_commit','params':{'tx':'0x00'}},
    {'jsonrpc':'2.0','id':1,'method':'abci_query','params':{}},
    {'jsonrpc':'2.0','id':1,'method':'unsafe_flush_mempool','params':{}},
    {'jsonrpc':'2.0','id':1,'method':'commit','params':{'height':True}},
    {'jsonrpc':'2.0','id':1,'method':'commit','params':{'height':'01'}},
    {'jsonrpc':'2.0','id':1,'method':'commit','params':{'height':-1}},
    {'jsonrpc':'2.0','id':1,'method':'commit','params':{'height':2**63}},
    {'jsonrpc':'2.0','id':1,'method':'validators','params':{'per_page':101}},
    {'jsonrpc':'2.0','id':1,'method':'status','params':{'method':'broadcast_tx_commit'}},
    {'jsonrpc':'2.0','id':True,'method':'status'},
    {'jsonrpc':'2.0','id':1,'method':'status','url':'http://169.254.169.254/'},
    [{'jsonrpc':'2.0','id':1,'method':'status'}],
    '{"jsonrpc":"2.0","id":1,"method":"status","method":"broadcast_tx_commit"}',
    '{"jsonrpc":"2.0","id":1,"method":"commit","params":{"height":"1","height":"2"}}',
    'x'*(reads.MAX_BODY+1),
])
def test_invalid_or_privileged_rpc_has_no_native_call(adapter,value):
    post,calls=adapter
    assert post(value)[0] in (400,403,413)
    assert calls==[]


@pytest.mark.parametrize('address',['http://8.8.8.8:26657','http://localhost:26657','https://127.0.0.1:26657',
    'http://user:pass@127.0.0.1:26657','http://127.0.0.1:26657/path'])
def test_adapter_cannot_become_an_arbitrary_upstream_proxy(address):
    with pytest.raises(ValueError): reads.upstream_address(address)
