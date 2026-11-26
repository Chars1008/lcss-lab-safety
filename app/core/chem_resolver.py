"""Chemical resolver: CAS validation, local cache, PubChem PUG-REST/PUG-View, and TW GHS."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from app.config import DATA_DIR
from app.schemas import ControlLevel, GroupSource, ResolvedChemical, SDSPayload

CAS_PATTERN = re.compile(r"^\d{2,7}-\d{2}-\d$")
H_CODE_PATTERN = re.compile(r"\bH\d{3}[a-zA-Z]*\b")
P_CODE_PATTERN = re.compile(r"\bP\d{3}(?:\+P\d{3})*\b")


def validate_cas_checksum(cas_number: str) -> bool:
    """Validate CAS Registry Number format and check digit."""
    cas = cas_number.strip()
    if not CAS_PATTERN.match(cas):
        return False
    digits = cas.replace("-", "")
    check_digit = int(digits[-1])
    body = digits[:-1]
    total = sum(int(d) * (idx + 1) for idx, d in enumerate(reversed(body)))
    return (total % 10) == check_digit


H_CLASSIFICATION_MAP: dict[str, str] = {
    "H224": "易燃液體第 1 級",
    "H225": "易燃液體第 2 級",
    "H226": "易燃液體第 3 級",
    "H228": "易燃固體第 1/2 級",
    "H260": "禁水性物質第 1 級",
    "H271": "氧化性液體／固體第 1 級",
    "H272": "氧化性液體／固體第 2/3 級",
    "H290": "金屬腐蝕物第 1 級",
    "H300": "急毒性物質第 1/2 級（吞食）",
    "H301": "急毒性物質第 3 級（吞食）",
    "H302": "急毒性物質第 4 級（吞食）",
    "H304": "吸入性危害物質第 1 級",
    "H310": "急毒性物質第 1/2 級（皮膚）",
    "H311": "急毒性物質第 3 級（皮膚）",
    "H312": "急毒性物質第 4 級（皮膚）",
    "H314": "腐蝕／刺激皮膚物質第 1 級",
    "H315": "腐蝕／刺激皮膚物質第 2 級",
    "H317": "皮膚過敏物質第 1 級",
    "H318": "嚴重損傷／刺激眼睛物質第 1 級",
    "H319": "嚴重損傷／刺激眼睛物質第 2A 級",
    "H330": "急毒性物質第 1/2 級（吸入）",
    "H331": "急毒性物質第 3 級（吸入）",
    "H332": "急毒性物質第 4 級（吸入）",
    "H334": "呼吸道過敏物質第 1 級",
    "H335": "特定標的器官系統毒性物質－單一暴露第 3 級（呼吸道刺激）",
    "H336": "特定標的器官系統毒性物質－單一暴露第 3 級（麻醉效應）",
    "H340": "生殖細胞致突變性物質第 1 級",
    "H341": "生殖細胞致突變性物質第 2 級",
    "H350": "致癌物質第 1 級",
    "H351": "致癌物質第 2 級",
    "H361d": "生殖毒性物質第 2 級（發育）",
    "H361f": "生殖毒性物質第 2 級（生育力）",
    "H370": "特定標的器官系統毒性物質－單一暴露第 1 級",
    "H372": "特定標的器官系統毒性物質－重複暴露第 1 級",
    "H373": "特定標的器官系統毒性物質－重複暴露第 2 級",
    "H400": "水環境之危害物質（急毒性）第 1 級",
    "H410": "水環境之危害物質（慢毒性）第 1 級",
    "H411": "水環境之危害物質（慢毒性）第 2 級",
}


class ChemResolver:
    """Deterministic chemical metadata & GHS resolver with offline fallback."""

    PUBCHEM_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
    PUBCHEM_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
    TW_GHS_SEARCH = "https://ghs.osha.gov.tw/CHT/intro/search.aspx"

    def __init__(self, data_dir: Optional[Path] = None, timeout: float = 15.0) -> None:
        self.data_dir = data_dir or DATA_DIR
        self.timeout = timeout
        self._cas_map: dict[str, dict[str, Any]] = self._load_json("cameo_cas_map.json", {})
        self._hp_zh: dict[str, dict[str, str]] = self._load_json(
            "ghs_hp_zh_tw.json", {"h_codes": {}, "p_codes": {}}
        )

    def _load_json(self, filename: str, default: Any) -> Any:
        path = self.data_dir / filename
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return default

    def translate_h_codes(self, h_codes: list[str]) -> list[str]:
        table = self._hp_zh.get("h_codes", {})
        return [f"{code}：{table[code]}" if code in table else code for code in h_codes]

    def translate_p_codes(self, p_codes: list[str]) -> list[str]:
        table = self._hp_zh.get("p_codes", {})
        return [f"{code}：{table[code]}" if code in table else code for code in p_codes]

    def infer_hazard_classifications(self, h_codes: list[str]) -> list[str]:
        """Derive Taiwanese GHS hazard classifications from H-codes."""
        classes: list[str] = []
        for code in h_codes:
            label = H_CLASSIFICATION_MAP.get(code)
            if label and label not in classes:
                classes.append(label)
        return classes

    def _build_sds_payload(
        self,
        cas: str,
        name_zh: str,
        name_en: str,
        formula: str,
        mw: Optional[float],
        smiles: str,
        inchikey: str,
        pictograms: list[str],
        signal_word: Optional[str],
        h_codes: list[str],
        p_codes: list[str],
        data_source: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> SDSPayload:
        classifications = self.infer_hazard_classifications(h_codes)
        payload = SDSPayload(
            cas_number=cas,
            name_zh=name_zh,
            name_en=name_en,
            formula=formula,
            molecular_weight=mw,
            smiles=smiles,
            inchikey=inchikey,
            ghs_pictograms=pictograms,
            signal_word=signal_word,
            h_codes=h_codes,
            p_codes=p_codes,
            h_statements_zh=self.translate_h_codes(h_codes),
            p_statements_zh=self.translate_p_codes(p_codes),
            hazard_classifications=classifications,
            hazard_classification_zh="；".join(classifications),
            data_source=data_source,
        )
        if extra:
            valid_updates = {k: v for k, v in extra.items() if hasattr(payload, k)}
            payload = payload.model_copy(update=valid_updates)
        return payload

    def resolve_offline(self, cas_number: str) -> Optional[ResolvedChemical]:
        """Look up chemical in built-in offline CAMEO/GHS dataset."""
        cas = cas_number.strip()
        entry = self._cas_map.get(cas)
        if not entry:
            return None

        h_codes = entry.get("h", [])
        p_codes = entry.get("p", [])
        ctrl_str = entry.get("control", "NORMAL")
        try:
            ctrl = ControlLevel(ctrl_str)
        except ValueError:
            ctrl = ControlLevel.NORMAL

        sds = self._build_sds_payload(
            cas=cas,
            name_zh=entry.get("name_zh", ""),
            name_en=entry.get("name_en", ""),
            formula=entry.get("formula", ""),
            mw=entry.get("mw"),
            smiles=entry.get("smiles", ""),
            inchikey="",
            pictograms=entry.get("ghs", []),
            signal_word=entry.get("signal"),
            h_codes=h_codes,
            p_codes=p_codes,
            data_source="OFFLINE_CAMEO_TW_GHS",
            extra=entry.get("sds_extra"),
        )
        return ResolvedChemical(
            cas_number=cas,
            name_zh=entry.get("name_zh", ""),
            name_en=entry.get("name_en", ""),
            formula=entry.get("formula", ""),
            molecular_weight=entry.get("mw"),
            smiles=entry.get("smiles", ""),
            ghs_pictograms=entry.get("ghs", []),
            signal_word=entry.get("signal"),
            h_codes=h_codes,
            p_codes=p_codes,
            reactive_groups=entry.get("groups", []),
            group_source=GroupSource.CAMEO_DB,
            control_level=ctrl,
            sds_payload=sds,
            data_source="OFFLINE_CAMEO_TW_GHS",
        )

    def resolve_online(
        self,
        query: str,
        client: Optional[httpx.Client] = None,
    ) -> Optional[ResolvedChemical]:
        """Resolve chemical by CAS or name via PubChem PUG-REST + PUG-View + TW GHS."""
        q = query.strip()
        if not q:
            return None

        # Check offline seed first if query is a valid CAS
        offline = self.resolve_offline(q) if validate_cas_checksum(q) else None

        own_client = client is None
        http = client or httpx.Client(timeout=self.timeout, follow_redirects=True)
        try:
            cid, props = self._fetch_pubchem_properties(http, q)
            if cid is None and offline is not None:
                return offline
            if cid is None:
                return None

            ghs_info = self._fetch_pubchem_ghs(http, cid)
            cas = q if validate_cas_checksum(q) else ghs_info.get("cas") or q
            tw_info = self._fetch_tw_ghs(http, cas) if validate_cas_checksum(cas) else {}

            name_en = props.get("Title") or props.get("IUPACName") or (offline.name_en if offline else q)
            name_zh = tw_info.get("name_zh") or (offline.name_zh if offline else "")
            h_codes = sorted(set(ghs_info.get("h_codes", []) + (offline.h_codes if offline else [])))
            p_codes = sorted(set(ghs_info.get("p_codes", []) + (offline.p_codes if offline else [])))
            pictograms = sorted(
                set(ghs_info.get("pictograms", []) + (offline.ghs_pictograms if offline else []))
            )
            signal_word = tw_info.get("signal_word") or ghs_info.get("signal_word") or (
                offline.signal_word if offline else None
            )

            smiles = (
                props.get("CanonicalSMILES")
                or props.get("ConnectivitySMILES")
                or props.get("IsomericSMILES")
                or (offline.smiles if offline else "")
            )
            mw_raw = props.get("MolecularWeight")
            try:
                mw = float(mw_raw) if mw_raw is not None else (offline.molecular_weight if offline else None)
            except (TypeError, ValueError):
                mw = offline.molecular_weight if offline else None

            offline_extra = self._cas_map.get(cas, {}).get("sds_extra") if validate_cas_checksum(cas) else None
            sds = self._build_sds_payload(
                cas=cas,
                name_zh=name_zh,
                name_en=name_en,
                formula=props.get("MolecularFormula", offline.formula if offline else ""),
                mw=mw,
                smiles=smiles,
                inchikey=props.get("InChIKey", ""),
                pictograms=pictograms,
                signal_word=signal_word,
                h_codes=h_codes,
                p_codes=p_codes,
                data_source="PUBCHEM_TW_GHS",
                extra=offline_extra,
            )
            return ResolvedChemical(
                cas_number=cas,
                name_zh=name_zh,
                name_en=name_en,
                formula=sds.formula,
                molecular_weight=mw,
                smiles=smiles,
                inchikey=sds.inchikey,
                ghs_pictograms=pictograms,
                signal_word=signal_word,
                h_codes=h_codes,
                p_codes=p_codes,
                reactive_groups=offline.reactive_groups if offline else [],
                group_source=offline.group_source if offline else GroupSource.MANUAL,
                control_level=offline.control_level if offline else ControlLevel.NORMAL,
                sds_payload=sds,
                data_source="PUBCHEM_TW_GHS",
            )
        finally:
            if own_client:
                http.close()

    def _fetch_pubchem_properties(
        self, http: httpx.Client, identifier: str
    ) -> tuple[Optional[int], dict[str, Any]]:
        url = (
            f"{self.PUBCHEM_REST}/compound/name/{identifier}/property/"
            "MolecularFormula,MolecularWeight,CanonicalSMILES,InChIKey,IUPACName,Title/JSON"
        )
        try:
            resp = http.get(url)
            if resp.status_code != 200:
                return None, {}
            data = resp.json()
            props_list = data.get("PropertyTable", {}).get("Properties", [])
            if not props_list:
                return None, {}
            first = props_list[0]
            return first.get("CID"), first
        except (httpx.HTTPError, ValueError):
            return None, {}

    def _fetch_pubchem_ghs(self, http: httpx.Client, cid: int) -> dict[str, Any]:
        url = f"{self.PUBCHEM_VIEW}/data/compound/{cid}/JSON?heading=GHS+Classification"
        result: dict[str, Any] = {"pictograms": [], "h_codes": [], "p_codes": [], "signal_word": None}
        try:
            resp = http.get(url)
            if resp.status_code != 200:
                return result
            text = resp.text
            # Extract GHS01-GHS09
            picts = sorted(set(re.findall(r"GHS0[1-9]", text)))
            h_codes = sorted(set(H_CODE_PATTERN.findall(text)))
            p_codes = sorted(set(P_CODE_PATTERN.findall(text)))
            signal: Optional[str] = None
            if '"Danger"' in text or "Danger" in text:
                signal = "危險"
            elif '"Warning"' in text or "Warning" in text:
                signal = "警告"
            result.update(
                pictograms=picts,
                h_codes=h_codes,
                p_codes=p_codes,
                signal_word=signal,
            )
            return result
        except (httpx.HTTPError, ValueError):
            return result

    def _fetch_tw_ghs(self, http: httpx.Client, cas_number: str) -> dict[str, Any]:
        """Best-effort parser for Taiwan OSHA GHS website; never raises on layout changes."""
        try:
            resp = http.get(self.TW_GHS_SEARCH, params={"cas": cas_number})
            if resp.status_code != 200:
                return {}
            soup = BeautifulSoup(resp.text, "lxml")
            title_el = soup.select_one(".chem-name-zh, #lblChemNameZh, td.name-zh")
            name_zh = title_el.get_text(strip=True) if title_el else ""
            signal_el = soup.select_one(".signal-word, #lblSignalWord")
            signal_word = signal_el.get_text(strip=True) if signal_el else None
            return {"name_zh": name_zh, "signal_word": signal_word}
        except Exception:
            return {}
