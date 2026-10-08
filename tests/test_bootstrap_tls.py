import http.client
import json
import socket
import ssl
import threading
import pytest
from computechain.scripts import bootstrap_read_service as tls
from computechain.scripts import bootstrap_pki as pki


@pytest.fixture(scope='module')
def certificates(tmp_path_factory):
    root=tmp_path_factory.mktemp('bootstrap-tls')
    ca=pki.ca_init(root/'ca')
    csr=pki.identity_init(root/'provider','provider-aa','127.0.0.1')
    cert=pki.issue(root/'ca',csr,'127.0.0.1',root/'server.pem')
    return root,ca,cert,root/'provider/tls-private.pem'


@pytest.fixture
def server(certificates):
    root,ca,cert,key=certificates
    calls=[]
    def reader(upstream,method,params):
        calls.append((method,params)); return {'jsonrpc':'2.0','result':{'method':method}}
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1',0)); port=reserve.getsockname()[1]
    config={'format':1,'listen':f'127.0.0.1:{port}','upstream':'http://127.0.0.1:26657','allowed_sources':['127.0.0.1']}
    service=tls.TLSServer(config,cert,key,reader)
    thread=threading.Thread(target=service.serve_forever,daemon=True); thread.start()
    yield service,ca,port,calls
    service.shutdown(); service.server_close(); thread.join(timeout=5)


def request(server,method,path,body=None):
    service,ca,port,calls=server
    context=ssl.create_default_context(cafile=str(ca)); context.minimum_version=ssl.TLSVersion.TLSv1_3
    connection=http.client.HTTPSConnection('127.0.0.1',port,context=context,timeout=3)
    try:
        connection.request(method,path,body=body,headers={'Content-Type':'application/json'})
        response=connection.getresponse(); return response.status,response.read()
    finally: connection.close()


def test_real_tls_read_post_and_no_write_routes(server):
    status,body=request(server,'POST','/',json.dumps({'jsonrpc':'2.0','id':7,'method':'status','params':{}}))
    assert status==200 and json.loads(body)['id']==7
    for method in ('broadcast_tx_commit','abci_query','unsafe_flush_mempool','net_info'):
        assert request(server,'POST','/',json.dumps({'jsonrpc':'2.0','id':8,'method':method}))[0]==403
    assert request(server,'GET','/abci_query')[0]==404
    assert request(server,'GET','/websocket')[0]==404
    assert server[3]==[('status',{})]


def test_tls_requires_trusted_certificate_and_matching_ip(server):
    _,ca,port,calls=server
    context=ssl.create_default_context()
    with socket.create_connection(('127.0.0.1',port),timeout=3) as raw:
        with pytest.raises(ssl.SSLCertVerificationError): context.wrap_socket(raw,server_hostname='127.0.0.1')
    context=ssl.create_default_context(cafile=str(ca))
    with socket.create_connection(('127.0.0.1',port),timeout=3) as raw:
        with pytest.raises(ssl.SSLCertVerificationError): context.wrap_socket(raw,server_hostname='wrong.example.com')
    assert not calls


def test_older_tls_and_spoofed_source_are_rejected_before_rpc(server):
    service,ca,port,calls=server
    context=ssl.create_default_context(cafile=str(ca)); context.maximum_version=ssl.TLSVersion.TLSv1_2
    with socket.create_connection(('127.0.0.1',port),timeout=3) as raw:
        with pytest.raises(ssl.SSLError): context.wrap_socket(raw,server_hostname='127.0.0.1')
    context=ssl.create_default_context(cafile=str(ca))
    with socket.create_connection(('127.0.0.1',port),timeout=3,source_address=('127.0.0.2',0)) as raw:
        with pytest.raises((ssl.SSLError,OSError)): context.wrap_socket(raw,server_hostname='127.0.0.1')
    assert service.rejected>=1 and not calls


def test_bounded_json_batch_duplicates_and_oversized_requests(server):
    assert request(server,'POST','/','[]')[0]==400
    assert request(server,'POST','/','{"jsonrpc":"2.0","id":1,"id":2,"method":"status"}')[0]==400
    assert request(server,'POST','/','x'*8193)[0]==413
    assert not server[3]


def test_source_bucket_has_bounded_storage_and_rate(server):
    service,_,_,_=server
    for _ in range(20): assert service.permitted('127.0.0.1',now=1)
    assert not service.permitted('127.0.0.1',now=1)
    for i in range(100): assert not service.permitted(f'192.168.0.{i}',now=1)
    assert len(service.buckets)==1
    assert service.permitted('127.0.0.1',now=1.2)


def test_limited_headers_cannot_allocate_unbounded_input():
    import io
    source=tls.LimitedInput(io.BytesIO(b'x'*100000+b'\n'))
    with pytest.raises(http.client.LineTooLong): source.readline(100000)
