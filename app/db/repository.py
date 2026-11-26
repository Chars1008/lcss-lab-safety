"""Repository layer for CRUD and domain queries on LCSS SQLite database."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Chemical, InventoryItem, InventoryLog, SDSDocument, StorageLocation
from app.schemas import InventoryAction, ItemStatus, ResolvedChemical


class LCSSRepository:
    """Data access object encapsulating all database operations."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Chemicals
    # ------------------------------------------------------------------
    def get_chemical_by_cas(self, cas_number: str) -> Optional[Chemical]:
        stmt = select(Chemical).where(Chemical.cas_number == cas_number.strip())
        return self.session.scalar(stmt)

    def get_chemical_by_id(self, chemical_id: int) -> Optional[Chemical]:
        return self.session.get(Chemical, chemical_id)

    def search_chemicals(self, query: str = "") -> list[Chemical]:
        stmt = select(Chemical).order_by(Chemical.name_zh, Chemical.name_en)
        if query.strip():
            like = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    Chemical.cas_number.ilike(like),
                    Chemical.name_zh.ilike(like),
                    Chemical.name_en.ilike(like),
                    Chemical.formula.ilike(like),
                )
            )
        return list(self.session.scalars(stmt).all())

    def upsert_chemical(self, data: ResolvedChemical) -> Chemical:
        chem = self.get_chemical_by_cas(data.cas_number)
        sds_dict = data.sds_payload.model_dump(mode="json") if data.sds_payload else {}
        if chem is None:
            chem = Chemical(
                cas_number=data.cas_number,
                name_zh=data.name_zh,
                name_en=data.name_en,
                formula=data.formula,
                molecular_weight=data.molecular_weight,
                smiles=data.smiles,
                inchikey=data.inchikey,
                ghs_pictograms=data.ghs_pictograms,
                signal_word=data.signal_word,
                h_codes=data.h_codes,
                p_codes=data.p_codes,
                reactive_groups=data.reactive_groups,
                group_source=data.group_source.value,
                control_level=data.control_level.value,
                sds_json=sds_dict,
                data_source=data.data_source,
            )
            self.session.add(chem)
        else:
            chem.name_zh = data.name_zh or chem.name_zh
            chem.name_en = data.name_en or chem.name_en
            chem.formula = data.formula or chem.formula
            chem.molecular_weight = data.molecular_weight or chem.molecular_weight
            chem.smiles = data.smiles or chem.smiles
            chem.inchikey = data.inchikey or chem.inchikey
            chem.ghs_pictograms = data.ghs_pictograms or chem.ghs_pictograms
            chem.signal_word = data.signal_word or chem.signal_word
            chem.h_codes = data.h_codes or chem.h_codes
            chem.p_codes = data.p_codes or chem.p_codes
            chem.reactive_groups = data.reactive_groups or chem.reactive_groups
            chem.group_source = data.group_source.value
            chem.control_level = data.control_level.value
            if sds_dict:
                chem.sds_json = sds_dict
            chem.data_source = data.data_source
        self.session.commit()
        self.session.refresh(chem)
        return chem

    def update_chemical_sds(self, chemical_id: int, sds_json: dict) -> Optional[Chemical]:
        chem = self.get_chemical_by_id(chemical_id)
        if chem is None:
            return None
        chem.sds_json = sds_json
        self.session.commit()
        self.session.refresh(chem)
        return chem

    # ------------------------------------------------------------------
    # Storage Locations
    # ------------------------------------------------------------------
    def list_locations(self) -> list[StorageLocation]:
        stmt = select(StorageLocation).order_by(
            StorageLocation.lab_name, StorageLocation.cabinet_name, StorageLocation.shelf_name
        )
        return list(self.session.scalars(stmt).all())

    def get_location(self, location_id: int) -> Optional[StorageLocation]:
        return self.session.get(StorageLocation, location_id)

    def create_location(
        self,
        lab_name: str,
        cabinet_name: str,
        shelf_name: str = "第 1 層",
        cabinet_type: str = "GENERAL",
        notes: str = "",
    ) -> StorageLocation:
        loc = StorageLocation(
            lab_name=lab_name,
            cabinet_name=cabinet_name,
            shelf_name=shelf_name,
            cabinet_type=cabinet_type,
            notes=notes,
        )
        self.session.add(loc)
        self.session.commit()
        self.session.refresh(loc)
        return loc

    # ------------------------------------------------------------------
    # Inventory Items & Logs
    # ------------------------------------------------------------------
    def generate_barcode(self) -> str:
        return f"LCSS-{uuid.uuid4().hex[:8].upper()}"

    def list_inventory_items(
        self,
        search: str = "",
        status: Optional[str] = None,
        location_id: Optional[int] = None,
    ) -> list[InventoryItem]:
        stmt = (
            select(InventoryItem)
            .options(joinedload(InventoryItem.chemical), joinedload(InventoryItem.location))
            .order_by(InventoryItem.updated_at.desc())
        )
        if status:
            stmt = stmt.where(InventoryItem.status == status)
        if location_id is not None:
            stmt = stmt.where(InventoryItem.location_id == location_id)
        items = list(self.session.scalars(stmt).all())
        if search.strip():
            q = search.strip().lower()
            items = [
                item
                for item in items
                if q in item.barcode.lower()
                or q in (item.brand or "").lower()
                or (item.chemical and (
                    q in item.chemical.cas_number.lower()
                    or q in item.chemical.name_zh.lower()
                    or q in item.chemical.name_en.lower()
                ))
            ]
        return items

    def get_item_by_barcode(self, barcode: str) -> Optional[InventoryItem]:
        stmt = (
            select(InventoryItem)
            .options(joinedload(InventoryItem.chemical), joinedload(InventoryItem.location))
            .where(InventoryItem.barcode == barcode.strip())
        )
        return self.session.scalar(stmt)

    def get_items_in_location(self, location_id: int) -> list[InventoryItem]:
        stmt = (
            select(InventoryItem)
            .options(joinedload(InventoryItem.chemical))
            .where(
                InventoryItem.location_id == location_id,
                InventoryItem.status == ItemStatus.IN_STOCK.value,
            )
        )
        return list(self.session.scalars(stmt).all())

    def check_in_item(
        self,
        chemical_id: int,
        location_id: Optional[int],
        capacity: float,
        unit: str = "mL",
        current_quantity: Optional[float] = None,
        barcode: Optional[str] = None,
        item_type: str = "COMMERCIAL",
        brand: str = "",
        lot_number: str = "",
        concentration: str = "",
        prepared_by: str = "",
        parent_item_id: Optional[int] = None,
        opened_date: Optional[date] = None,
        expiry_date: Optional[date] = None,
        operator: str = "系統管理員",
        override_warning_reason: str = "",
    ) -> InventoryItem:
        qty = current_quantity if current_quantity is not None else capacity
        item = InventoryItem(
            chemical_id=chemical_id,
            location_id=location_id,
            barcode=barcode or self.generate_barcode(),
            item_type=item_type,
            brand=brand,
            lot_number=lot_number,
            concentration=concentration,
            prepared_by=prepared_by,
            parent_item_id=parent_item_id,
            capacity=capacity,
            current_quantity=qty,
            unit=unit,
            opened_date=opened_date,
            expiry_date=expiry_date,
            status=ItemStatus.IN_STOCK.value if qty > 0 else ItemStatus.EMPTY.value,
        )
        self.session.add(item)
        self.session.flush()

        log = InventoryLog(
            item_id=item.id,
            action=InventoryAction.CHECK_IN.value,
            delta_quantity=qty,
            to_location_id=location_id,
            operator=operator,
            override_warning_reason=override_warning_reason,
        )
        self.session.add(log)
        self.session.commit()
        self.session.refresh(item)
        return item

    def check_out_quantity(
        self,
        item_id: int,
        used_quantity: float,
        operator: str = "系統管理員",
    ) -> Optional[InventoryItem]:
        item = self.session.get(InventoryItem, item_id)
        if item is None:
            return None
        actual_used = min(max(used_quantity, 0.0), item.current_quantity)
        item.current_quantity = max(0.0, item.current_quantity - actual_used)
        if item.current_quantity <= 0:
            item.status = ItemStatus.EMPTY.value
        log = InventoryLog(
            item_id=item.id,
            action=InventoryAction.CHECK_OUT.value,
            delta_quantity=-actual_used,
            from_location_id=item.location_id,
            to_location_id=item.location_id,
            operator=operator,
        )
        self.session.add(log)
        self.session.commit()
        self.session.refresh(item)
        return item

    def move_item(
        self,
        item_id: int,
        new_location_id: int,
        operator: str = "系統管理員",
        override_warning_reason: str = "",
    ) -> Optional[InventoryItem]:
        item = self.session.get(InventoryItem, item_id)
        if item is None:
            return None
        old_loc = item.location_id
        item.location_id = new_location_id
        log = InventoryLog(
            item_id=item.id,
            action=InventoryAction.MOVE.value,
            delta_quantity=0.0,
            from_location_id=old_loc,
            to_location_id=new_location_id,
            operator=operator,
            override_warning_reason=override_warning_reason,
        )
        self.session.add(log)
        self.session.commit()
        self.session.refresh(item)
        return item

    def dispose_item(self, item_id: int, operator: str = "系統管理員") -> Optional[InventoryItem]:
        item = self.session.get(InventoryItem, item_id)
        if item is None:
            return None
        item.status = ItemStatus.DISPOSED.value
        log = InventoryLog(
            item_id=item.id,
            action=InventoryAction.DISPOSE.value,
            delta_quantity=-item.current_quantity,
            from_location_id=item.location_id,
            operator=operator,
        )
        item.current_quantity = 0.0
        self.session.add(log)
        self.session.commit()
        self.session.refresh(item)
        return item

    def list_expiring_items(self, within_days: int = 30) -> list[InventoryItem]:
        cutoff = date.today() + timedelta(days=within_days)
        stmt = (
            select(InventoryItem)
            .options(joinedload(InventoryItem.chemical), joinedload(InventoryItem.location))
            .where(
                InventoryItem.status == ItemStatus.IN_STOCK.value,
                InventoryItem.expiry_date.is_not(None),
                InventoryItem.expiry_date <= cutoff,
            )
            .order_by(InventoryItem.expiry_date)
        )
        return list(self.session.scalars(stmt).all())

    def list_low_stock_items(self, threshold_ratio: float = 0.2) -> list[InventoryItem]:
        items = self.list_inventory_items(status=ItemStatus.IN_STOCK.value)
        return [
            item
            for item in items
            if item.capacity > 0 and (item.current_quantity / item.capacity) <= threshold_ratio
        ]

    # ------------------------------------------------------------------
    # SDS Documents
    # ------------------------------------------------------------------
    def add_sds_document(
        self,
        chemical_id: int,
        file_path: str,
        doc_type: str = "SUPPLIER_OFFICIAL",
        supplier_name: str = "",
        revision_date: Optional[date] = None,
    ) -> SDSDocument:
        doc = SDSDocument(
            chemical_id=chemical_id,
            doc_type=doc_type,
            file_path=file_path,
            supplier_name=supplier_name,
            revision_date=revision_date,
        )
        self.session.add(doc)
        self.session.commit()
        self.session.refresh(doc)
        return doc

    def list_sds_documents(self, chemical_id: int) -> list[SDSDocument]:
        stmt = (
            select(SDSDocument)
            .where(SDSDocument.chemical_id == chemical_id)
            .order_by(SDSDocument.uploaded_at.desc())
        )
        return list(self.session.scalars(stmt).all())
