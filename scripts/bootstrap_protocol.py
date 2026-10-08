"""Approved HTTPS providers and signed, short-lived operator checkpoints."""
from __future__ import annotations
import hashlib
import http.client
import ipaddress
import json
from pathlib import Path
import re
import ssl
import urllib.parse
from computechain.scripts import comet_checkpoint as anchors
from computechain.scripts import rpc_read_gateway as reads
from computechain.scripts import signed_checkpoint as signed


def profile(value,config,local_qa=False):
    fields={'format','chain_id','genesis_sha256','ca_sha256','operator_public_key','providers'}
    if not isinstance(value,dict) or set(value)!=fields or type(value['format']) is not int or value['format']!=1:
        raise ValueError('invalid bootstrap profile')
    if value['chain_id']!=config['chain_id'] or value['genesis_sha256']!=config['genesis_sha256']:
        raise ValueError('bootstrap profile belongs to another chain/genesis')
    for field in ('ca_sha256','operator_public_key','genesis_sha256'):
        if not isinstance(value[field],str) or not re.fullmatch(r'[0-9a-f]{64}',value[field]): raise ValueError('invalid bootstrap trust identity')
    from computechain.blockchain.comet.staking import consensus_key
    consensus_key(value['operator_public_key'])
    providers=value['providers']
    if not isinstance(providers,list) or not 2<=len(providers)<=6: raise ValueError('two to six independent providers required')
    ids=set(); addresses=set(); locations=set(); names=set(); certificates=set()
    for provider in providers:
        if not isinstance(provider,dict) or set(provider)!={'name','node_id','location','url','certificate_sha256'}:
            raise ValueError('invalid provider fields')
        for label in ('name','location'):
            if not re.fullmatch(r'[a-z][a-z0-9-]{1,39}',provider[label]): raise ValueError('invalid provider label')
        if not re.fullmatch(r'[0-9a-f]{40}',provider['node_id']) or not re.fullmatch(r'[0-9a-f]{64}',provider['certificate_sha256']):
            raise ValueError('invalid provider node/certificate identity')
        parsed=urllib.parse.urlsplit(provider['url'])
        try:
            address=ipaddress.IPv4Address(parsed.hostname)
            allowed=address.is_global and not address.is_multicast and not address.is_reserved
            if local_qa and address.is_loopback: allowed=True
            if parsed.scheme!='https' or not allowed or str(address)!=parsed.hostname or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment or not 1024<=parsed.port<=65535:
                raise ValueError
        except (ValueError,TypeError): raise ValueError('provider must be a literal approved HTTPS WAN origin') from None
        if provider['node_id'] in ids or provider['name'] in names or str(address) in addresses or provider['certificate_sha256'] in certificates:
            raise ValueError('duplicate provider identity/host/certificate')
        ids.add(provider['node_id']); names.add(provider['name']); addresses.add(str(address)); locations.add(provider['location'])
        certificates.add(provider['certificate_sha256'])
    if len(locations)<2: raise ValueError('providers must span declared locations')
    return value


def trust_context(ca,expected):
    path=Path(ca)
    if path.is_symlink(): raise ValueError('trust CA must not be a symlink')
    with path.open('rb') as stream: raw=stream.read(65537)
    if len(raw)>65536 or hashlib.sha256(raw).hexdigest()!=expected: raise ValueError('CA differs from approved profile')
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version=ssl.TLSVersion.TLSv1_3
    context.load_verify_locations(cadata=raw.decode('ascii'))
    return context


def read(provider,context,method,*,timeout=2,**params):
    clean=reads.parameters(method,params)
    parsed=urllib.parse.urlsplit(provider['url'])
    connection=http.client.HTTPSConnection(parsed.hostname,parsed.port,timeout=timeout,context=context)
    try:
        connection.connect()
        certificate=connection.sock.getpeercert(binary_form=True)
        if hashlib.sha256(certificate).hexdigest()!=provider['certificate_sha256']:
            raise ValueError('provider leaf certificate differs from approval')
        connection.request('GET','/'+method+'?'+urllib.parse.urlencode(clean),headers={'Connection':'close','Accept-Encoding':'identity'})
        response=connection.getresponse()
        if response.status!=200:
            if response.status>=500 or response.status==429: raise RuntimeError('bootstrap read service unavailable')
            raise ValueError('bootstrap HTTPS response/redirect rejected')
        raw=response.read(reads.MAX_REPLY+1)
        if len(raw)>reads.MAX_REPLY: raise ValueError('bootstrap reply too large')
        value=json.loads(raw,object_pairs_hook=reads.pairs)
        if not isinstance(value,dict) or value.get('jsonrpc')!='2.0' or not isinstance(value.get('result'),dict) or 'error' in value:
            raise ValueError('invalid bootstrap RPC reply')
        return value['result']
    except ssl.SSLError as exc:
        raise ValueError('bootstrap TLS authentication/handshake rejected') from exc
    finally: connection.close()


