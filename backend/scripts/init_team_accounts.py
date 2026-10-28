"""Initialize development accounts only, restricted to the team database."""
import asyncio
import os
from sqlalchemy import select
from sqlalchemy.engine import make_url
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal, engine
from app.db.models.org import OrgUnit
from app.db.models.user import User
from app.db.models.permission import Permission

async def main():
    settings=get_settings(); url=make_url(settings.DATABASE_URL)
    if os.getenv('ZHIDIAN_TEAM_INITIALIZE') != 'true' or settings.ENVIRONMENT != 'dev' or url.database != 'zhidian_team' or url.host != '127.0.0.1' or url.username != 'zhidian' or url.port not in (55441,55442):
        raise RuntimeError('Initialization refused: target is not an isolated team database')
    password=os.environ.get('TEAM_ACCOUNT_PASSWORD','')
    if len(password) != 64: raise RuntimeError('Missing generated account credential')
    async with SessionLocal() as s:
        if (await s.execute(select(User.user_id).limit(1))).first():
            print('Existing accounts preserved; no reset or seed.'); return
        s.add(OrgUnit(org_id='org_team_dev',name='本机开发组织',org_type='headquarter',path='/development'))
        await s.flush()
        for role,name,clearance in [('R1','employee','internal'),('R2','reviewer','confidential'),('R3','kbadmin','secret'),('R4','admin','secret')]:
            s.add(User(username=name,hashed_password=hash_password(password),org_id='org_team_dev',post='开发验证',role=role,secret_clearance=clearance))
            s.add(Permission(role=role,org_scope='/',secret_level=clearance,domain='*'))
        await s.commit()
        print('Four local development accounts created. No regulations, cases, rules or business samples seeded.')
    await engine.dispose()

if __name__=='__main__':
    if os.name=='nt': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
