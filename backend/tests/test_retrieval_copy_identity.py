"""Equivalent import copies do not duplicate evidence or bypass file RBAC."""
from sqlalchemy import select
from app.db.models.asset import AssetDocument, AssetVersionDocument
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.db.models.permission import Permission
from app.db.models.user import User
from app.services.rag.retriever import RetrievedClause, RetrieverService
from test_compound_retrieval import _seed_compound_unit

def _candidate(identifier,text,*,file_id='file-a',version='v1',kind='legacy_clause',mapping=None):
    return RetrievedClause(Clause(clause_id=identifier,content=text,file_id=file_id,content_hash=identifier),RegulationFile(file_id=file_id,title='合成来源',version=version),0.8,kind,{'legacy_file_id':mapping} if mapping else {})

def test_imported_whitespace_copy_collapses_but_other_sources_and_versions_remain():
    old=_candidate('old','党群工作部 是归口\n管理部门。')
    migrated=_candidate('unit','党群工作部是归口 管理部门。',file_id='asset-a',kind='compound_unit',mapping='file-a')
    different_file=_candidate('other','党群工作部是归口管理部门。',file_id='file-b')
    different_version=_candidate('v2','党群工作部是归口管理部门。',version='v2')
    changed_copy=_candidate('changed','总部是归口管理部门。',file_id='asset-a',kind='compound_unit',mapping='file-a')
    rows=RetrieverService._merge_sources([migrated,changed_copy],[old,different_file,different_version],10)
    assert {row.clause.clause_id for row in rows}=={'unit','other','v2','changed'}
    assert len(rows)==4

async def test_compound_unit_internal_does_not_expose_confidential_source_file(session):
    unit,asset=await _seed_compound_unit(session)
    link=(await session.execute(select(AssetVersionDocument).where(AssetVersionDocument.version_id==unit.version_id))).scalar_one()
    document=await session.get(AssetDocument,link.document_id)
    document.secret_level='confidential';await session.flush()
    user=User(user_id='synthetic-reader',role='R1',secret_clearance='internal')
    permissions=[Permission(role='R1',org_scope='/',secret_level='internal',domain='*')]
    rows=await RetrieverService().retrieve(session,user,permissions,'境外项目审批',top_k=5,min_score=0)
    assert rows==[]