def context(home,approved_profile,ca,local_qa=False):
    home=Path(home)
    from computechain.scripts import multisite as fleet
    m=fleet.checked_home(home)
    config={'schema':3,'chain_id':m['chain_id'],'genesis_sha256':m['genesis_sha256'],
            'genesis_file':str(home/'config/genesis.json')}
    value=profile(approved_profile,config,local_qa)
    config['nodes']=value['providers']
    config['expected_node_ids']={i:p['node_id'] for i,p in enumerate(value['providers'])}
    tls=trust_context(ca,value['ca_sha256'])
    call=lambda i,method,**params:read(value['providers'][i],tls,method,**params)
    return m,config,call,tuple(range(len(value['providers'])))


def capture(home,value,ca,private_key,output,local_qa=False):
    _,config,call,indexes=context(home,value,ca,local_qa)
    checkpoint=anchors.capture(config,call,indexes)
    envelope=signed.sign(private_key,checkpoint,config)
    if envelope['authority']!=value['operator_public_key']: raise ValueError('operator signing key differs from approved public key')
    signed.export(output,envelope)
    return envelope


def uninitialized_application(home,manifest):
    """Explicit retry of a stopped, entirely empty app DB, without replacing it.

    Native DBs, any committed state/receipts/snapshots or staging data are refused.
    This is not a recovery path for a partial native restore or existing history.
    """
    import fcntl
    import os
    import sqlite3
    from computechain.scripts import multisite as fleet
    from computechain.scripts.fleet_network import stopped
    if os.geteuid()!=0:
        raise ValueError('empty application retry requires explicit root operator')
    if manifest['node']['role']!='full' or 'bootstrap_completed' in manifest:
        raise ValueError('empty application retry is only for an uncompleted full follower')
    pinned=pinned_trust(home,manifest)
    signed.verify_signature(manifest['checkpoint_attestation'],pinned['operator_public_key'])
    stopped(manifest)
    fleet.fresh(home)  # native history/signing state must still be entirely fresh
    directory=Path(manifest['application_home'])
    expected={'application.sqlite','application.sqlite-wal','application.sqlite-shm','.writer.lock'}
    if directory.is_symlink() or any(p.is_symlink() or not p.is_file() or p.name not in expected for p in directory.iterdir()):
        raise ValueError('unrecognized or staged application data; inspect manually')
    database=directory/'application.sqlite'
    if not database.is_file() or database.stat().st_size>1024*1024:
        raise ValueError('empty application database missing or oversized')
    descriptor=os.open(directory/'.writer.lock',os.O_RDONLY|os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        connection=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
        try:
            connection.execute('PRAGMA query_only=ON')
            tables=connection.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            if set(tables)!={(name,'table') for name in ('committed','receipts','snapshots')}:
                raise ValueError('unexpected application schema; inspect manually')
            if any(connection.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('committed','receipts','snapshots')):
                raise ValueError('application has existing state/history; retry prohibited')
        finally:
            connection.close()
    finally:
        os.close(descriptor)
    return {'database':str(database),'committed':0,'receipts':0,'snapshots':0,'database_preserved':True}


def configure(home,envelope_path,value,ca,local_qa=False,*,resume_uninitialized=False):
    from computechain.scripts import multisite as fleet
    from computechain.scripts.fleet_network import atomic_public
    home=Path(home)
    with fleet.operator_lock(home):
        m,config,call,indexes=context(home,value,ca,local_qa)
        if m['node']['role']!='full': raise ValueError('signed state-sync bootstrap is FULL node only')
        retry=uninitialized_application(home,m) if resume_uninitialized else None
        if not resume_uninitialized:
            fleet.fresh(home,m['application_home'])
        if m.get('bootstrap_profile')!=value or fleet.digest_file(home/'bootstrap-ca.pem')!=value['ca_sha256']:
            raise ValueError('bootstrap trust must be preinstalled and pinned, not selected at startup')
        envelope=signed.load(envelope_path)
        checkpoint=signed.verify(envelope,value['operator_public_key'],config)
        verified=anchors.check_witnesses(checkpoint,config,call,indexes)
        cfg=home/'config/config.toml'; original=cfg.read_bytes(); metadata=(home/'node.json').read_bytes()
        try:
            fleet.set_toml(cfg,'',{'log_level':'"*:error,statesync:info"'})
            fleet.set_toml(cfg,'statesync',{'enable':'true','rpc_servers':json.dumps(','.join(value['providers'][i]['url'] for i in verified['witnesses'])),
                'trust_height':str(checkpoint['height']),'trust_hash':json.dumps(checkpoint['block_hash']),'trust_period':'"30s"',
                'discovery_time':'"5s"','chunk_request_timeout':'"5s"','chunk_fetchers':'2','max_snapshot_chunks':'64'})
            m['files']['config.toml']=fleet.digest_file(cfg)
            m['state_sync_anchor']=checkpoint
            m['bootstrap_profile']=value
            m['checkpoint_attestation']=envelope
            atomic_public(home/'node.json',(json.dumps(m,indent=2)+'\n').encode())
            fleet.checked_home(home)
            # Do not extend or refresh signed time implicitly after configuration.
            if anchors.validate(checkpoint,config)<anchors.STARTUP_BUDGET_SECONDS: raise ValueError('checkpoint near expiry; not starting')
        except Exception:
            atomic_public(cfg,original); atomic_public(home/'node.json',metadata)
            raise
        return {'node':m['node']['name'],'signed_checkpoint_verified':True,'native_restore_still_required':True,
                'empty_application_retry':retry,**verified}


def pinned_trust(home,manifest):
    """Service users cannot replace the external root-owned operator trust pin."""
    from computechain.scripts import multisite as fleet
    home=Path(home)
    ops=Path('/etc/computechain')/manifest['chain_id']/manifest['node']['name']
    for path in (ops,ops.parent,ops.parent.parent):
        if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022:
            raise ValueError('operator trust directory is not root-owned/immutable to services')
    for name in ('bootstrap-profile.json','bootstrap-ca.pem'):
        path=ops/name
        if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022 or fleet.digest_file(path)!=manifest['files'][name]:
            raise ValueError('external operator trust pin mismatch')
    pinned=fleet.read(ops/'bootstrap-profile.json')
    config={'schema':3,'chain_id':manifest['chain_id'],'genesis_sha256':manifest['genesis_sha256']}
    profile(pinned,config)
    if pinned!=manifest['bootstrap_profile'] or fleet.digest_file(home/'bootstrap-ca.pem')!=pinned['ca_sha256']:
        raise ValueError('node trust differs from operator approval')
    empty=home/'empty-trust-directory'
    if empty.is_symlink() or not empty.is_dir() or any(empty.iterdir()):
        raise ValueError('native TLS must not load additional unapproved trust roots')
    return pinned


def complete(home,ca):
    """Retire bootstrap ONLY after this native attempt's restore and common AppHash."""
    import subprocess
    from computechain.scripts import multisite as fleet
    from computechain.scripts.fleet_network import atomic_public
    home=Path(home)
    with fleet.operator_lock(home):
        m=fleet.checked_home(home)
        value=pinned_trust(home,m)
        _,config,call,indexes=context(home,value,ca)
        signed.verify_signature(m['checkpoint_attestation'],value['operator_public_key'])
        prefix='cpc-'+m['chain_id']+'-'+m['node']['name']+'-engine.service'
        invocation=subprocess.check_output(['systemctl','show',prefix,'-p','InvocationID','--value'],text=True).strip()
        if not re.fullmatch(r'[0-9a-f]{32}',invocation): raise ValueError('no current native engine invocation')
        logs=subprocess.check_output(['journalctl','_SYSTEMD_INVOCATION_ID='+invocation,'--no-pager','-o','cat','-n','200'],text=True)
        restored=re.search(r'Snapshot restored[^\n]*height=(\d+)',logs)
        if restored is None: raise ValueError('this native attempt has no Snapshot restored proof')
        upstream=f"http://127.0.0.1:{m['ports']['rpc']}"
        status=reads.read_native(upstream,'status',{})['result']
        if status['node_info']['id']!=m['registration']['node_id'] or status['node_info']['network']!=m['chain_id']:
            raise ValueError('fresh follower identity mismatch')
        height=int(status['sync_info']['latest_block_height'])-1
        if height<=int(restored[1]) or height<m['state_sync_anchor']['height']: raise ValueError('wait for post-snapshot committed history')
        local=reads.read_native(upstream,'block',{'height':height})['result']
        identity=(local['block_id']['hash'],local['block']['header']['app_hash'])
        for index in indexes:
            remote=call(index,'block',height=height)
            if (remote['block_id']['hash'],remote['block']['header']['app_hash'])!=identity:
                raise ValueError('post-snapshot block/AppHash differs from approved provider')
        cfg=home/'config/config.toml'; old=cfg.read_bytes(); metadata=(home/'node.json').read_bytes()
        try:
            fleet.set_toml(cfg,'statesync',{'enable':'false'})
            m['files']['config.toml']=fleet.digest_file(cfg)
            m['bootstrap_completed']={'invocation':invocation,'snapshot_height':int(restored[1]),'height':height,
                                      'block_hash':identity[0],'app_hash':identity[1]}
            atomic_public(home/'node.json',(json.dumps(m,indent=2)+'\n').encode())
        except Exception:
            atomic_public(cfg,old); atomic_public(home/'node.json',metadata); raise
        return m['bootstrap_completed']
