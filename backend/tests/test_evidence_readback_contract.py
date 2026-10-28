"""Owned historical evidence and document download authorization contracts."""
from datetime import date
import hashlib
import httpx
from app.main import app
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.db.models.regulation_document import RegulationDocument
from app.db.models.qa import QASession, QACitation
from app.db.models.feedback import QAFeedback
from app.db.models.permission import Permission
from app.services.auth.auth_service import issue_token
from test_read_authorization import _seed_user

async def test_historical_citation_is_owned_hash_bound_and_respects_current_permission(session):
    owner = await _seed_user(session, 'history_owner', 'R1')
    stranger = await _seed_user(session, 'history_stranger', 'R1')
    session.add(Permission(role='R1',org_scope='/',secret_level='internal',domain='*'))
    text='当时已审核的完整制度正文。'
    digest=hashlib.sha256(text.encode()).hexdigest()
    file=RegulationFile(file_id='history_file',title='历史制度',status='retired',secret_level='internal',org_path='/')
    session.add(file); await session.flush()
    clause=Clause(clause_id='history_clause',file_id=file.file_id,clause_no='第1条',content=text,content_hash=digest,status='isolated',secret_level='internal')
    qa=QASession(session_id='history_qa',user_id=owner.user_id,question='当时的要求？')
    session.add_all([clause,qa]); await session.flush()
    citation=QACitation(session_id=qa.session_id,clause_id=clause.clause_id,file_title=file.title,clause_no='第1条',excerpt='当时已审核',content_hash=digest)
    session.add(citation); await session.commit()
    path='/api/v1/clauses/history_clause'
    headers={'Authorization':f'Bearer {issue_token(owner)}'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get(path,headers=headers)).status_code==404
        history=await client.get(path,params={'session_id':qa.session_id},headers=headers)
        assert history.status_code==200, history.text
        assert history.json()['data']['historical'] is True
        assert history.json()['data']['snapshot_only'] is False
        assert history.json()['data']['content']==text
        assert (await client.get(path,params={'session_id':qa.session_id},headers={'Authorization':f'Bearer {issue_token(stranger)}'})).status_code==404
        citation.content_hash='mismatch'; await session.commit()
        snapshot=await client.get(path,params={'session_id':qa.session_id},headers=headers)
        assert snapshot.json()['data']['snapshot_only'] is True
        assert snapshot.json()['data']['content']==citation.excerpt
        file.secret_level='confidential'; await session.commit()
        assert (await client.get(path,params={'session_id':qa.session_id},headers=headers)).status_code==404

async def test_document_download_checks_membership_release_and_permission(session,monkeypatch):
    user=await _seed_user(session,'document_reader','R1')
    session.add(Permission(role='R1',org_scope='/',secret_level='internal',domain='*'))
    visible=RegulationFile(file_id='doc_visible',title='可读制度',status='current',secret_level='internal',org_path='/')
    hidden=RegulationFile(file_id='doc_hidden',title='秘密制度',status='current',secret_level='secret',org_path='/')
    session.add_all([visible,hidden]); await session.flush()
    session.add_all([RegulationDocument(doc_id='visible_attachment',file_id=visible.file_id,filename='附件.txt',object_key='test-visible'),RegulationDocument(doc_id='hidden_attachment',file_id=hidden.file_id,filename='隐藏.txt',object_key='test-hidden')]);await session.commit()
    class Store:
        def get_object(self,key): return b'verified download'
    monkeypatch.setattr('app.api.v1.router_regulation.get_object_store',lambda:Store())
    headers={'Authorization':f'Bearer {issue_token(user)}'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        good=await client.get('/api/v1/regulations/doc_visible/documents/visible_attachment/download',headers=headers)
        assert good.status_code==200 and good.content==b'verified download'
        assert 'filename*=' in good.headers['content-disposition']
        assert (await client.get('/api/v1/regulations/doc_visible/documents/hidden_attachment/download',headers=headers)).status_code==404
        assert (await client.get('/api/v1/regulations/doc_hidden/documents/hidden_attachment/download',headers=headers)).status_code==404
        visible.status='pending_review';await session.commit()
        assert (await client.get('/api/v1/regulations/doc_visible/documents/visible_attachment/download',headers=headers)).status_code==404

async def test_correction_queue_excludes_reactions_and_evaluation_traffic(session):
    reviewer=await _seed_user(session,'feedback_reviewer','R2')
    employee=await _seed_user(session,'feedback_employee','R1')
    normal=QASession(session_id='feedback_normal',user_id=employee.user_id,question='实际问题',is_evaluation=False)
    evaluation=QASession(session_id='feedback_eval',user_id=employee.user_id,question='评测问题',is_evaluation=True)
    session.add_all([normal,evaluation]);await session.flush()
    session.add_all([QAFeedback(fb_id='actual_correction',session_id=normal.session_id,user_id=employee.user_id,type='correct',content='需复核'),QAFeedback(fb_id='thumb',session_id=normal.session_id,user_id=employee.user_id,type='like'),QAFeedback(fb_id='eval_correction',session_id=evaluation.session_id,user_id=employee.user_id,type='correct',content='合成测试')]);await session.commit()
    headers={'Authorization':f'Bearer {issue_token(reviewer)}'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/api/v1/qa/feedbacks',headers=headers)
        assert response.status_code==200
        assert [row['fb_id'] for row in response.json()['data']]==['actual_correction']
        assert (await client.post('/api/v1/qa/feedbacks/thumb/resolve',json={'note':'不应处理'},headers=headers)).status_code==404
        assert (await client.post('/api/v1/qa/feedbacks/eval_correction/resolve',json={'note':'不应处理'},headers=headers)).status_code==404
