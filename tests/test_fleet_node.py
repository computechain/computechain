import json
import hashlib
from pathlib import Path
import pytest
from computechain.scripts import fleet_node
from computechain.scripts import install_multisite


def test_operator_selection_never_targets_another_fleet(tmp_path,monkeypatch):
    monkeypatch.setattr(install_multisite,'safe_root',lambda root:Path(root))
    home=tmp_path/'approved-chain/nodes/validator-aa'; home.mkdir(parents=True)
    manifest={'home_root':str(tmp_path),'chain_id':'approved-chain','node':{'name':'validator-aa'}}
    (home/'node.json').write_text(json.dumps(manifest))
    assert [n for n,_,_ in fleet_node.selected(tmp_path,'approved-chain',[])]==['validator-aa']
    with pytest.raises(ValueError,match='distinct installed'):
        fleet_node.selected(tmp_path,'approved-chain',['validator-aa','validator-aa'])
    with pytest.raises(ValueError,match='distinct installed'):
        fleet_node.selected(tmp_path,'approved-chain',['validator-other'])
    manifest['chain_id']='foreign-chain'; (home/'node.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='identity mismatch'):
        fleet_node.selected(tmp_path,'approved-chain',[])


def test_operator_selection_rejects_symlink_chain(tmp_path,monkeypatch):
    monkeypatch.setattr(install_multisite,'safe_root',lambda root:Path(root))
    (tmp_path/'actual').mkdir(); (tmp_path/'approved-chain').symlink_to(tmp_path/'actual',target_is_directory=True)
    with pytest.raises(ValueError,match='symlinks'):
        fleet_node.selected(tmp_path,'approved-chain',[])


@pytest.mark.parametrize('path',['/','/root','/root/../computechain-node','/tmp/computechain-node'])
def test_installer_scope_is_only_dedicated_operator_home(path):
    with pytest.raises(ValueError,match='dedicated'):
        install_multisite.safe_root(path)


def test_privileged_artifact_copy_uses_only_the_approved_bytes(tmp_path):
    source=tmp_path/'engine-compose'; target=tmp_path/'root-compose'
    approved=b'services: {}\n'
    digest=hashlib.sha256(approved).hexdigest()
    source.write_bytes(b'changed after preflight')
    with pytest.raises(ValueError,match='changed before'):
        install_multisite.copy_owned(source,target,0o644,digest)
    assert not target.exists()
    source.write_bytes(approved)
    install_multisite.copy_owned(source,target,0o644,digest)
    assert target.read_bytes()==approved
    source.write_bytes(b'changed during another installation')
    with pytest.raises(ValueError,match='changed before'):
        install_multisite.copy_owned(source,target,0o644,digest)
    assert target.read_bytes()==approved


def test_privileged_artifact_copy_never_follows_a_source_symlink(tmp_path):
    source=tmp_path/'link'; actual=tmp_path/'actual'; target=tmp_path/'target'
    actual.write_bytes(b'approved'); source.symlink_to(actual)
    with pytest.raises(OSError):
        install_multisite.copy_owned(source,target,0o644,hashlib.sha256(b'approved').hexdigest())
    assert not target.exists()


def test_privileged_installer_parses_only_approved_manifest_bytes(tmp_path,monkeypatch):
    home=tmp_path/'approved-chain/nodes/validator-aa'; home.mkdir(parents=True)
    manifest={'home_root':str(tmp_path),'chain_id':'approved-chain','node':{'name':'validator-aa'},
              'application_home':str(tmp_path/'approved-chain/apps/validator-aa'),'files':{}}
    raw=json.dumps(manifest).encode(); (home/'node.json').write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest()
    # A hash-then-read_text implementation must not be able to parse a second,
    # different manifest owned by the engine user after approving the first one.
    monkeypatch.setattr(Path,'read_text',lambda *a,**k: (_ for _ in ()).throw(AssertionError('second path read')))
    assert install_multisite.checked_artifacts(tmp_path,'approved-chain','validator-aa',digest)==(home,manifest)
    with pytest.raises(ValueError,match='manifest SHA'):
        install_multisite.checked_artifacts(tmp_path,'approved-chain','validator-aa','f'*64)


def test_privileged_installer_refuses_symlink_manifest(tmp_path):
    home=tmp_path/'approved-chain/nodes/validator-aa'; home.mkdir(parents=True)
    actual=tmp_path/'actual'; actual.write_bytes(b'{}'); (home/'node.json').symlink_to(actual)
    with pytest.raises(OSError):
        install_multisite.checked_artifacts(tmp_path,'approved-chain','validator-aa',hashlib.sha256(b'{}').hexdigest())
