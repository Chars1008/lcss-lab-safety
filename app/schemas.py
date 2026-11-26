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
    """Structured 16-section Taiwanese GHS Safety Data Sheet payload (EPA/OSHA format)."""

    cas_number: str
    epa_control_no: str = "－"
    name_zh: str = ""
    name_en: str = ""
    other_names: str = "－"
    synonyms: str = "－"
    formula: str = ""
    molecular_weight: Optional[float] = None
    smiles: str = ""
    inchikey: str = ""
    concentration_pct: str = "100%"

    # Section 1: Chemical & Company Identification
    supplier_info: str = ""
    emergency_phone: str = "119 / 校安中心"
    recommended_use: str = "實驗室教學、分析與研究用途"
    restricted_use: str = "僅限受訓人員於實驗室使用"

    # Section 2: Hazard Identification
    ghs_pictograms: list[str] = Field(default_factory=list)
    signal_word: Optional[str] = None
    h_codes: list[str] = Field(default_factory=list)
    p_codes: list[str] = Field(default_factory=list)
    h_statements_zh: list[str] = Field(default_factory=list)
    p_statements_zh: list[str] = Field(default_factory=list)
    hazard_classification_zh: str = ""
    hazard_classifications: list[str] = Field(default_factory=list)
    other_hazards: str = "－"

    # Section 3: Composition
    composition_note: str = "純物質 (100%)"

    # Section 4: First Aid Measures
    first_aid_ingestion: str = "1. 若患者意識不清或痙攣，切勿經口餵食任何東西。\n2. 若意識清楚，讓其用水徹底漱口，切勿催吐。\n3. 立即就醫。"
    first_aid_inhalation: str = "1. 施救前先做好自身防護。\n2. 將患者移至空氣新鮮處，保持呼吸舒適。\n3. 若呼吸困難或持續不適，立即就醫。"
    first_aid_eye: str = "1. 立即撐開眼皮，以大量流動清水或生理食鹽水緩和沖洗至少 10～15 分鐘。\n2. 禁止揉眼；若戴隱形眼鏡且可方便取出，先取出後繼續沖洗。\n3. 立即就醫。"
    first_aid_skin: str = "1. 必要時戴防滲手套再行協助。\n2. 立即脫去受污染衣物、鞋襪，以大量清水沖洗受污染皮膚至少 5～15 分鐘。\n3. 若刺激感持續，立即就醫。"
    first_aid_symptoms: str = "接觸部位可能出現紅腫、刺激或灼傷；依物質特性可能影響呼吸道或中樞神經系統。"
    first_aid_rescuer_ppe: str = "應穿著適當個人防護裝備（如 C 級防護裝備、防滲手套、護目鏡）於安全區實施急救。"
    first_aid_physician_note: str = "依患者暴露途徑與症狀給予支持性療法，必要時聯繫毒物諮詢中心。"
    section_4_first_aid: str = "眼睛接觸：立即以大量清水沖洗至少 15 分鐘並就醫。皮膚接觸：立即脫去污染衣物並以大量清水沖洗。吸入：移至空氣新鮮處。食入：勿催吐，立即就醫。"

    # Section 5: Fire-Fighting Measures
    fire_extinguishing_media: str = "噴水霧、二氧化碳、乾粉滅火劑、酒精型泡沫。"
    fire_special_hazards: str = "高熱或燃燒時可能產生刺激性、腐蝕性或有毒分解氣體，密閉容器受熱可能破裂。"
    fire_procedures: str = "1. 撤退並於安全距離及上風處滅火。\n2. 安全情況下將未著火容器搬離火場，或噴水霧冷卻暴露火場之容器。"
    fire_ppe: str = "消防人員應佩戴正壓自給式呼吸器（SCBA）及全身式化學防護衣。"
    section_5_fire_fighting: str = "依周圍火勢選用乾粉、二氧化碳、抗醇泡沫或水霧滅火。火場應佩戴自給式呼吸器（SCBA）。"

    # Section 6: Accidental Release Measures
    release_personal: str = "1. 在污染區尚未清理乾淨前限制非相關人員進入。\n2. 清理人員須穿戴適當個人防護裝備。"
    release_env: str = "1. 對該區域進行通風換氣並移除發火源。\n2. 避免外洩物進入下水道、排水溝或密閉空間。"
    release_cleanup: str = "小量：避免產生粉塵或霧滴，以惰性吸收材吸附或鏟入乾燥潔淨標示容器後依法處理。\n大量：連絡消防緊急處理單位及校安／環安衛中心協助。"
    section_6_accidental_release: str = "穿戴適當個人防護具，確保通風，避免流入下水道；以惰性吸收材吸附後依廢棄物規定處理。"

    # Section 7: Handling & Storage
    handling_notes: str = "1. 應受適當安全訓練後操作，儘可能於排氣櫃或密閉系統中使用。\n2. 操作前檢查容器是否破損溢漏，禁止將受污染物質倒回原容器。\n3. 避免與不相容物質接觸，現場須備妥緊急沖淋與滅火器材。"
    storage_notes: str = "1. 貯存在乾燥、陰涼、通風良好且陽光無法直射之處，遠離熱源、引燃源與不相容物。\n2. 容器保持密閉並貼妥完整 GHS 危害標示，貯存區應定期巡檢。"
    section_7_handling_storage: str = "於通風櫥內操作，遠離火源、熱源與不相容物質。容器密閉並存放於適當屬性之藥品櫃。"

    # Section 8: Exposure Controls / PPE
    eng_controls: str = "1. 使用局部排氣裝置或化學排氣櫃，必要時採用不產生火花及接地之通風系統。\n2. 鄰近作業區設置緊急洗眼器與安全淋浴設備。"
    twa: str = "－"
    stel: str = "－"
    ceiling: str = "－"
    beis: str = "－"
    ppe_hands: str = "防滲手套（依化學品特性選用丁基橡膠、Viton 或耐化學 Nitrile 手套）。"
    ppe_skin_body: str = "實驗衣或連身式化學防護衣、包覆式實驗鞋。"
    ppe_respiratory: str = "通風不良或超過容許濃度時，佩戴適當濾罐式呼吸防護具或自攜式呼吸防護具。"
    ppe_eyes: str = "化學防濺安全護目鏡，必要時加戴護面罩。"
    hygiene_measures: str = "1. 工作場所嚴禁吸菸或飲食。\n2. 處理後徹底洗手，受污染衣物須洗淨除污後方可再用或丟棄。"
    section_8_exposure_controls: str = "建議佩戴化學防濺護目鏡、耐化學手套（Nitrile 或 Neoprene）、實驗衣，並於排氣櫃操作。"

    # Section 9: Physical & Chemical Properties
    phys_appearance: str = "－"
    phys_odor: str = "－"
    phys_odor_threshold: str = "－"
    phys_melting_point: str = "－"
    phys_ph: str = "－"
    phys_boiling_point: str = "－"
    phys_flammability: str = "－"
    phys_flash_point: str = "－"
    phys_flash_test_method: str = "－"
    phys_decomp_temp: str = "－"
    phys_autoignition_temp: str = "－"
    phys_explosion_limits: str = "－"
    phys_vapor_pressure: str = "－"
    phys_vapor_density: str = "－"
    phys_density: str = "－"
    phys_solubility: str = "－"
    phys_log_kow: str = "－"
    phys_evap_rate: str = "－"
    section_9_physical_chemical: str = "請參閱原廠 SDS 或物化性質資料庫。"

    # Section 10: Stability & Reactivity
    stability: str = "正常狀況下安定"
    hazardous_reactions: str = "接觸不相容物質（如強酸、強鹼或強氧化劑）可能發生劇烈放熱或釋出有害氣體。"
    conditions_to_avoid: str = "高熱、明火、火花、陽光直射。"
    materials_to_avoid: str = "強酸、強鹼、強氧化劑（詳見本系統相容性檢查引擎）。"
    decomp_products: str = "加熱分解可能釋出刺激性或毒性氣體（如 CO、CO2、NOx 或鹵化氫）。"
    section_10_stability_reactivity: str = "常溫常壓下安定；避免接觸不相容之強酸、強鹼或強氧化劑。"

    # Section 11: Toxicological Information
    tox_routes: str = "皮膚接觸、吸入、食入、眼睛接觸"
    tox_symptoms: str = "刺激感、紅腫、咳嗽或依特定危害分類之急慢性症狀。"
    tox_acute_skin: str = "－"
    tox_acute_inhalation: str = "－"
    tox_acute_ingestion: str = "－"
    tox_acute_eye: str = "－"
    tox_ld50: str = "－"
    tox_lc50: str = "－"
    tox_chronic: str = "－"
    section_11_toxicological: str = "詳見原廠毒理學資料；操作時避免吸入蒸氣或皮膚直接接觸。"

    # Section 12: Ecological Information
    eco_toxicity: str = "－"
    eco_persistence: str = "－"
    eco_bioaccumulation: str = "－"
    eco_mobility: str = "－"
    eco_other: str = "避免未經處理排入環境水體或土壤。"
    section_12_ecological: str = "避免未經處理排入環境水體或土壤。"

    # Section 13: Disposal Considerations
    disposal_methods: str = "1. 依《廢棄物清理法》及《事業廢棄物貯存清除處理方法及設施標準》辦理。\n2. 依貯存注意事項分類暫存，並委託合法廢棄物清除處理機構或學校環安衛中心清運。"
    section_13_disposal: str = "依台灣《廢棄物清理法》及學校環安衛中心規定分類集中委託合法清除機構處理。"

    # Section 14: Transport Information
    un_number: str = "－"
    un_shipping_name: str = "－"
    transport_hazard_class: str = "－"
    packing_group: str = "－"
    marine_pollutant: str = "否"
    transport_special: str = "－"
    erg_guide: str = "－"
    section_14_transport: str = "依聯合國危險物品運輸規定及供應商包裝標示辦理。"

    # Section 15: Regulatory Information
    regulations: str = (
        "1. 職業安全衛生法\n"
        "2. 危害性化學品標示及通識規則\n"
        "3. 勞工作業場所容許暴露標準\n"
        "4. 毒性及關注化學物質管理法\n"
        "5. 廢棄物清理法\n"
        "6. 危害性化學品評估及分級管理辦法"
    )
    section_15_regulatory: str = "適用台灣勞動部《危害性化學品標示及通識規則》及《職業安全衛生法》相關規定。"

    # Section 16: Other Information
    references: str = (
        "1. 勞動部職業安全衛生署 GHS 化學品全球調和制度網站\n"
        "2. 環境部化學物質管理署毒理與應變資料庫\n"
        "3. PubChem (NCBI) 化合物資料庫\n"
        "4. 國家標準 CNS 15030「化學品分類及標示」\n"
        "5. NOAA CAMEO Chemicals 反應性相容資料庫"
    )
    preparer_org: str = "實驗室安全管理系統 (LCSS)"
    preparer_address_phone: str = "－"
    preparer_title: str = "實驗室管理人"
    preparer_name: str = "系統自動彙整"
    prepare_date: str = ""
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
