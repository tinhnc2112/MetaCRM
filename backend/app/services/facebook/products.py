"""Page-scoped Product catalog services."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from app.models.auth import User
from app.models.facebook import FacebookPage
from app.models.products import Product
from app.services.facebook.conversations import PaginatedResult
from app.services.facebook.pages import get_current_page
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

MONEY_QUANTUM = Decimal("0.01")
MAX_MONEY = Decimal("9999999999.99")


class DuplicateProductSkuError(ValueError):
    """Raised when a Page already contains the requested non-null SKU."""


class ProductUnavailableError(ValueError):
    """Raised when an order item cannot use the requested Product."""


def _normalise_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _money(value: Decimal | int | float | str) -> Decimal:
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if amount < 0:
        raise ValueError("sale_price must not be negative")
    if amount > MAX_MONEY:
        raise ValueError("sale_price exceeds Numeric(12, 2) capacity")
    amount = amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    return amount


def _product_for_page(session: Session, page_id: int, product_uuid: str) -> Product | None:
    try:
        public_id = UUID(product_uuid)
    except ValueError:
        return None
    return (
        session.query(Product)
        .options(joinedload(Product.inventory))
        .filter(
            Product.public_id == public_id,
            Product.facebook_page_id == page_id,
            Product.deleted_at.is_(None),
        )
        .first()
    )


def _sku_exists(
    session: Session,
    page_id: int,
    sku: str | None,
    *,
    exclude_product_id: int | None = None,
) -> bool:
    if sku is None:
        return False
    query = session.query(Product.id).filter(
        Product.facebook_page_id == page_id, Product.sku == sku
    )
    if exclude_product_id is not None:
        query = query.filter(Product.id != exclude_product_id)
    return query.first() is not None


def list_products(
    session: Session,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    active: bool | None = None,
    sku: str | None = None,
) -> PaginatedResult[Product] | None:
    current_page = get_current_page(session, user)
    if current_page is None:
        return None

    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    query = session.query(Product).filter(
        Product.facebook_page_id == current_page.id,
        Product.deleted_at.is_(None),
    )
    if active is not None:
        query = query.filter(Product.is_active.is_(active))
    if q and q.strip():
        search = f"%{q.strip()}%"
        query = query.filter(or_(Product.name.ilike(search), Product.sku.ilike(search)))
    if sku and sku.strip():
        query = query.filter(Product.sku == sku.strip())

    total = query.count()
    items = (
        query.options(joinedload(Product.inventory))
        .order_by(Product.name.asc(), Product.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResult(items=items, total=total, page=page, page_size=page_size)


def get_product(session: Session, user: User, product_uuid: str) -> Product | None:
    current_page = get_current_page(session, user)
    if current_page is None:
        return None
    return _product_for_page(session, current_page.id, product_uuid)


def create_product(session: Session, user: User, data: Mapping[str, object]) -> Product | None:
    current_page = get_current_page(session, user)
    if current_page is None:
        return None

    name = str(data["name"]).strip()
    if not name:
        raise ValueError("name must not be empty")
    sku = _normalise_optional_text(data.get("sku"))  # type: ignore[arg-type]
    if _sku_exists(session, current_page.id, sku):
        raise DuplicateProductSkuError("SKU already exists for this Facebook Page")

    currency = str(data.get("currency") or "VND").strip().upper()
    if not currency:
        raise ValueError("currency must not be empty")
    product = Product(
        facebook_page_id=current_page.id,
        name=name,
        sku=sku,
        currency=currency,
        sale_price=_money(data["sale_price"]),  # type: ignore[arg-type]
        description=_normalise_optional_text(data.get("description")),  # type: ignore[arg-type]
        is_active=bool(data.get("is_active", True)),
    )
    session.add(product)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if sku is not None:
            raise DuplicateProductSkuError("SKU already exists for this Facebook Page") from exc
        raise
    session.refresh(product)
    return product


def update_product(
    session: Session,
    user: User,
    product_uuid: str,
    data: Mapping[str, object],
) -> Product | None:
    current_page = get_current_page(session, user)
    if current_page is None:
        return None
    product = _product_for_page(session, current_page.id, product_uuid)
    if product is None:
        return None

    if "name" in data:
        name = str(data["name"]).strip()
        if not name:
            raise ValueError("name must not be empty")
        product.name = name
    if "sku" in data:
        sku = _normalise_optional_text(data["sku"])  # type: ignore[arg-type]
        if _sku_exists(session, current_page.id, sku, exclude_product_id=product.id):
            raise DuplicateProductSkuError("SKU already exists for this Facebook Page")
        product.sku = sku
    if "currency" in data:
        currency = str(data["currency"]).strip().upper()
        if not currency:
            raise ValueError("currency must not be empty")
        product.currency = currency
    if "sale_price" in data:
        product.sale_price = _money(data["sale_price"])  # type: ignore[arg-type]
    if "description" in data:
        product.description = _normalise_optional_text(data["description"])  # type: ignore[arg-type]
    if "is_active" in data:
        product.is_active = bool(data["is_active"])

    pending_sku = product.sku
    session.add(product)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if pending_sku is not None:
            raise DuplicateProductSkuError("SKU already exists for this Facebook Page") from exc
        raise
    session.refresh(product)
    return product


def archive_product(session: Session, user: User, product_uuid: str) -> Product | None:
    current_page = get_current_page(session, user)
    if current_page is None:
        return None
    product = _product_for_page(session, current_page.id, product_uuid)
    if product is None:
        return None
    product.is_active = False
    product.deleted_at = datetime.now(UTC)
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def resolve_product_for_order_item(
    session: Session,
    page: FacebookPage,
    product_uuid: str,
) -> Product:
    product = _product_for_page(session, page.id, product_uuid)
    if product is None or not product.is_active:
        raise ProductUnavailableError("Product not found")
    return product
