"""Run the isolated development API with the Windows psycopg-compatible loop."""
import argparse
import asyncio
import os
import uvicorn
from sqlalchemy.engine import make_url
from app.core.config import get_settings

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,required=True)
    args=parser.parse_args(); settings=get_settings(); url=make_url(settings.DATABASE_URL)
    expected={55441:8121,55442:8122}
    if settings.ENVIRONMENT!='dev' or url.database!='zhidian_team' or url.host!='127.0.0.1' or url.username!='zhidian' or expected.get(url.port)!=args.port:
        raise RuntimeError('Team API refused: target or port is not isolated')
    if os.name=='nt': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run('app.main:app',host='127.0.0.1',port=args.port,loop='asyncio')

if __name__=='__main__': main()
