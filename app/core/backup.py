"""Export and import helpers for chemical inventory lists and application settings."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.db.database import DatabaseManager
from app.db.repository import LCSSRepository
from app.schemas import ControlLevel, GroupSource, ResolvedChemical, SDSPayload


def export_inventory_csv(db: DatabaseManager, output_path: Path | str) -> Path:
    """Export all chemicals & inventory items to UTF-8 BOM CSV (Excel friendly)."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with db.get_session() as session:
        repo = LCSSRepository(session)
        items = repo.list_inventory_items()
        chems = repo.search_chemicals()

    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "紀錄類型", "條碼", "CAS No.", "中文品名", "英文品名", "分子式",
            "試劑類型", "容量", "剩餘量", "單位", "存放位置", "有效期限", "狀態",
        ])
        seen_chem_ids: set[int] = set()
        for it in items:
            c = it.chemical
            if c:
                seen_chem_ids.add(c.id)
            writer.writerow([
                "庫存品項",
                it.barcode,
                c.cas_number if c else "",
                c.name_zh if c else "",
                c.name_en if c else "",
                c.formula if c else "",
                it.item_type,
                it.capacity,
                it.current_quantity,
                it.unit,
                it.location.display_name if it.location else "",
                it.expiry_date.isoformat() if it.expiry_date else "",
                it.status,
            ])
        for c in chems:
            if c.id not in seen_chem_ids:
                writer.writerow([
                    "藥品主檔(無庫存)", "", c.cas_number, c.name_zh, c.name_en, c.formula,
                    "", "", "", "", "", "", "",
                ])
    return out


