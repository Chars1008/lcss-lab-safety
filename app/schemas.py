"""Shared Pydantic data contracts and Enums across core, db, and ui layers."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ControlLevel(str, Enum):
    NORMAL = "NORMAL"
    TEACHER_ONLY = "TEACHER_ONLY"
    PROHIBITED = "PROHIBITED"


class CabinetType(str, Enum):
    FLAMMABLE = "FLAMMABLE"
    CORROSIVE = "CORROSIVE"
    GENERAL = "GENERAL"
    FRIDGE_4C = "FRIDGE_4C"
    FREEZER_M20 = "FREEZER_M20"
    TOXIC = "TOXIC"


class GroupSource(str, Enum):
    CAMEO_DB = "CAMEO_DB"
    RDKIT_INFERRED = "RDKIT_INFERRED"
    MANUAL = "MANUAL"


class ItemType(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    PREPARED = "PREPARED"


class ItemStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    EMPTY = "EMPTY"
    DISPOSED = "DISPOSED"


class InventoryAction(str, Enum):
    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"
    MOVE = "MOVE"
    ADJUST = "ADJUST"
    DISPOSE = "DISPOSE"


class DocType(str, Enum):
    SUPPLIER_OFFICIAL = "SUPPLIER_OFFICIAL"
    GENERATED_DRAFT = "GENERATED_DRAFT"


class CompatibilityLevel(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    CAUTION = "CAUTION"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


class CompatibilityIssue(BaseModel):
    """Result of pairwise chemical compatibility check."""

    chem_a_cas: str
    chem_b_cas: str
    chem_a_name: str = ""
    chem_b_name: str = ""
    level: CompatibilityLevel
    hazards: list[str] = Field(default_factory=list)
    matched_groups: list[tuple[str, str]] = Field(default_factory=list)
    summary_zh: str = ""
    recommendation_zh: str = ""
    inference_note: str = ""


class CabinetCheckResult(BaseModel):
    """Result of checking a chemical against a target cabinet type."""

    compatible: bool
    level: CompatibilityLevel
    message_zh: str = ""


class SDSPayload(BaseModel):
    """Structured 16-section Taiwanese GHS Safety Data Sheet payload."""

    cas_number: str
    name_zh: str = ""
    name_en: str = ""
    formula: str = ""
    molecular_weight: Optional[float] = None
    smiles: str = ""
    inchikey: str = ""

    # Section 1: Chemical & Company Identification
    supplier_info: str = ""
    emergency_phone: str = "119 / 校安中心"
    recommended_use: str = "實驗室教學與研究用途"

    # Section 2: Hazard Identification
    ghs_pictograms: list[str] = Field(default_factory=list)
    signal_word: Optional[str] = None
    h_codes: list[str] = Field(default_factory=list)
    p_codes: list[str] = Field(default_factory=list)
    h_statements_zh: list[str] = Field(default_factory=list)
    p_statements_zh: list[str] = Field(default_factory=list)
    hazard_classification_zh: str = ""

    # Section 3: Composition
    composition_note: str = "純物質 (100%)"

    # Sections 4 - 16
    section_4_first_aid: str = "眼睛接觸：立即以大量清水沖洗至少 15 分鐘並就醫。皮膚接觸：立即脫去污染衣物並以大量清水沖洗。吸入：移至空氣新鮮處。食入：勿催吐，立即就醫。"
    section_5_fire_fighting: str = "依周圍火勢選用乾粉、二氧化碳、抗醇泡沫或水霧滅火。火場應佩戴自給式呼吸器（SCBA）。"
    section_6_accidental_release: str = "穿戴適當個人防護具，確保通風，避免流入下水道；以惰性吸收材吸附後依廢棄物規定處理。"
    section_7_handling_storage: str = "於通風櫥內操作，遠離火源、熱源與不相容物質。容器密閉並存放於適當屬性之藥品櫃。"
    section_8_exposure_controls: str = "建議佩戴化學防濺護目鏡、耐化學手套（Nitrile 或 Neoprene）、實驗衣，並於排氣櫃操作。"
    section_9_physical_chemical: str = "請參閱原廠 SDS 或物化性質資料庫。"
    section_10_stability_reactivity: str = "常溫常壓下安定；避免接觸不相容之強酸、強鹼或強氧化劑。"
    section_11_toxicological: str = "詳見原廠毒理學資料；操作時避免吸入蒸氣或皮膚直接接觸。"
    section_12_ecological: str = "避免未經處理排入環境水體或土壤。"
    section_13_disposal: str = "依台灣《廢棄物清理法》及學校環安衛中心規定分類集中委託合法清除機構處理。"
    section_14_transport: str = "依聯合國危險物品運輸規定及供應商包裝標示辦理。"
    section_15_regulatory: str = "適用台灣勞動部《危害性化學品標示及通識規則》及《職業安全衛生法》相關規定。"
    section_16_other: str = "系統彙整內部參考版（資料來源：PubChem / 台灣 GHS，正式法規依據請以供應商原廠 SDS 為準）。"

    data_source: str = "LOCAL_CACHE"
    generated_at: datetime = Field(default_factory=datetime.now)


class ResolvedChemical(BaseModel):
    """Normalized output from ChemResolver."""

    cas_number: str
    name_zh: str = ""
    name_en: str = ""
    formula: str = ""
    molecular_weight: Optional[float] = None
    smiles: str = ""
    inchikey: str = ""
    ghs_pictograms: list[str] = Field(default_factory=list)
    signal_word: Optional[str] = None
    h_codes: list[str] = Field(default_factory=list)
    p_codes: list[str] = Field(default_factory=list)
    reactive_groups: list[str] = Field(default_factory=list)
    group_source: GroupSource = GroupSource.MANUAL
    control_level: ControlLevel = ControlLevel.NORMAL
    sds_payload: Optional[SDSPayload] = None
    data_source: str = "LOCAL_CACHE"


class LabelRequest(BaseModel):
    """Data required to render a GHS bottle label or prepared reagent label."""

    item_type: ItemType = ItemType.COMMERCIAL
    name_zh: str
    name_en: str = ""
    cas_number: str = ""
    barcode: str
    ghs_pictograms: list[str] = Field(default_factory=list)
    signal_word: Optional[str] = None
    hazard_summary: str = ""
    concentration: str = ""
    prepared_by: str = ""
    prepared_date: Optional[date] = None
    expiry_date: Optional[date] = None
    location_label: str = ""
