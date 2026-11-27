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
        formula="C2H6O",
        molecular_weight=46.07,
        barcode="LCSS-TEST0001",
        ghs_pictograms=["GHS02", "GHS07"],
        signal_word="危險",
        concentration="75% v/v",
        prepared_by="王小明",
        prepared_date=date.today(),
    )
    html_lbl = gen.render_label_html(req)
    assert 'width="42"' in html_lbl
    assert "46.07 g/mol" in html_lbl
    assert "Formula" in html_lbl and "MW" in html_lbl

    gen.export_label_pdf(req, label_pdf)
    assert label_pdf.exists() and label_pdf.stat().st_size > 1000

    import fitz
    with fitz.open(str(label_pdf)) as doc:
        assert len(doc) == 1
        rect = doc[0].rect
        assert rect.width <= 305 and rect.height <= 430  # Within A6 (298 x 420 pt)


def test_detailed_taiwan_epa_format_sds_for_acrylamide(tmp_path):
    resolver = ChemResolver()
    acrylamide = resolver.resolve_offline("79-06-1")
    assert acrylamide is not None and acrylamide.sds_payload is not None

    gen = SDSGenerator()
    html = gen.render_sds_html(acrylamide.sds_payload)
    assert "data:image/png;base64," in html

    pdf_path = tmp_path / "acrylamide_sds.pdf"
    gen.export_sds_pdf(acrylamide.sds_payload, pdf_path)
    assert pdf_path.exists()

    import fitz
    with fitz.open(str(pdf_path)) as doc:
        assert len(doc[0].get_images()) >= 2  # GHS06 + GHS08 embedded in page 1

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


def test_dnph_sds_includes_explosive_when_dry_and_physical_properties(tmp_path):
    resolver = ChemResolver()
    dnph = resolver.resolve_offline("119-26-6")
    assert dnph is not None and dnph.sds_payload is not None

    pdf_path = tmp_path / "dnph_sds.pdf"
    SDSGenerator().export_sds_pdf(dnph.sds_payload, pdf_path)
    extracted = PDFParser().extract_text(pdf_path)

    for expected in ("119-26-6", "乾燥", "爆炸", "紅橙色結晶粉末", "198–202℃", "3380"):
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


@respx.mock
def test_english_sds_export_and_bidirectional_translation(tmp_path):
    resolver = ChemResolver()
    ethanol = resolver.resolve_offline("64-17-5")
    assert ethanol is not None and ethanol.sds_payload is not None

    gen = SDSGenerator()
    en_pdf = tmp_path / "ethanol_sds_en.pdf"
    gen.export_sds_pdf(ethanol.sds_payload, en_pdf, language="en")
    assert en_pdf.exists()

    extracted = PDFParser().extract_text(en_pdf)
    for expected in (
        "SAFETY DATA SHEET",
        "SECTION 1:",
        "SECTION 16:",
        "Danger",
        "H225: Highly flammable liquid and vapour",
    ):
        assert expected in extracted

    sds_zh_src = ethanol.sds_payload.model_copy(
        update={"recommended_use": "實驗室溶劑", "phys_appearance": "澄清液體"}
    )

    def _mock_translate(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        if "澄清液體" in body:
            return httpx.Response(200, json={"response": "Clear liquid (澄清液體)"})
        if "Clear colorless liquid" in body:
            return httpx.Response(200, json={"response": "澄清無色液體"})
        return httpx.Response(200, json={"response": "Laboratory solvent"})

    respx.post("http://localhost:11434/api/generate").mock(side_effect=_mock_translate)
    llm = LocalLLMService(enabled=True)
    translated_en = llm.translate_sds_language(sds_zh_src, target_language="en")
    assert translated_en.name_zh == ""
    assert translated_en.name_en == "Ethanol"
    assert translated_en.phys_appearance == "Clear liquid"

    # EN -> ZH: retains English name_en and English reference in translated field
    sds_en_src = ethanol.sds_payload.model_copy(update={"phys_appearance": "Clear colorless liquid"})
    translated_zh = llm.translate_sds_language(sds_en_src, target_language="zh-TW")
    assert translated_zh.name_en == "Ethanol"
    assert "乙醇" in translated_zh.name_zh
    assert "Clear colorless liquid" in translated_zh.phys_appearance
    assert "澄清無色液體" in translated_zh.phys_appearance
