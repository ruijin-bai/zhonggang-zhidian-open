"""Authoritative V2 benchmark selection and exceptional package boundaries."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.assets.taxonomy import AssetType


BENCHMARK_TITLES = [
    "员工职业发展管理及评聘办法",
    "适度市场化管理制度等3项制度【中港战发2018-1654号】",
    "视觉识别系统及资料使用说明",
    "中国港湾安全质量管理部（应急管理办公室）规章制度汇编20250606",
    "中国港湾典型EPC项目管理标准化手册（试行）",
    "中非区域管理中心核心管控权限",
    "中部非洲区域管理中心施工安全重大事故隐患判定标准清单(1)",
    "中国港湾深入贯彻中央八项规定精神正负面清单",
    "项目实施策划书模板2025",
    "中国港湾境外项目实施管理办法（修订）",
    "中国港湾境外项目全生命周期管理规定（修订）",
    "B类驻外机构管理项目实施管理手册-总承包模式",
    "《HSE标准化指导手册》审核V02-20200422",
    "中国港湾境外项目管理层级实施办法（试行）",
    "中国港湾中部非洲区域管理中心危险作业施工许可管理程序",
    "中国港湾工程技术方案管理办法",
    "中国港湾企业年金方案实施细则",
    "中部非洲区域管理中心分包商以公司名义订立合同管理细则【中港中非发2022-6号】",
    "中国港湾出海优势物资装备品类清单",
    "中国交通建设集团有限公司合规行为准则（试行）",
]


@dataclass(frozen=True)
class SplitAssetSpec:
    title: str
    asset_type: str
    body_filename_contains: str
    extra_filename_contains: tuple[str, ...] = ()


SPECIAL_SPLIT_PACKAGES: dict[str, tuple[SplitAssetSpec, ...]] = {
    "适度市场化管理制度等3项制度【中港战发2018-1654号】": (
        SplitAssetSpec(
            "中国港湾工程有限责任公司适度市场化管理制度",
            AssetType.REGULATION.value,
            "附件2 中国港湾工程有限责任公司适度市场化管理制度",
            ("附件1《中国港湾工程有限责任公司适度市场化管理制度》编制说明",),
        ),
        SplitAssetSpec(
            "中国港湾工程有限责任公司施工类合作方管理实施细则",
            AssetType.IMPLEMENTATION_RULE.value,
            "附件3 中国港湾工程有限责任公司施工类合作方管理实施细则",
        ),
        SplitAssetSpec(
            "中国港湾工程有限责任公司勘察设计类合作方管理实施细则",
            AssetType.IMPLEMENTATION_RULE.value,
            "附件4 中国港湾工程有限责任公司勘察设计类合作方管理实施细则",
        ),
    ),
}
