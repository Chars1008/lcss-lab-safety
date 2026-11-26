"""Tests for ChemResolver: CAS checksum, offline lookup, and respx-mocked online lookup."""

import httpx
import respx

from app.core.chem_resolver import ChemResolver, validate_cas_checksum


def test_cas_checksum_validation():
    assert validate_cas_checksum("7647-01-0") is True
    assert validate_cas_checksum("7681-52-9") is True
    assert validate_cas_checksum("64-17-5") is True
    assert validate_cas_checksum("7647-01-9") is False
    assert validate_cas_checksum("not-a-cas") is False


def test_offline_resolution_and_hp_translation():
    resolver = ChemResolver()
    res = resolver.resolve_offline("7647-01-0")
    assert res is not None
    assert res.name_en == "Hydrochloric acid"
    assert "GHS05" in res.ghs_pictograms
    assert res.sds_payload is not None
    assert any("腐蝕金屬" in line for line in res.sds_payload.h_statements_zh)


@respx.mock
def test_online_resolution_with_mocked_pubchem_and_tw_ghs():
    cas = "67-64-1"
    respx.get(
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{cas}/property/"
        "MolecularFormula,MolecularWeight,CanonicalSMILES,InChIKey,IUPACName,Title/JSON"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "PropertyTable": {
                    "Properties": [
                        {
                            "CID": 180,
                            "MolecularFormula": "C3H6O",
                            "MolecularWeight": "58.08",
                            "CanonicalSMILES": "CC(=O)C",
                            "InChIKey": "CSCPPACGZOOCGX-UHFFFAOYSA-N",
                            "Title": "Acetone",
                        }
                    ]
                }
            },
        )
    )
    respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/180/JSON?heading=GHS+Classification").mock(
        return_value=httpx.Response(200, text='{"Signal": "Danger", "Codes": ["GHS02", "GHS07", "H225", "H319", "P210"]}')
    )
    respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/180/JSON?heading=Chemical+and+Physical+Properties").mock(
        return_value=httpx.Response(
            200,
            json={
                "Record": {
                    "Section": [
                        {
                            "TOCHeading": "Experimental Properties",
                            "Section": [
                                {"TOCHeading": "Physical Description", "Information": [{"Value": {"StringWithMarkup": [{"String": "Clear colorless liquid"}]}}]},
                                {"TOCHeading": "Boiling Point", "Information": [{"Value": {"StringWithMarkup": [{"String": "56.05 °C"}]}}]},
                            ],
                        }
                    ]
                }
            },
        )
    )
    respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/180/JSON?heading=Safety+and+Hazards").mock(
        return_value=httpx.Response(200, json={"Record": {"Section": []}})
    )
    respx.get("https://ghs.osha.gov.tw/CHT/intro/search.aspx", params={"cas": cas}).mock(
        return_value=httpx.Response(200, text="<html><span class='chem-name-zh'>丙酮</span></html>")
    )

    resolver = ChemResolver()
    resolved = resolver.resolve_online(cas)
    assert resolved is not None
    assert resolved.cas_number == cas
    assert resolved.name_zh == "丙酮"
    assert "GHS02" in resolved.ghs_pictograms
    assert "H225" in resolved.h_codes
    assert resolved.sds_payload is not None
    assert "Clear colorless liquid" in resolved.sds_payload.phys_appearance
    assert "56.05 °C" in resolved.sds_payload.phys_boiling_point
