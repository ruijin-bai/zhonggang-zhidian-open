"""Batch-import a regulation library directory into the knowledge base.

Scans a folder tree, recognises:
  * classification folders (``NN-名称``) → 制度分类标签
  * regulation folders (a folder containing files) → 一份制度
  * document roles inside a regulation folder:
      main / attachment / history / review_opinion / notice / training

Clause-level parsing (切条款) is intentionally NOT performed here — this
import only groups files and tags them, so a library can be onboarded quickly.
Run with ``--dry-run`` first to preview the grouping without writing anything.

Usage:
    python -m scripts.import_library --root "D:/path/制度库" --dry-run
    python -m scripts.import_library --root "D:/path/制度库"
"""
from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path

from sqlalchemy import insert, or_, select

from app.adapters.storage.object_store import get_object_store
from app.db import models as _models  # noqa: F401  register all tables
from app.db.base import Base, gen_id
from app.db.models.regulation import RegulationFile
from app.db.models.regulation_document import RegulationDocument
from app.db.models.tag import Tag, regulation_tag
from app.db.session import SessionLocal, engine

CAT_DIR_RE = re.compile(r"^\d{2}[-—_.、]?\s*")
# 子目录名 → 文档类型
SPECIAL_DIRS = {
    "_历史版本": "history",
    "_版本比对": "history",
    "_会审意见": "review_opinion",
    "附件": "attachment",
}
# 宣贯/培训材料关键字
TRAINING_KEYS = ("宣贯", "宣讲", "课件", "培训", "思维导图", "解读")
MIME_BY_EXT = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ofd": "application/octet-stream",
    ".ai": "application/postscript",
    ".zip": "application/zip",
}


def category_name(dirname: str) -> str:
    return CAT_DIR_RE.sub("", dirname).strip()


def is_category_dir(dirname: str) -> bool:
    return bool(CAT_DIR_RE.match(dirname))


def classify_document(rel_parts: tuple[str, ...], filename: str) -> str:
    for part in rel_parts:
        if part in SPECIAL_DIRS:
            return SPECIAL_DIRS[part]
    if filename.startswith("附件") or filename.startswith("附表"):
        return "attachment"
    if "通知" in filename and ("印发" in filename or "关于" in filename):
        return "notice"
    if any(k in filename for k in TRAINING_KEYS):
        return "training"
    return "main"


class Regulation:
    """A discovered regulation and its files, grouped by document role."""

    def __init__(self, title: str, categories: list[str]):
        self.title = title
        self.categories = categories
        self.files: list[tuple[str, Path]] = []  # (doc_type, file_path)


def scan(root: Path) -> list[Regulation]:
    """Walk the tree and collect regulations with their classified files."""
    found: list[Regulation] = []

    def walk(directory: Path, categories: list[str]) -> None:
        subdirs = sorted([p for p in directory.iterdir() if p.is_dir() and not p.name.startswith(".")])
        files = sorted([p for p in directory.iterdir() if p.is_file() and not p.name.startswith(".")])

        # Direct files at this level are single-file regulations.
        if files:
            for f in files:
                reg = Regulation(title=f.stem, categories=categories)
                reg.files.append(("main", f))
                found.append(reg)

        for sub in subdirs:
            if is_category_dir(sub.name):
                walk(sub, categories + [category_name(sub.name)])
            elif sub.name in SPECIAL_DIRS:
                # A special sub-folder belongs to a parent regulation folder;
                # handled when the parent folder is processed.
                continue
            else:
                # A regulation folder: gather every file recursively.
                reg = Regulation(title=sub.name, categories=categories)
                for p in sorted(sub.rglob("*")):
                    if not p.is_file() or p.name.startswith("."):
                        continue
                    rel = p.relative_to(sub)
                    rel_parts = tuple(rel.parts[:-1])
                    reg.files.append((classify_document(rel_parts, p.name), p))
                found.append(reg)

    walk(root, [])
    return found


