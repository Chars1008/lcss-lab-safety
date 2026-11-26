"""Optional Local LLM (Ollama) helper service with strict graceful degradation."""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from app.schemas import CompatibilityIssue, SDSPayload


class LocalLLMService:
    """Wrapper around Ollama REST API; never alters deterministic safety levels."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        enabled: bool = False,
        timeout: float = 45.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.enabled = enabled
        self.timeout = timeout

    def check_connection(self, client: Optional[httpx.Client] = None) -> tuple[bool, list[str]]:
        """Check if Ollama server is reachable and return installed model names."""
        own_client = client is None
        http = client or httpx.Client(timeout=5.0)
        try:
            resp = http.get(f"{self.host}/api/tags")
            if resp.status_code != 200:
                return False, []
            data = resp.json()
            models = [m["name"] for m in data.get("models", []) if "name" in m]
            return True, models
        except (httpx.HTTPError, ValueError):
            return False, []
        finally:
            if own_client:
                http.close()

    def _generate_json(
        self,
        prompt: str,
        client: Optional[httpx.Client] = None,
    ) -> Optional[dict[str, Any]]:
        if not self.enabled:
            return None
        own_client = client is None
        http = client or httpx.Client(timeout=self.timeout)
        try:
            resp = http.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                },
            )
            if resp.status_code != 200:
                return None
            raw_response = resp.json().get("response", "")
            return json.loads(raw_response)
        except (httpx.HTTPError, ValueError, TypeError):
            return None
        finally:
            if own_client:
                http.close()

    def translate_sds_language(
        self,
        sds: SDSPayload,
        target_language: str = "en",
        client: Optional[httpx.Client] = None,
    ) -> SDSPayload:
        """Translate SDS fields bidirectionally between Traditional Chinese (zh-TW) and English (en)."""
        if not self.enabled:
            return sds
        lang_label = "English (professional GHS SDS style)" if target_language == "en" else "台灣繁體中文（符合台灣 GHS 專業用語）"
        prompt = (
            f"You are a chemical safety expert. Translate the following SDS fields into {lang_label}. "
            "Return a JSON object with keys: recommended_use, first_aid_ingestion, first_aid_inhalation, "
            "first_aid_eye, first_aid_skin, first_aid_symptoms, fire_extinguishing_media, "
            "fire_special_hazards, release_cleanup, handling_notes, storage_notes, "
            "phys_appearance, materials_to_avoid, tox_chronic.\n"
            f"Chemical: {sds.name_en} / {sds.name_zh} (CAS: {sds.cas_number})\n"
            f"recommended_use: {sds.recommended_use}\n"
            f"first_aid_ingestion: {sds.first_aid_ingestion}\n"
            f"first_aid_inhalation: {sds.first_aid_inhalation}\n"
            f"first_aid_eye: {sds.first_aid_eye}\n"
            f"first_aid_skin: {sds.first_aid_skin}\n"
            f"first_aid_symptoms: {sds.first_aid_symptoms}\n"
            f"fire_extinguishing_media: {sds.fire_extinguishing_media}\n"
            f"fire_special_hazards: {sds.fire_special_hazards}\n"
            f"release_cleanup: {sds.release_cleanup}\n"
            f"handling_notes: {sds.handling_notes}\n"
            f"storage_notes: {sds.storage_notes}\n"
            f"phys_appearance: {sds.phys_appearance}\n"
            f"materials_to_avoid: {sds.materials_to_avoid}\n"
            f"tox_chronic: {sds.tox_chronic}"
        )
        parsed = self._generate_json(prompt, client=client)
        if not parsed:
            return sds
        updates = {
            k: v.strip()
            for k, v in parsed.items()
            if hasattr(sds, k) and isinstance(v, str) and v.strip()
        }
        return sds.model_copy(update=updates)

    def translate_sds_fields(
        self,
        sds: SDSPayload,
        client: Optional[httpx.Client] = None,
    ) -> SDSPayload:
        """Translate or polish SDS safety fields into Traditional Chinese (Taiwan)."""
        if not self.enabled:
            return sds
        prompt = (
            "你是一位台灣實驗室環安衛專家。請將以下化學品安全資料翻譯或潤飾為自然專業的台灣繁體中文，"
            "回傳 JSON 物件，包含 keys: name_zh, section_4_first_aid, section_5_fire_fighting, "
            "section_6_accidental_release, section_7_handling_storage。\n"
            f"化學品英文名: {sds.name_en} (CAS: {sds.cas_number})\n"
            f"目前中文名: {sds.name_zh}\n"
            f"第4節: {sds.section_4_first_aid}\n"
            f"第5節: {sds.section_5_fire_fighting}\n"
            f"第6節: {sds.section_6_accidental_release}\n"
            f"第7節: {sds.section_7_handling_storage}"
        )
        parsed = self._generate_json(prompt, client=client)
        if not parsed:
            return sds
        updates: dict[str, Any] = {}
        for key in (
            "name_zh",
            "section_4_first_aid",
            "section_5_fire_fighting",
            "section_6_accidental_release",
            "section_7_handling_storage",
        ):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                updates[key] = val.strip()
        return sds.model_copy(update=updates)

    def extract_sds_from_pdf_text(
        self,
        pdf_text: str,
        client: Optional[httpx.Client] = None,
    ) -> dict[str, Any]:
        """Extract structured chemical & SDS fields from supplier PDF text."""
        if not self.enabled or not pdf_text.strip():
            return {}
        snippet = pdf_text[:6000]
        prompt = (
            "請從以下原廠 SDS 文本中萃取結構化資訊，回傳 JSON 物件，包含 keys: "
            "cas_number, name_zh, name_en, signal_word, h_codes (陣列), p_codes (陣列), "
            "first_aid_ingestion, first_aid_inhalation, first_aid_eye, first_aid_skin, "
            "fire_extinguishing_media, fire_special_hazards, handling_notes, storage_notes, "
            "twa, stel, phys_appearance, phys_melting_point, phys_boiling_point, phys_ph, "
            "materials_to_avoid, tox_ld50, un_number, transport_hazard_class。\n\n"
            f"{snippet}"
        )
        return self._generate_json(prompt, client=client) or {}

    def summarize_compatibility_advice(
        self,
        issue: CompatibilityIssue,
        client: Optional[httpx.Client] = None,
    ) -> str:
        """Generate plain-language Taiwanese Mandarin storage/spill advice without altering level."""
        if not self.enabled:
            return issue.recommendation_zh
        prompt = (
            "請以簡潔明確的台灣繁體中文，針對以下確定的化學品相容性判定結果提供 2 句以內的分櫃與應變建議"
            "（不可更改危害等級）：\n"
            f"化學品 A: {issue.chem_a_name} ({issue.chem_a_cas})\n"
            f"化學品 B: {issue.chem_b_name} ({issue.chem_b_cas})\n"
            f"確定等級: {issue.level.value}\n"
            f"危害機制: {issue.summary_zh}\n"
            "請回傳 JSON: {\"advice_zh\": \"...\"}"
        )
        parsed = self._generate_json(prompt, client=client)
        if parsed and isinstance(parsed.get("advice_zh"), str) and parsed["advice_zh"].strip():
            return parsed["advice_zh"].strip()
        return issue.recommendation_zh
