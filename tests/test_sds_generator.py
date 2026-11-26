"""Tests for SDSGenerator, PDFParser, and LocalLLMService (with respx mock)."""

from datetime import date

import httpx
import respx

from app.core.chem_resolver import ChemResolver
from app.core.llm_service import LocalLLMService
from app.core.pdf_parser import PDFParser
from app.core.sds_generator import SDSGenerator
from app.schemas import ItemType, LabelRequest


def test_sds_and_label_pdf_generation_and_pymupdf_read(tmp_path):
    resolver = ChemResolver()
    ethanol = resolver.resolve_offline("64-17-5")
    assert ethanol is not None and ethanol.sds_payload is not None

    gen = SDSGenerator()
    sds_pdf = tmp_path / "ethanol_sds.pdf"
    gen.export_sds_pdf(ethanol.sds_payload, sds_pdf)
    assert sds_pdf.exists() and sds_pdf.stat().st_size > 1000

    parser = PDFParser()
    extracted = parser.extract_text(sds_pdf)
    assert "64-17-5" in extracted
    assert "系統彙整內部參考版" in extracted

    label_pdf = tmp_path / "ethanol_label.pdf"
    req = LabelRequest(
        item_type=ItemType.PREPARED,
        name_zh="75% 乙醇消毒液",
        name_en="75% Ethanol",
        cas_number="64-17-5",
        barcode="LCSS-TEST0001",
        ghs_pictograms=["GHS02", "GHS07"],
        signal_word="危險",
        concentration="75% v/v",
        prepared_by="王小明",
        prepared_date=date.today(),
    )
    gen.export_label_pdf(req, label_pdf)
    assert label_pdf.exists() and label_pdf.stat().st_size > 1000


def test_detailed_taiwan_epa_format_sds_for_acrylamide(tmp_path):
    resolver = ChemResolver()
    acrylamide = resolver.resolve_offline("79-06-1")
    assert acrylamide is not None and acrylamide.sds_payload is not None

    gen = SDSGenerator()
    pdf_path = tmp_path / "acrylamide_sds.pdf"
    gen.export_sds_pdf(acrylamide.sds_payload, pdf_path)
    assert pdf_path.exists()

    extracted = PDFParser().extract_text(pdf_path)
    for expected in (
        "050-01",
        "丙烯醯胺",
        "79-06-1",
        "國內控制參數",
        "0.03 mg/m3",
        "84.5℃",
        "2074",
        "第 6.1 類毒性物質",
        "系統彙整內部參考版",
    ):
        assert expected in extracted


@respx.mock
def test_llm_service_translation_and_graceful_degradation():
    resolver = ChemResolver()
    sds = resolver.resolve_offline("64-17-5").sds_payload
    assert sds is not None

    # Disabled mode returns original unchanged
    disabled_llm = LocalLLMService(enabled=False)
    assert disabled_llm.translate_sds_fields(sds).name_zh == sds.name_zh

    # Enabled mode with mocked Ollama
    respx.post("http://localhost:11434/api/generate").mock(
        return_value=httpx.Response(
            200,
            json={"response": '{"name_zh": "無水乙醇", "section_4_first_aid": "立即以清水沖洗15分鐘並送醫。"}'},
        )
    )
    enabled_llm = LocalLLMService(enabled=True)
    updated = enabled_llm.translate_sds_fields(sds)
    assert updated.name_zh == "無水乙醇"
    assert "15分鐘" in updated.section_4_first_aid