def pick_main(files: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    """Keep at most one main file; demote extra body files to attachment."""
    mains = [f for f in files if f[0] == "main"]
    if len(mains) <= 1:
        return files
    # Prefer common editable formats, then by filename length (closest to title).
    order = {".docx": 0, ".pdf": 1, ".doc": 2, ".ofd": 3}
    mains.sort(key=lambda f: (order.get(f[1].suffix.lower(), 99), len(f[1].name)))
    keep = mains[0][1]
    return [("attachment" if f[0] == "main" and f[1] != keep else f[0], f[1]) for f in files]


def build_output(files: list[tuple[str, Path]]) -> list[tuple[str, str, str]]:
    """Return (doc_type, title, object_key) after copying files into storage."""
    store = get_object_store()
    out: list[tuple[str, str, str]] = []
    for doc_type, path in files:
        data = path.read_bytes()
        key = f"{gen_id('obj')}_{path.name}"
        object_key = store.put_object(key, data, MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream"))
        out.append((doc_type, path.name, object_key))
    return out


async def run(root: Path, dry_run: bool) -> None:
    regulations = scan(root)
    print(f"[import] 扫描完成：识别 {len(regulations)} 份制度\n")

    if dry_run:
        for reg in regulations:
            print(f"▸ 制度：{reg.title}")
            print(f"   分类：{' / '.join(reg.categories) or '(无)'}")
            for doc_type, path in reg.files:
                print(f"     - [{doc_type}] {path.name}")
        print(f"\n[dry-run] 未写入任何数据。确认无误后去掉 --dry-run 再执行。")
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    store = get_object_store()
    imported = skipped = 0

    async with SessionLocal() as session:
        for reg in regulations:
            code = reg.title
            exists = (
                await session.execute(
                    select(RegulationFile.file_id).where(
                        (RegulationFile.regulation_code == code) | (RegulationFile.title == code)
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                skipped += 1
                print(f"[skip] 已存在：{code}")
                continue

            files = pick_main(reg.files)
            reg_file = RegulationFile(
                regulation_code=code,
                title=reg.title,
                source=str(root),
                version="v1",
                status="current",
                domain="*",
                lang="zh",
                secret_level="internal",
                org_path="/",
            )
            session.add(reg_file)
            await session.flush()

            # Classification tags.
            for cat in reg.categories:
                tag = (
                    await session.execute(
                        select(Tag).where(Tag.tag_type == "制度分类", Tag.tag_value == cat)
                    )
                ).scalar_one_or_none()
                if tag is None:
                    tag = Tag(tag_type="制度分类", tag_value=cat)
                    session.add(tag)
                    await session.flush()
                await session.execute(
                    insert(regulation_tag).values(file_id=reg_file.file_id, tag_id=tag.tag_id)
                )

            # Documents (copy bytes into object storage).
            for idx, (doc_type, path) in enumerate(files):
                data = path.read_bytes()
                key = f"{gen_id('obj')}_{path.name}"
                object_key = store.put_object(key, data, MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream"))
                if doc_type == "main" and reg_file.object_key is None:
                    reg_file.object_key = object_key
                session.add(
                    RegulationDocument(
                        file_id=reg_file.file_id,
                        doc_type=doc_type,
                        title=path.stem,
                        filename=path.name,
                        object_key=object_key,
                        mime=MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream"),
                        sort_order=idx,
                        source_path=str(path),
                    )
                )

            imported += 1
            print(f"[ok] {reg.title}  ← {' / '.join(reg.categories) or '(无分类)'}  （{len(files)} 个文档）")

        await session.commit()

    print(f"\n[import] 完成：新导入 {imported} 份，跳过 {skipped} 份。")


def main() -> None:
    parser = argparse.ArgumentParser(description="批量导入制度库")
    parser.add_argument("--root", required=True, help="制度库根目录路径")
    parser.add_argument("--dry-run", action="store_true", help="仅预览归类结果，不写入")
    args = parser.parse_args()
    asyncio.run(run(Path(args.root), args.dry_run))


if __name__ == "__main__":
    main()
