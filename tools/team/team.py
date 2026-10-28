"""Portable team setup. Uses only a fresh checkout and isolated PostgreSQL."""
from pathlib import Path
import argparse, json, os, re, secrets, shutil, socket, subprocess, sys

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.runtime/team'
PROFILE = STATE / 'profile.json'
PYTHON = ROOT / ('backend/.venv/Scripts/python.exe' if os.name == 'nt' else 'backend/.venv/bin/python')
PORTS = {'owner': (55441, 8121, 3121), 'teammate': (55442, 8122, 3122)}

def run(args, cwd=ROOT, env=None, capture=False):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env, check=True, capture_output=capture, text=True)
    return result.stdout.strip() if capture else None

def tool(name):
    path = shutil.which(name)
    if not path: raise RuntimeError(f'Install {name}; see docs/collaboration/README.md')
    return path

def fresh():
    if (ROOT/'backend/.env').exists(): raise RuntimeError('backend/.env exists; use a fresh clone instead of the business checkout')

def profile():
    data=json.loads(PROFILE.read_text(encoding='utf-8'))
    role=data['role']
    if role not in PORTS or (data['db_port'],data['api_port'],data['ui_port']) != PORTS[role]: raise RuntimeError('Profile target changed; refusing unverified database or ports')
    if not re.fullmatch(r'zhidian-team-(owner|teammate)-[a-f0-9]{8}',data['project']): raise RuntimeError('Invalid project')
    for k in ('db_password','secret_key','encryption_key','account_password'):
        if not re.fullmatch(r'[a-f0-9]{64}',data[k]): raise RuntimeError('Invalid generated credential')
    return data

