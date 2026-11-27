"""Deterministic chemical compatibility engine using NOAA CAMEO matrix + RDKit SMARTS."""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any, Optional

from rdkit import Chem

from app.config import DATA_DIR
from app.schemas import (
    CabinetCheckResult,
    CabinetType,
    CompatibilityIssue,
    CompatibilityLevel,
    GroupSource,
)

HAZARD_LABELS_ZH: dict[str, str] = {
    "HEAT": "劇烈放熱",
    "TOXIC_GAS": "產生有毒氣體",
    "FIRE": "起火風險",
    "EXPLOSION": "爆炸風險",
    "POLYMERIZATION": "劇烈聚合",
}

LEVEL_PRIORITY: dict[CompatibilityLevel, int] = {
    CompatibilityLevel.INCOMPATIBLE: 3,
    CompatibilityLevel.CAUTION: 2,
    CompatibilityLevel.UNKNOWN: 1,
    CompatibilityLevel.COMPATIBLE: 0,
}


class CompatibilityEngine:
    """Two-tier deterministic chemical compatibility engine."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self.data_dir = data_dir or DATA_DIR
        self.groups_def: dict[str, dict[str, str]] = self._load_json("cameo_groups.json", {})
        self.cas_map: dict[str, dict[str, Any]] = self._load_json("cameo_cas_map.json", {})
        raw_matrix = self._load_json("cameo_matrix.json", {"rules": []})
        self._matrix: dict[tuple[str, str], dict[str, Any]] = {}
        for rule in raw_matrix.get("rules", []):
            pair = tuple(sorted((rule["a"], rule["b"])))
            self._matrix[pair] = rule

        raw_smarts = self._load_json("smarts_reactive_groups.json", [])
        self._smarts_patterns: list[tuple[str, str, Chem.Mol]] = []
        for item in raw_smarts:
            mol = Chem.MolFromSmarts(item["smarts"])
            if mol is not None:
                self._smarts_patterns.append((item["group_id"], item["name"], mol))

    def _load_json(self, filename: str, default: Any) -> Any:
        path = self.data_dir / filename
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return default

    def classify_reactive_groups(
        self,
        cas_number: str = "",
        smiles: str = "",
        stored_groups: Optional[list[str]] = None,
    ) -> tuple[list[str], GroupSource, str]:
        """Determine CAMEO reactive groups via CAS map -> stored -> RDKit SMARTS."""
        cas = cas_number.strip()
        if cas and cas in self.cas_map:
            return list(self.cas_map[cas].get("groups", [])), GroupSource.CAMEO_DB, "依內建 CAMEO CAS 對照表判定"

        if stored_groups:
            return list(stored_groups), GroupSource.MANUAL, "依資料庫已儲存反應基團判定"

        if smiles.strip():
            mol = Chem.MolFromSmiles(smiles.strip())
            if mol is not None:
                matched: list[str] = []
                matched_names: list[str] = []
                for gid, gname, pat in self._smarts_patterns:
                    if mol.HasSubstructMatch(pat) and gid not in matched:
                        matched.append(gid)
                        matched_names.append(gname)
                if matched:
                    return (
                        matched,
                        GroupSource.RDKIT_INFERRED,
                        f"RDKit SMARTS 結構推斷：{', '.join(matched_names)}",
                    )
                return ["RG20"], GroupSource.RDKIT_INFERRED, "RDKit SMARTS 未檢出高反應性官能基，暫歸類為一般中性物質"

        return [], GroupSource.MANUAL, "缺少 CAS 對照與 SMILES 結構資訊，無法自動推斷反應基團"

    def check_pair(
        self,
        chem_a: dict[str, Any],
        chem_b: dict[str, Any],
    ) -> CompatibilityIssue:
        """Evaluate pairwise compatibility between two chemicals."""
        cas_a = chem_a.get("cas_number", "")
        cas_b = chem_b.get("cas_number", "")
        name_a = chem_a.get("name_zh") or chem_a.get("name_en") or cas_a
        name_b = chem_b.get("name_zh") or chem_b.get("name_en") or cas_b

        groups_a, src_a, note_a = self.classify_reactive_groups(
            cas_a, chem_a.get("smiles", ""), chem_a.get("reactive_groups")
        )
        groups_b, src_b, note_b = self.classify_reactive_groups(
            cas_b, chem_b.get("smiles", ""), chem_b.get("reactive_groups")
        )

        inference_parts = []
        if src_a == GroupSource.RDKIT_INFERRED:
            inference_parts.append(f"[{name_a}] {note_a}")
        if src_b == GroupSource.RDKIT_INFERRED:
            inference_parts.append(f"[{name_b}] {note_b}")
        inference_note = "；".join(inference_parts)

        if not groups_a or not groups_b:
            return CompatibilityIssue(
                chem_a_cas=cas_a,
                chem_b_cas=cas_b,
                chem_a_name=name_a,
                chem_b_name=name_b,
                level=CompatibilityLevel.UNKNOWN,
                summary_zh="其中一方缺少反應基團或 SMILES 資料，無法確認相容性。",
                recommendation_zh="請補齊 CAS 或 SMILES 結構資訊，或人工查閱原廠 SDS 第 10 節。",
                inference_note=inference_note,
            )

        worst_level = CompatibilityLevel.COMPATIBLE
        hazards: list[str] = []
        matched_groups: list[tuple[str, str]] = []
        summaries: list[str] = []

        for ga in groups_a:
            for gb in groups_b:
                pair = tuple(sorted((ga, gb)))
                rule = self._matrix.get(pair)
                if not rule:
                    continue
                lvl = CompatibilityLevel(rule["level"])
                if LEVEL_PRIORITY[lvl] > LEVEL_PRIORITY[worst_level]:
                    worst_level = lvl
                for h in rule.get("hazards", []):
                    if h not in hazards:
                        hazards.append(h)
                matched_groups.append((ga, gb))
                if rule.get("summary") and rule["summary"] not in summaries:
                    summaries.append(rule["summary"])

        if worst_level == CompatibilityLevel.COMPATIBLE:
            sds_issue = self._check_sds_section_10_cross_reference(
                cas_a, cas_b, name_a, name_b, groups_a, groups_b, chem_a, chem_b, inference_note
            )
            if sds_issue is not None:
                return sds_issue
            return CompatibilityIssue(
                chem_a_cas=cas_a,
                chem_b_cas=cas_b,
                chem_a_name=name_a,
                chem_b_name=name_b,
                level=CompatibilityLevel.COMPATIBLE,
                summary_zh="依目前反應基團矩陣及 SDS 第 10 節未發現劇烈不相容反應。",
                recommendation_zh="可依一般分類存放，仍須保持容器密閉與適當通風。",
                inference_note=inference_note,
            )

        hazard_zh = "、".join(HAZARD_LABELS_ZH.get(h, h) for h in hazards)
        rec = (
            f"禁止混放或混合！主要風險：{hazard_zh}。請務必分櫃隔離存放並備妥對應中和／吸收器材。"
            if worst_level == CompatibilityLevel.INCOMPATIBLE
            else f"具潛在反應風險（{hazard_zh}），建議分層或分區隔離存放。"
        )
        return CompatibilityIssue(
            chem_a_cas=cas_a,
            chem_b_cas=cas_b,
            chem_a_name=name_a,
            chem_b_name=name_b,
            level=worst_level,
            hazards=hazards,
            matched_groups=matched_groups,
            summary_zh=" ".join(summaries),
            recommendation_zh=rec,
            inference_note=inference_note,
        )

    def _check_sds_section_10_cross_reference(
        self,
        cas_a: str,
        cas_b: str,
        name_a: str,
        name_b: str,
        groups_a: list[str],
        groups_b: list[str],
        chem_a: dict[str, Any],
        chem_b: dict[str, Any],
        inference_note: str,
    ) -> Optional[CompatibilityIssue]:
        """Tier-3 deterministic cross-check using SDS Section 10 (materials_to_avoid)."""
        sds_a = chem_a.get("sds_json") or {}
        sds_b = chem_b.get("sds_json") or {}
        avoid_a = str(sds_a.get("materials_to_avoid") or "").lower()
        avoid_b = str(sds_b.get("materials_to_avoid") or "").lower()

        if not avoid_a and not avoid_b:
            return None

        # Keyword categories mapped to reactive groups / GHS pictograms / H-codes
        category_rules = [
            ("強酸/酸類", ("酸", "acid"), ("RG01", "RG02", "RG03"), ("GHS05",), ()),
            ("強鹼/鹼類", ("鹼", "alkali", "base", "hydroxide"), ("RG08",), (), ()),
            ("強氧化劑", ("氧化劑", "oxidiz", "peroxide", "過氧化物"), ("RG02", "RG09", "RG16", "RG17"), ("GHS03",), ()),
            ("還原劑", ("還原劑", "reduc"), ("RG19",), (), ()),
            ("水/潮氣", ("水", "water", "moisture"), ("RG20",), (), ("H260", "EUH014")),
        ]

        hits: list[str] = []
        for label, keywords, target_groups, target_ghs, target_h in category_rules:
            # Does A's SDS warn against B?
            if avoid_a and any(kw in avoid_a for kw in keywords):
                b_ghs = chem_b.get("ghs_pictograms") or []
                b_h = chem_b.get("h_codes") or []
                if any(g in groups_b for g in target_groups) or any(g in b_ghs for g in target_ghs) or any(h in b_h for h in target_h):
                    hits.append(f"[{name_a}] SDS 第 10 節註明應避免接觸「{label}」")
            # Does B's SDS warn against A?
            if avoid_b and any(kw in avoid_b for kw in keywords):
                a_ghs = chem_a.get("ghs_pictograms") or []
                a_h = chem_a.get("h_codes") or []
                if any(g in groups_a for g in target_groups) or any(g in a_ghs for g in target_ghs) or any(h in a_h for h in target_h):
                    hits.append(f"[{name_b}] SDS 第 10 節註明應避免接觸「{label}」")

        # Direct name / CAS mention in materials_to_avoid
        for src_name, avoid_txt, tgt_cas, tgt_zh, tgt_en in (
            (name_a, avoid_a, cas_b, chem_b.get("name_zh", ""), chem_b.get("name_en", "")),
            (name_b, avoid_b, cas_a, chem_a.get("name_zh", ""), chem_a.get("name_en", "")),
        ):
            if not avoid_txt:
                continue
            for token in (tgt_cas, tgt_zh, tgt_en):
                tok = str(token or "").strip().lower()
                if len(tok) >= 2 and tok in avoid_txt:
                    hits.append(f"[{src_name}] SDS 第 10 節直接點名應避免接觸「{token}」")
                    break

        if not hits:
            return None

        sds_note = "；".join(dict.fromkeys(hits))
        combined_note = f"{inference_note}；{sds_note}" if inference_note else sds_note
        return CompatibilityIssue(
            chem_a_cas=cas_a,
            chem_b_cas=cas_b,
            chem_a_name=name_a,
            chem_b_name=name_b,
            level=CompatibilityLevel.CAUTION,
            hazards=["SDS_INCOMPATIBLE"],
            summary_zh=f"CAMEO 矩陣未列為禁混，但依 SDS 第 10 節交叉比對發現潛在禁忌：{sds_note}。",
            recommendation_zh="建議分櫃或隔離存放，並詳閱雙方原廠 SDS 第 10 節「應避免之物質」確認風險。",
            inference_note=combined_note,
        )

    def check_matrix(self, chemicals: list[dict[str, Any]]) -> list[CompatibilityIssue]:
        """Run pairwise compatibility checks across N chemicals."""
        return [self.check_pair(a, b) for a, b in combinations(chemicals, 2)]

    def check_cabinet_suitability(
        self,
        ghs_pictograms: list[str],
        reactive_groups: list[str],
        cabinet_type: CabinetType | str,
    ) -> CabinetCheckResult:
        """Check whether a chemical is suitable for a target cabinet type."""
        ctype = cabinet_type.value if isinstance(cabinet_type, CabinetType) else cabinet_type
        is_flammable = "GHS02" in ghs_pictograms or any(
            g in reactive_groups for g in ("RG04", "RG11", "RG12", "RG14", "RG15")
        )
        is_corrosive = "GHS05" in ghs_pictograms or any(
            g in reactive_groups for g in ("RG01", "RG02", "RG03", "RG08")
        )
        is_oxidizer = "GHS03" in ghs_pictograms or any(
            g in reactive_groups for g in ("RG02", "RG09", "RG16", "RG17")
        )

        if is_flammable and ctype in (CabinetType.FRIDGE_4C.value, CabinetType.FREEZER_M20.value):
            return CabinetCheckResult(
                compatible=False,
                level=CompatibilityLevel.INCOMPATIBLE,
                message_zh="警告：易燃溶劑或低閃火點化學品嚴禁放入一般非防爆冰箱／冷凍庫！",
            )
        if is_flammable and ctype == CabinetType.CORROSIVE.value:
            return CabinetCheckResult(
                compatible=False,
                level=CompatibilityLevel.CAUTION,
                message_zh="提醒：易燃有機溶劑不建議存放於耐酸鹼腐蝕櫃，應優先移至防火易燃櫃。",
            )
        if is_oxidizer and ctype == CabinetType.FLAMMABLE.value:
            return CabinetCheckResult(
                compatible=False,
                level=CompatibilityLevel.INCOMPATIBLE,
                message_zh="警告：強氧化劑（GHS03）嚴禁與易燃物同置於防火易燃櫃！",
            )
        if is_corrosive and ctype == CabinetType.FLAMMABLE.value and not is_flammable:
            return CabinetCheckResult(
                compatible=False,
                level=CompatibilityLevel.CAUTION,
                message_zh="提醒：純腐蝕性酸鹼建議存放於耐酸鹼櫃，避免腐蝕易燃櫃金屬內壁。",
            )
        return CabinetCheckResult(
            compatible=True,
            level=CompatibilityLevel.COMPATIBLE,
            message_zh="藥品屬性與目標藥品櫃類型相符。",
        )
