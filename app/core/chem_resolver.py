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
H_CODE_PATTERN = re.compile(r"\b(?:EU)?H\d{3}[a-zA-Z]*\b")
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
        self._cameo_groups: dict[str, dict[str, str]] = self._load_json("cameo_groups.json", {})
        self._cameo_matrix: list[dict[str, Any]] = self._load_json(
            "cameo_matrix.json", {"rules": []}
        ).get("rules", [])
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

    def lookup_cas_by_name(
        self,
        query: str,
        client: Optional[httpx.Client] = None,
    ) -> list[dict[str, str]]:
        """Search CAS Number by Chinese or English chemical name (offline map + PubChem synonyms)."""
        q = query.strip().lower()
        if not q:
            return []

        matches: list[dict[str, str]] = []
        seen_cas: set[str] = set()
        for cas, entry in self._cas_map.items():
            name_zh = str(entry.get("name_zh", ""))
            name_en = str(entry.get("name_en", ""))
            syns = str((entry.get("sds_extra") or {}).get("synonyms", ""))
            if q in name_zh.lower() or q in name_en.lower() or q in syns.lower():
                matches.append({
                    "cas_number": cas,
                    "name_zh": name_zh,
                    "name_en": name_en,
                    "source": "離線資料庫",
                })
                seen_cas.add(cas)

        if matches:
            return matches

        own_client = client is None
        http = client or httpx.Client(timeout=self.timeout, follow_redirects=True)
        try:
            url = f"{self.PUBCHEM_REST}/compound/name/{query.strip()}/synonyms/JSON"
            resp = http.get(url)
            if resp.status_code == 200:
                infos = resp.json().get("InformationList", {}).get("Information", [])
                for info in infos[:3]:
                    syns_list = info.get("Synonym", [])
                    found_cas = next(
                        (s.strip() for s in syns_list if CAS_PATTERN.match(s.strip()) and validate_cas_checksum(s.strip())),
                        None,
                    )
                    if found_cas and found_cas not in seen_cas:
                        seen_cas.add(found_cas)
                        matches.append({
                            "cas_number": found_cas,
                            "name_zh": "",
                            "name_en": syns_list[0] if syns_list else query.strip(),
                            "source": "PubChem",
                        })
        except (httpx.HTTPError, ValueError):
            pass
        finally:
            if own_client:
                http.close()

        return matches

    def infer_hazard_classifications(self, h_codes: list[str]) -> list[str]:
        """Derive Taiwanese GHS hazard classifications from H-codes."""
        classes: list[str] = []
        for code in h_codes:
            label = H_CLASSIFICATION_MAP.get(code)
            if label and label not in classes:
                classes.append(label)
        return classes

    def _derive_section_10_from_groups(
        self, reactive_groups: list[str]
    ) -> tuple[str, str]:
        """Derive non-self-contradictory materials_to_avoid & hazardous_reactions from CAMEO matrix."""
        if not reactive_groups:
            return "", ""
        avoid_names: list[str] = []
        reactions: list[str] = []
        own_set = set(reactive_groups)
        for rule in self._cameo_matrix:
            a, b = rule.get("a"), rule.get("b")
            other = None
            if a in own_set and b not in own_set:
                other = b
            elif b in own_set and a not in own_set:
                other = a
            if other is None:
                continue
            grp_zh = self._cameo_groups.get(other, {}).get("name_zh", other)
            if grp_zh not in avoid_names:
                avoid_names.append(grp_zh)
            summary = rule.get("summary", "").strip()
            if summary and summary not in reactions:
                reactions.append(summary)

        avoid_str = "\n".join(f"{i}. {name}" for i, name in enumerate(avoid_names, 1))
        react_str = "\n".join(f"{i}. {r}" for i, r in enumerate(reactions[:5], 1))
        return avoid_str, react_str

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
        reactive_groups: Optional[list[str]] = None,
    ) -> SDSPayload:
        classifications = self.infer_hazard_classifications(h_codes)
        avoid_str, react_str = self._derive_section_10_from_groups(reactive_groups or [])
        payload_kwargs: dict[str, Any] = {
            "cas_number": cas,
            "name_zh": name_zh,
            "name_en": name_en,
            "formula": formula,
            "molecular_weight": mw,
            "smiles": smiles,
            "inchikey": inchikey,
            "ghs_pictograms": pictograms,
            "signal_word": signal_word,
            "h_codes": h_codes,
            "p_codes": p_codes,
            "h_statements_zh": self.translate_h_codes(h_codes),
            "p_statements_zh": self.translate_p_codes(p_codes),
            "hazard_classifications": classifications,
            "hazard_classification_zh": "；".join(classifications),
            "data_source": data_source,
        }
        if avoid_str:
            payload_kwargs["materials_to_avoid"] = avoid_str
            payload_kwargs["section_10_stability_reactivity"] = f"常溫常壓下安定；應避免接觸：{avoid_str.replace(chr(10), '、')}"
        if react_str:
            payload_kwargs["hazardous_reactions"] = react_str
        payload = SDSPayload(**payload_kwargs)
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
            reactive_groups=entry.get("groups", []),
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
            prop_extra = self._fetch_pubchem_properties_and_hazards(http, cid)
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
            merged_extra = {**prop_extra, **(offline_extra or {})}
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
                extra=merged_extra,
                reactive_groups=offline.reactive_groups if offline else [],
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

    def _extract_pug_view_sections(self, sections: list[dict[str, Any]], out: dict[str, list[str]]) -> None:
        """Recursively flatten PubChem PUG-View TOCHeading -> string values."""
        for sec in sections:
            heading = sec.get("TOCHeading", "")
            vals: list[str] = []
            for inf in sec.get("Information", []):
                val = inf.get("Value", {})
                for swm in val.get("StringWithMarkup", []):
                    s = swm.get("String", "").strip()
                    if s:
                        vals.append(s)
                nums = val.get("Number", [])
                unit = val.get("Unit", "")
                if nums:
                    vals.append(f"{nums[0]} {unit}".strip())
            if heading and vals:
                out.setdefault(heading, []).extend(vals)
            self._extract_pug_view_sections(sec.get("Section", []), out)

    def _fetch_pubchem_properties_and_hazards(self, http: httpx.Client, cid: int) -> dict[str, Any]:
        """Fetch experimental physical properties and safety hazards from PubChem PUG-View."""
        collected: dict[str, list[str]] = {}
        for heading in ("Chemical+and+Physical+Properties", "Safety+and+Hazards"):
            url = f"{self.PUBCHEM_VIEW}/data/compound/{cid}/JSON?heading={heading}"
            try:
                resp = http.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    self._extract_pug_view_sections(
                        data.get("Record", {}).get("Section", []), collected
                    )
            except (httpx.HTTPError, ValueError):
                continue

        extra: dict[str, Any] = {}
        heading_map = {
            "Physical Description": "phys_appearance",
            "Color/Form": "phys_appearance",
            "Odor": "phys_odor",
            "Melting Point": "phys_melting_point",
            "Boiling Point": "phys_boiling_point",
            "Flash Point": "phys_flash_point",
            "Density": "phys_density",
            "Solubility": "phys_solubility",
            "Vapor Pressure": "phys_vapor_pressure",
            "Vapor Density": "phys_vapor_density",
            "LogP": "phys_log_kow",
            "XLogP3": "phys_log_kow",
            "Autoignition Temperature": "phys_autoignition_temp",
        }
        for toc_key, sds_field in heading_map.items():
            if toc_key in collected and sds_field not in extra:
                extra[sds_field] = "；".join(collected[toc_key][:2])

        if "Hazards Summary" in collected:
            summary = " ".join(collected["Hazards Summary"][:2])
            extra["fire_special_hazards"] = summary
            extra["first_aid_symptoms"] = summary

        if "Fire Fighting" in collected:
            extra["fire_procedures"] = "\n".join(collected["Fire Fighting"][:3])

        chem_classes = " ".join(collected.get("Chemical Classes", []))
        if "Explosive" in chem_classes or "explosive when dry" in " ".join(
            collected.get("Hazards Summary", [])
        ).lower():
            extra["other_hazards"] = f"PubChem 危害類別：{chem_classes or '具爆炸性風險（乾燥或受熱時須特別注意）'}"

        return extra

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