def environment(p):
    env=os.environ.copy()
    env.update(DATABASE_URL=f"postgresql+psycopg://zhidian:{p['db_password']}@127.0.0.1:{p['db_port']}/zhidian_team",
      ENVIRONMENT='dev', SECRET_KEY=p['secret_key'], MODEL_CONFIG_ENCRYPTION_KEY=p['encryption_key'],
      TEAM_ACCOUNT_PASSWORD=p['account_password'], ZHIDIAN_TEAM_INITIALIZE='true',
      LLM_PROVIDER='mock', LLM_API_KEY='', EMBED_PROVIDER='mock', EMBED_API_KEY='', EMBED_DIM='128',
      VECTOR_BACKEND='pgvector', RERANK_API_KEY='', RERANK_ENABLED='false',
      INGEST_ASYNC='false', INGEST_QUEUE_BACKEND='inprocess', DOCUMENT_PARSER_MODE='native', DOCLING_BASE_URL='',
      MINIO_ENDPOINT='127.0.0.1:1', MINIO_ACCESS_KEY='isolated-dev', MINIO_SECRET_KEY=p['secret_key'],
      REDIS_URL='redis://127.0.0.1:1/0', SEED_DEMO_DATA='false', SEED_DEFAULT_PASSWORD='',
      DEMO_LOGIN_ENABLED='false', DEMO_LOGIN_PASSWORD='', COMPETITION_DEMO_ENABLED='false',
      CORS_ORIGINS=f"http://127.0.0.1:{p['ui_port']},http://localhost:{p['ui_port']}",
      VITE_API_TARGET=f"http://127.0.0.1:{p['api_port']}", PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    return env

def compose(p, *args):
    env=os.environ.copy(); env.update(POSTGRES_PASSWORD=p['db_password'],TEAM_DB_PORT=str(p['db_port']))
    run([tool('docker'),'compose','--project-name',p['project'],'-f',ROOT/'tools/team/compose.yml',*args],env=env)

def free_port(port):
    with socket.socket() as s:
        try: s.bind(('127.0.0.1',port))
        except OSError: raise RuntimeError(f'Port {port} is occupied. Stop the known service in its own terminal.')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['Init','Install','Doctor','Backend','Frontend','Check','DbStop'])
    parser.add_argument('--role',choices=PORTS,default='owner')
    args=parser.parse_args(); fresh(); git=tool('git')
    if args.action=='Init':
        old= subprocess.run([git,'config','--get','core.hooksPath'],cwd=ROOT,capture_output=True,text=True).stdout.strip()
        if old and old != '.githooks': raise RuntimeError('Existing hooks preserved; review before installing team hooks')
        if PROFILE.exists():
            p=profile()
            if p['role'] != args.role: raise RuntimeError('Existing role differs; use another checkout')
        else:
            STATE.mkdir(parents=True,exist_ok=True)
            db,api,ui=PORTS[args.role]
            p=dict(role=args.role,db_port=db,api_port=api,ui_port=ui,project=f'zhidian-team-{args.role}-{secrets.token_hex(4)}')
            p.update({k:secrets.token_hex(32) for k in ('db_password','secret_key','encryption_key','account_password')})
            PROFILE.write_text(json.dumps(p,indent=2),encoding='utf-8')
        run([git,'config','--local','core.hooksPath','.githooks'])
        run([git,'check-ignore','--quiet','.runtime/team/profile.json'])
        print('Local profile and push guard ready. Credentials stay in .runtime/team/profile.json.'); return
    p=profile(); env=environment(p)
    if args.action=='Install':
        if not PYTHON.exists():
            if sys.version_info[:2] != (3,12): raise RuntimeError('Use Python 3.12; pass -PythonExecutable to team.ps1 if needed')
            run([sys.executable,'-m','venv',ROOT/'backend/.venv'])
        run([PYTHON,'-m','pip','install','-r',ROOT/'backend/requirements.txt','-c',ROOT/'backend/constraints.txt'])
        run([tool('npm'),'ci'],cwd=ROOT/'web'); return
    if args.action=='Doctor':
        node=run([tool('node'),'--version'],capture=True)
        if int(node.lstrip('v').split('.')[0]) < 24: raise RuntimeError('Use Node.js 24 LTS')
        run([PYTHON,'-c','import fastapi, sqlalchemy, alembic, psycopg, pytest; print("Backend imports OK")'])
        if not (ROOT/'web/node_modules').is_dir(): raise RuntimeError('Run Install first')
        run([git,'check-ignore','--quiet','.runtime/team/profile.json'])
        if run([git,'config','--get','core.hooksPath'],capture=True) != '.githooks': raise RuntimeError('Run Init to enable push guard')
        compose(p,'config','--quiet')
        print(f"Doctor passed. Backend {p['api_port']}; frontend {p['ui_port']}; isolated PG {p['db_port']}. DB and API have not been started."); return
    if args.action=='DbStop': compose(p,'stop','pg'); return
    if args.action=='Backend':
        free_port(p['api_port']); compose(p,'up','-d','--wait','pg')
        run([PYTHON,'-m','alembic','upgrade','head'],cwd=ROOT/'backend',env=env)
        run([PYTHON,'-m','scripts.init_team_accounts'],cwd=ROOT/'backend',env=env)
        run([PYTHON,'-m','scripts.run_team_api','--port',p['api_port']],cwd=ROOT/'backend',env=env); return
    if args.action=='Frontend':
        free_port(p['ui_port'])
        run([tool('npm'),'run','dev','--','--host','127.0.0.1','--port',p['ui_port'],'--strictPort'],cwd=ROOT/'web',env=env); return
    if args.action=='Check':
        run([PYTHON,ROOT/'tools/team/guard.py','--repo',ROOT])
        run([PYTHON,'-m','pytest','-q'],cwd=ROOT/'backend',env=env)
        run([PYTHON,'-m','scripts.check_migrations'],cwd=ROOT/'backend',env=env)
        run([tool('npm'),'run','build'],cwd=ROOT/'web',env=env)

if __name__=='__main__':
    try: main()
    except (RuntimeError, FileNotFoundError, subprocess.CalledProcessError) as error:
        print(str(error),file=sys.stderr); raise SystemExit(1)
