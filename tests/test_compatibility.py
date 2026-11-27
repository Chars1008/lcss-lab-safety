"""Tests for CompatibilityEngine including mandatory safety cases & RDKit SMARTS inference."""

from app.core.compatibility import CompatibilityEngine
from app.schemas import CabinetType, CompatibilityLevel, GroupSource


def test_bleach_plus_hcl_must_be_incompatible_toxic_gas():
    engine = CompatibilityEngine()
    bleach = {"cas_number": "7681-52-9", "name_zh": "次氯酸鈉"}
    hcl = {"cas_number": "7647-01-0", "name_zh": "鹽酸"}

    issue = engine.check_pair(bleach, hcl)
    assert issue.level == CompatibilityLevel.INCOMPATIBLE
    assert "TOXIC_GAS" in issue.hazards


def test_nitric_acid_plus_ethanol_must_be_incompatible_fire_explosion():
    engine = CompatibilityEngine()
    nitric = {"cas_number": "7697-37-2", "name_zh": "濃硝酸"}
    ethanol = {"cas_number": "64-17-5", "name_zh": "乙醇"}

    issue = engine.check_pair(nitric, ethanol)
    assert issue.level == CompatibilityLevel.INCOMPATIBLE
    assert any(h in issue.hazards for h in ("FIRE", "EXPLOSION"))


def test_unknown_cas_with_peroxide_and_azide_smiles_triggers_rdkit_smarts():
    engine = CompatibilityEngine()
    # Unknown CAS, tert-butyl hydroperoxide SMILES
    groups_p, src_p, _ = engine.classify_reactive_groups("999999-99-9", smiles="CC(C)(C)OO")
    assert src_p == GroupSource.RDKIT_INFERRED
    assert "RG17" in groups_p

    # Unknown CAS, ethyl azide SMILES
    groups_a, src_a, _ = engine.classify_reactive_groups("888888-88-8", smiles="CCN=[N+]=[N-]")
    assert src_a == GroupSource.RDKIT_INFERRED
    assert "RG07" in groups_a

    # Pairing unknown azide with HCl must trigger INCOMPATIBLE
    issue = engine.check_pair(
        {"cas_number": "888888-88-8", "name_zh": "未知疊氮物", "smiles": "CCN=[N+]=[N-]"},
        {"cas_number": "7647-01-0", "name_zh": "鹽酸"},
    )
    assert issue.level == CompatibilityLevel.INCOMPATIBLE
    assert "TOXIC_GAS" in issue.hazards


def test_cabinet_suitability_rejects_flammable_in_standard_fridge():
    engine = CompatibilityEngine()
    res = engine.check_cabinet_suitability(["GHS02"], ["RG04"], CabinetType.FRIDGE_4C)
    assert res.compatible is False
    assert res.level == CompatibilityLevel.INCOMPATIBLE


def test_sds_section_10_cross_check_catches_cameo_blind_spot():
    engine = CompatibilityEngine()
    # DMSO (67-68-5) is RG20 in CAMEO, but its SDS Section 10 warns against strong oxidizers
    dmso = {
        "cas_number": "67-68-5",
        "name_zh": "二甲基亞碸 (DMSO)",
        "sds_json": {"materials_to_avoid": "強氧化劑、醯氯、強酸"},
    }
    kmno4 = {
        "cas_number": "7722-64-7",
        "name_zh": "過錳酸鉀",
        "ghs_pictograms": ["GHS03"],
    }
    issue = engine.check_pair(dmso, kmno4)
    assert issue.level == CompatibilityLevel.CAUTION
    assert "SDS_INCOMPATIBLE" in issue.hazards
    assert "SDS 第 10 節" in issue.summary_zh


def test_phenol_plus_ethanol_must_be_compatible():
    from app.core.chem_resolver import ChemResolver
    engine = CompatibilityEngine()
    resolver = ChemResolver()
    phenol = resolver.resolve_offline("108-95-2")
    ethanol = resolver.resolve_offline("64-17-5")
    assert phenol is not None and ethanol is not None

    issue = engine.check_pair(
        {
            "cas_number": phenol.cas_number,
            "name_zh": phenol.name_zh,
            "ghs_pictograms": phenol.ghs_pictograms,
            "sds_json": phenol.sds_payload.model_dump(),
        },
        {
            "cas_number": ethanol.cas_number,
            "name_zh": ethanol.name_zh,
            "ghs_pictograms": ethanol.ghs_pictograms,
            "sds_json": ethanol.sds_payload.model_dump(),
        },
    )
    assert issue.level == CompatibilityLevel.COMPATIBLE
