"""Team setup must not inherit business targets or initialize arbitrary databases."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

def module():
    path=Path(__file__).resolve().parents[2]/'tools/team/team.py'
    spec=importlib.util.spec_from_file_location('team_safety_subject',path)
    loaded=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded

def valid_profile():
    return dict(role='owner',db_port=55441,api_port=8121,ui_port=3121,project='zhidian-team-owner-01234567',**{k:'a'*64 for k in ('db_password','secret_key','encryption_key','account_password')})

def test_team_environment_does_not_inherit_business_connections(monkeypatch):
    monkeypatch.setenv('DATABASE_URL','postgresql://original/production')
    monkeypatch.setenv('LLM_API_KEY','original-private-value')
    monkeypatch.setenv('SEED_DEMO_DATA','true')
    env=module().environment(valid_profile())
    assert env['DATABASE_URL'].endswith('@127.0.0.1:55441/zhidian_team')
    assert env['LLM_API_KEY']==env['EMBED_API_KEY']==env['RERANK_API_KEY']==''
    assert env['SEED_DEMO_DATA']=='false' and env['DEMO_LOGIN_ENABLED']=='false'
    assert env['MINIO_ENDPOINT']=='127.0.0.1:1'
    assert env['VITE_API_TARGET']=='http://127.0.0.1:8121'

def test_profile_refuses_target_drift(tmp_path):
    team=module(); team.PROFILE=tmp_path/'profile.json'
    p=valid_profile(); p['db_port']=5432
    team.PROFILE.write_text(json.dumps(p),encoding='utf-8')
    with pytest.raises(RuntimeError,match='target changed'): team.profile()

def test_team_setup_refuses_checkout_with_private_env(tmp_path):
    team=module(); team.ROOT=tmp_path
    (tmp_path/'backend').mkdir(); (tmp_path/'backend/.env').touch()
    with pytest.raises(RuntimeError,match='fresh clone'): team.fresh()

async def test_account_initialization_refuses_non_team_database(monkeypatch):
    from scripts import init_team_accounts
    monkeypatch.setenv('ZHIDIAN_TEAM_INITIALIZE','true')
    monkeypatch.setattr(init_team_accounts,'get_settings',lambda:SimpleNamespace(DATABASE_URL='sqlite+aiosqlite:///:memory:',ENVIRONMENT='dev'))
    with pytest.raises(RuntimeError,match='not an isolated'): await init_team_accounts.main()

def test_private_path_guard_allows_storage_adapter_but_rejects_uploaded_files():
    path=Path(__file__).resolve().parents[2]/'tools/team/guard.py'
    spec=importlib.util.spec_from_file_location('team_guard_subject',path)
    guard=importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
    assert not guard.forbidden('backend/app/adapters/storage/object_store.py')
    assert guard.forbidden('backend/storage/original.pdf')
    assert guard.forbidden('.runtime/team/profile.json')
    assert guard.forbidden('backend/.env')
    assert guard.forbidden('docs/reference/application.docx')
