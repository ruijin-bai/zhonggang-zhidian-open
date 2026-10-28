"""Check the actual isolated PG schema and refusal to discard source evidence."""
import os, subprocess, sys
from pathlib import Path
backend=Path(__file__).resolve().parents[2]/'backend'
sys.path.insert(0,str(backend))
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from app.db.models.regulation import RegulationFile
from sqlalchemy.engine import make_url

url=make_url(os.environ['DATABASE_URL'])
if url.get_backend_name() != 'postgresql' or url.database != 'zhidian_team' or url.username != 'zhidian' or url.host != '127.0.0.1' or url.port not in (55441,55442):
    raise RuntimeError('PG acceptance requires the isolated team target')
def migrate(*args, expected=0):
    result=subprocess.run([sys.executable,'-m','alembic',*args],cwd=backend,capture_output=True,text=True,encoding='utf-8')
    if expected==0 and result.returncode != 0: raise RuntimeError(result.stderr)
    if expected!=0 and result.returncode==0: raise AssertionError('Destructive downgrade unexpectedly succeeded')
    return result
migrate('upgrade','head')
engine=create_engine(url)
with engine.connect() as c:
    assert engine.dialect.name=='postgresql'
    assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0021'
    for table,required in {'decision_rule':{'source_kind','asset_version_id','retrieval_unit_id'},'regulation_file':{'source_confirmation'},'business_case':{'facts','decision_snapshot'}}.items():
        assert required <= {col['name'] for col in inspect(engine).get_columns(table)}, table
with engine.begin() as c:
    assert c.execute(text('SELECT count(*) FROM regulation_file')).scalar_one()==0, 'Use a new empty acceptance database'
with Session(engine) as session:
    session.add(RegulationFile(file_id='synthetic-pg-preservation',title='Synthetic PG acceptance',version='1',source_confirmation={'kind':'maintainer','confirmed':True}))
    session.commit()
result=migrate('downgrade','0020',expected=1)
assert '回退会丢失确认记录' in result.stderr
with engine.connect() as c:
    assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0021'
    value=c.execute(text("SELECT source_confirmation FROM regulation_file WHERE file_id='synthetic-pg-preservation'")).scalar_one()
    assert value['confirmed'] is True
with engine.begin() as c:
    c.execute(text("DELETE FROM regulation_file WHERE file_id='synthetic-pg-preservation'"))
engine.dispose()
print('PostgreSQL passed: actual dialect, head 0021, source schema, confirmation preservation and destructive downgrade refusal.')
