"""SQLAlchemy 2.0 ORM models for LCSS."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class."""


class Chemical(Base):
    """Chemical master record keyed by CAS Number."""

    __tablename__ = "chemicals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cas_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name_zh: Mapped[str] = mapped_column(String(255), default="")
    name_en: Mapped[str] = mapped_column(String(255), default="")
    formula: Mapped[str] = mapped_column(String(128), default="")
    molecular_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    smiles: Mapped[str] = mapped_column(Text, default="")
    inchikey: Mapped[str] = mapped_column(String(64), default="")

    ghs_pictograms: Mapped[list[str]] = mapped_column(JSON, default=list)
    signal_word: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    h_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    p_codes: Mapped[list[str]] = mapped_column(JSON, default=list)

    reactive_groups: Mapped[list[str]] = mapped_column(JSON, default=list)
    group_source: Mapped[str] = mapped_column(String(32), default="MANUAL")
    control_level: Mapped[str] = mapped_column(String(32), default="NORMAL")

    sds_json: Mapped[dict] = mapped_column(JSON, default=dict)
    data_source: Mapped[str] = mapped_column(String(64), default="LOCAL_CACHE")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    inventory_items: Mapped[list["InventoryItem"]] = relationship(
        back_populates="chemical", cascade="all, delete-orphan"
    )
    sds_documents: Mapped[list["SDSDocument"]] = relationship(
        back_populates="chemical", cascade="all, delete-orphan"
    )


class StorageLocation(Base):
    """3-level hierarchical storage location: Lab -> Cabinet -> Shelf."""

    __tablename__ = "storage_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lab_name: Mapped[str] = mapped_column(String(128), nullable=False)
    cabinet_name: Mapped[str] = mapped_column(String(128), nullable=False)
    shelf_name: Mapped[str] = mapped_column(String(128), default="第 1 層")
    cabinet_type: Mapped[str] = mapped_column(String(32), default="GENERAL")
    notes: Mapped[str] = mapped_column(Text, default="")

    items: Mapped[list["InventoryItem"]] = relationship(back_populates="location")

    @property
    def display_name(self) -> str:
        return f"{self.lab_name} / {self.cabinet_name} / {self.shelf_name}"


class InventoryItem(Base):
    """Physical bottle / prepared reagent instance."""

    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chemical_id: Mapped[int] = mapped_column(ForeignKey("chemicals.id"), nullable=False)
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("storage_locations.id"), nullable=True)

    barcode: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), default="COMMERCIAL")
    brand: Mapped[str] = mapped_column(String(128), default="")
    lot_number: Mapped[str] = mapped_column(String(128), default="")
    concentration: Mapped[str] = mapped_column(String(64), default="")
    prepared_by: Mapped[str] = mapped_column(String(128), default="")
    parent_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inventory_items.id"), nullable=True)

    capacity: Mapped[float] = mapped_column(Float, default=500.0)
    current_quantity: Mapped[float] = mapped_column(Float, default=500.0)
    unit: Mapped[str] = mapped_column(String(32), default="mL")
    opened_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="IN_STOCK")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    chemical: Mapped["Chemical"] = relationship(back_populates="inventory_items")
    location: Mapped[Optional["StorageLocation"]] = relationship(back_populates="items")
    logs: Mapped[list["InventoryLog"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class InventoryLog(Base):
    """Audit log for inventory movements and compatibility warning overrides."""

    __tablename__ = "inventory_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    delta_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    from_location_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    to_location_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    operator: Mapped[str] = mapped_column(String(128), default="系統管理員")
    override_warning_reason: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    item: Mapped["InventoryItem"] = relationship(back_populates="logs")


class SDSDocument(Base):
    """Archived supplier PDF or generated draft PDF metadata."""

    __tablename__ = "sds_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chemical_id: Mapped[int] = mapped_column(ForeignKey("chemicals.id"), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(32), default="SUPPLIER_OFFICIAL")
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(128), default="")
    revision_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    chemical: Mapped["Chemical"] = relationship(back_populates="sds_documents")