def export_bundle_json(db: DatabaseManager, settings: AppSettings, output_path: Path | str) -> Path:
    """Export settings, storage locations, chemicals, and inventory items to JSON."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with db.get_session() as session:
        repo = LCSSRepository(session)
        locations = repo.list_locations()
        chemicals = repo.search_chemicals()
        items = repo.list_inventory_items()

        bundle: dict[str, Any] = {
            "version": 1,
            "settings": settings.model_dump(),
            "locations": [
                {
                    "lab_name": loc.lab_name,
                    "cabinet_name": loc.cabinet_name,
                    "shelf_name": loc.shelf_name,
                    "cabinet_type": loc.cabinet_type,
                    "notes": loc.notes,
                }
                for loc in locations
            ],
            "chemicals": [
                {
                    "cas_number": c.cas_number,
                    "name_zh": c.name_zh,
                    "name_en": c.name_en,
                    "formula": c.formula,
                    "molecular_weight": c.molecular_weight,
                    "smiles": c.smiles,
                    "inchikey": c.inchikey,
                    "ghs_pictograms": c.ghs_pictograms,
                    "signal_word": c.signal_word,
                    "h_codes": c.h_codes,
                    "p_codes": c.p_codes,
                    "reactive_groups": c.reactive_groups,
                    "group_source": c.group_source,
                    "control_level": c.control_level,
                    "sds_json": c.sds_json,
                    "data_source": c.data_source,
                }
                for c in chemicals
            ],
            "inventory_items": [
                {
                    "barcode": it.barcode,
                    "cas_number": it.chemical.cas_number if it.chemical else "",
                    "location_key": (
                        f"{it.location.lab_name}|{it.location.cabinet_name}|{it.location.shelf_name}"
                        if it.location
                        else ""
                    ),
                    "item_type": it.item_type,
                    "brand": it.brand,
                    "lot_number": it.lot_number,
                    "concentration": it.concentration,
                    "prepared_by": it.prepared_by,
                    "capacity": it.capacity,
                    "current_quantity": it.current_quantity,
                    "unit": it.unit,
                    "expiry_date": it.expiry_date.isoformat() if it.expiry_date else None,
                }
                for it in items
            ],
        }
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def import_bundle_json(
    db: DatabaseManager,
    settings: AppSettings,
    input_path: Path | str,
) -> dict[str, int]:
    """Import settings, locations, chemicals, and inventory items from a JSON bundle."""
    raw = json.loads(Path(input_path).read_text(encoding="utf-8"))

    # 1. Restore settings (preserve current db_path unless explicitly desired)
    if isinstance(raw.get("settings"), dict):
        s_data = raw["settings"]
        for key in (
            "lab_name",
            "lab_manager",
            "emergency_phone",
            "organization",
            "expiry_warning_days",
            "low_stock_threshold_ratio",
            "llm_enabled",
            "ollama_host",
            "ollama_model",
        ):
            if key in s_data:
                setattr(settings, key, s_data[key])
        settings.initialized = True
        settings.save()

    counts = {"locations": 0, "chemicals": 0, "items": 0}
    with db.get_session() as session:
        repo = LCSSRepository(session)
        existing_locs = {
            f"{l.lab_name}|{l.cabinet_name}|{l.shelf_name}": l.id for l in repo.list_locations()
        }
        for loc_data in raw.get("locations", []):
            key = f"{loc_data['lab_name']}|{loc_data['cabinet_name']}|{loc_data.get('shelf_name', '第 1 層')}"
            if key not in existing_locs:
                loc = repo.create_location(
                    lab_name=loc_data["lab_name"],
                    cabinet_name=loc_data["cabinet_name"],
                    shelf_name=loc_data.get("shelf_name", "第 1 層"),
                    cabinet_type=loc_data.get("cabinet_type", "GENERAL"),
                    notes=loc_data.get("notes", ""),
                )
                existing_locs[key] = loc.id
                counts["locations"] += 1

        for c_data in raw.get("chemicals", []):
            sds_dict = c_data.get("sds_json") or {}
            sds_payload = SDSPayload(**sds_dict) if sds_dict else None
            resolved = ResolvedChemical(
                cas_number=c_data["cas_number"],
                name_zh=c_data.get("name_zh", ""),
                name_en=c_data.get("name_en", ""),
                formula=c_data.get("formula", ""),
                molecular_weight=c_data.get("molecular_weight"),
                smiles=c_data.get("smiles", ""),
                inchikey=c_data.get("inchikey", ""),
                ghs_pictograms=c_data.get("ghs_pictograms", []),
                signal_word=c_data.get("signal_word"),
                h_codes=c_data.get("h_codes", []),
                p_codes=c_data.get("p_codes", []),
                reactive_groups=c_data.get("reactive_groups", []),
                group_source=GroupSource(c_data.get("group_source", "MANUAL")),
                control_level=ControlLevel(c_data.get("control_level", "NORMAL")),
                sds_payload=sds_payload,
                data_source=c_data.get("data_source", "IMPORTED"),
            )
            repo.upsert_chemical(resolved)
            counts["chemicals"] += 1

        for it_data in raw.get("inventory_items", []):
            barcode = it_data.get("barcode", "")
            if barcode and repo.get_item_by_barcode(barcode) is not None:
                continue
            chem = repo.get_chemical_by_cas(it_data.get("cas_number", ""))
            if chem is None:
                continue
            loc_id = existing_locs.get(it_data.get("location_key", ""))
            exp_str = it_data.get("expiry_date")
            exp_date = date.fromisoformat(exp_str) if exp_str else None
            repo.check_in_item(
                chemical_id=chem.id,
                location_id=loc_id,
                capacity=float(it_data.get("capacity", 500.0)),
                current_quantity=float(it_data.get("current_quantity", 500.0)),
                unit=it_data.get("unit", "mL"),
                barcode=barcode or None,
                item_type=it_data.get("item_type", "COMMERCIAL"),
                brand=it_data.get("brand", ""),
                lot_number=it_data.get("lot_number", ""),
                concentration=it_data.get("concentration", ""),
                prepared_by=it_data.get("prepared_by", ""),
                expiry_date=exp_date,
            )
            counts["items"] += 1

    return counts
