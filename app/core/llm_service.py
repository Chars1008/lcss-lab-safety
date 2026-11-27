"""Optional Local LLM (Ollama) helper service with strict graceful degradation."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx

from app.schemas import CompatibilityIssue, SDSPayload

CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")


def _contains_cjk(text: str) -> bool:
    return bool(CJK_PATTERN.search(text))


def _strip_cjk(text: str) -> str:
    """Remove CJK characters and tidy punctuation left behind."""
    cleaned = CJK_PATTERN.sub("", text)
    cleaned = re.sub(r"[（）()、；：]+", lambda m: " " if len(m.group(0)) > 1 else "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;:-")
    return cleaned or "－"


class LocalLLMService:
    """Wrapper around Ollama REST API; never alters deterministic safety levels."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "gemma4:e2b",
        enabled: bool = False,
        timeout: float = 180.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.enabled = enabled
        self.timeout = timeout
        self.last_error: str = ""

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

    def _extract_json_dict(self, raw: str) -> Optional[dict[str, Any]]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else None
        except ValueError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                try:
                    obj = json.loads(match.group(0))
                    return obj if isinstance(obj, dict) else None
                except ValueError:
                    return None
            return None

    def _generate_json(
        self,
        prompt: str,
        client: Optional[httpx.Client] = None,
    ) -> Optional[dict[str, Any]]:
        self.last_error = ""
        if not self.enabled:
            self.last_error = "Ollama 未啟用"
            return None
        own_client = client is None
        http = client or httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=self.timeout, write=30.0, pool=10.0)
        )
        try:
            resp = http.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                    "think": False,
                    "keep_alive": "10m",
                },
            )
            if resp.status_code != 200:
                self.last_error = f"Ollama HTTP {resp.status_code}: {resp.text[:200]}"
                return None
            raw_response = resp.json().get("response", "")
            parsed = self._extract_json_dict(raw_response)
            if parsed is None:
                self.last_error = "Ollama 回傳內容非有效 JSON 格式"
            return parsed
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            self.last_error = f"Ollama 連線失敗：{exc}"
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
        """Translate all SDS text fields bidirectionally between zh-TW and en.

        Rules:
        - target_language == "zh-TW" (EN -> ZH): translate to Traditional Chinese while
          retaining English (keeps `name_en` intact, appends English reference if source was English).
        - target_language == "en" (ZH -> EN): translate to English and remove Chinese
          (clears `name_zh` and strips residual CJK characters).
        """
        if not self.enabled:
            return sds

        translatable_fields = [
            "recommended_use",
            "synonyms",
            "other_hazards",
            "first_aid_ingestion",
            "first_aid_inhalation",
            "first_aid_eye",
            "first_aid_skin",
            "first_aid_symptoms",
            "first_aid_physician_note",
            "fire_extinguishing_media",
            "fire_special_hazards",
            "fire_procedures",
            "release_cleanup",
            "handling_notes",
            "storage_notes",
            "ppe_hands",
            "ppe_respiratory",
            "phys_appearance",
            "phys_odor",
            "phys_melting_point",
            "phys_boiling_point",
            "phys_solubility",
            "materials_to_avoid",
            "tox_ld50",
            "tox_chronic",
            "eco_toxicity",
            "disposal_methods",
            "transport_hazard_class",
        ]

        # Only translate fields that actually need translation, one field at a time (plain text)
        # to eliminate JSON truncation/escaping failures on long PubChem paragraphs.
        fields_to_translate: list[str] = []
        for k in translatable_fields:
            val = str(getattr(sds, k) or "").strip()
            if not val or val in ("－", "/"):
                continue
            if target_language == "zh-TW":
                if not _contains_cjk(val) and re.search(r"[A-Za-z]{2,}", val):
                    fields_to_translate.append(k)
            else:
                if _contains_cjk(val):
                    fields_to_translate.append(k)

        if target_language == "zh-TW" and not sds.name_zh and sds.name_en:
            fields_to_translate.insert(0, "name_zh")

        updates: dict[str, Any] = {}
        own_client = client is None
        http = client or httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=max(self.timeout, 180.0), write=30.0, pool=10.0)
        )
        try:
            self.last_error = ""
            for k in fields_to_translate:
                orig_val = (
                    sds.name_en
                    if (k == "name_zh" and not sds.name_zh)
                    else str(getattr(sds, k) or "").strip()
                )
                if target_language == "zh-TW":
                    prompt = (
                        "Translate the following chemical safety text into natural Traditional Chinese (繁體中文). "
                        "Output ONLY the translated Traditional Chinese text, with no extra explanation or markdown.\n\n"
                        f"{orig_val}"
                    )
                else:
                    prompt = (
                        "Translate the following chemical safety text into clear professional English. "
                        "Output ONLY the translated English text with no Chinese characters and no extra explanation.\n\n"
                        f"{orig_val}"
                    )

                try:
                    payload_json: dict[str, Any] = {
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "think": False,
                        "keep_alive": "10m",
                        "options": {"num_ctx": 4096},
                    }
                    resp = http.post(f"{self.host}/api/generate", json=payload_json)
                    if resp.status_code == 500:
                        # Retry once in safe low-VRAM mode (smaller context, CPU fallback)
                        payload_json["options"] = {"num_ctx": 2048, "num_gpu": 0}
                        resp = http.post(f"{self.host}/api/generate", json=payload_json)
                    if resp.status_code != 200:
                        self.last_error = (
                            f"Ollama HTTP {resp.status_code}（模型 {self.model} 執行失敗，"
                            f"建議於設定改用較輕量模型如 gemma4:e2b）：{resp.text[:160]}"
                        )
                        break
                    translated = resp.json().get("response", "").strip()
                    if not translated:
                        continue
                    if target_language == "zh-TW":
                        if k != "name_zh" and not _contains_cjk(orig_val):
                            if orig_val.lower() not in translated.lower():
                                translated = f"{translated} ({orig_val})"
                        updates[k] = translated
                    else:
                        updates[k] = _strip_cjk(translated) if _contains_cjk(translated) else translated
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    self.last_error = f"Ollama 連線或推論失敗：{exc}"
                    break
        finally:
            if own_client:
                http.close()

        if target_language == "en":
            updates["name_zh"] = ""
            if not sds.name_en and sds.name_zh:
                updates["name_en"] = _strip_cjk(sds.name_zh)
        else:
            updates["name_en"] = sds.name_en

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
