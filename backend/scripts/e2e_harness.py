"""Prepare and serve the isolated database used by browser E2E tests.

This module is test infrastructure, not an application endpoint. It will not
touch a database unless the explicit E2E gate is enabled and the target
database name ends with ``_e2e``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+_e2e$")
E2E_USERNAME = "e2e.operator"
E2E_EMAIL = "e2e.operator@example.test"
E2E_PASSWORD = "MetaCRM-e2e-password"
PAGE_A_ID = "e2e-page-a"
PAGE_B_ID = "e2e-page-b"


def require_e2e_gate() -> None:
    if os.environ.get("METACRM_E2E", "").lower() != "true":
        raise SystemExit("Refusing E2E database access: METACRM_E2E must equal true")


def e2e_database_url() -> URL:
    load_dotenv(PROJECT_ROOT / ".env")
    require_e2e_gate()
    explicit_url = os.environ.get("METACRM_E2E_DATABASE_URL")
    if explicit_url:
        target = make_url(explicit_url)
    else:
        from app.core.config import get_settings

        settings = get_settings()
        base = make_url(settings.database_url)
        base_name = base.database
        if not base_name:
            raise SystemExit("Refusing E2E database access: DATABASE_URL has no database name")
        target_name = base_name if base_name.endswith("_e2e") else f"{base_name}_e2e"
        target = base.set(database=target_name)

    if target.drivername != "mysql+pymysql":
        raise SystemExit("Refusing E2E database access: MySQL PyMySQL URL required")
    if not target.database or not DATABASE_NAME_PATTERN.fullmatch(target.database):
        raise SystemExit("Refusing E2E database access: database name must end in _e2e")
    return target


def runtime_environment(target: URL) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "METACRM_E2E": "true",
            "APP_ENV": "test",
            "DATABASE_URL": target.render_as_string(hide_password=False),
            "CORS_ORIGINS": "http://127.0.0.1:5173",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8001",
            "LOG_LEVEL": "WARNING",
        }
    )
    return environment


def ensure_database(target: URL) -> None:
    database_name = target.database
    assert database_name is not None
    admin_url_value = os.environ.get("METACRM_E2E_ADMIN_DATABASE_URL")
    if admin_url_value:
        admin_url = make_url(admin_url_value)
        if admin_url.drivername != "mysql+pymysql":
            raise SystemExit("METACRM_E2E_ADMIN_DATABASE_URL must use MySQL PyMySQL")
        engine = create_engine(admin_url.set(database="", query={}), pool_pre_ping=True)
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.execute(
                    text(
                        f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                )
        finally:
            engine.dispose()

    engine = create_engine(target, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:
        raise SystemExit(
            f"Dedicated E2E database '{database_name}' is unavailable. Pre-create it and grant "
            "the E2E user access, or set METACRM_E2E_ADMIN_DATABASE_URL for provisioning."
        ) from exc
    finally:
        engine.dispose()


def reset_schema(target: URL) -> None:
    """Drop tables only inside the suffix-guarded disposable database."""
    engine = create_engine(target, pool_pre_ping=True)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            table_names = inspect(connection).get_table_names()
            connection.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            try:
                for table_name in table_names:
                    safe_table_name = table_name.replace("`", "``")
                    connection.execute(text(f"DROP TABLE `{safe_table_name}`"))
            finally:
                connection.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    finally:
        engine.dispose()


def migrate(environment: dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
    )


def seed(environment: dict[str, str]) -> dict[str, object]:
    os.environ.update(environment)
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.db.session import SessionLocal, dispose_engine
    from app.models.auth import User
    from app.models.customer_core import Customer, CustomerIdentity
    from app.models.facebook import FacebookAccount, FacebookPage, UserPageContext
    from app.models.messenger import Conversation
    from app.models.orders import Order, OrderEvent, OrderItem
    from app.models.products import Product
    from app.services.facebook.inventory import enable_product_inventory
    from app.utils.password import hash_password

    with SessionLocal() as session:
        user = User(
            username=E2E_USERNAME,
            email=E2E_EMAIL,
            password_hash=hash_password(E2E_PASSWORD),
            full_name="E2E Operator",
            is_active=True,
        )
        session.add(user)
        session.flush()

        account = FacebookAccount(
            user_id=user.id,
            facebook_user_id="e2e-facebook-user",
            access_token_encrypted="e2e-placeholder-not-a-real-credential",
            is_active=True,
        )
        session.add(account)
        session.flush()

        page_a = FacebookPage(
            facebook_account_id=account.id,
            page_id=PAGE_A_ID,
            name="E2E Page A",
            username="e2e_page_a",
            access_token_encrypted="e2e-placeholder-not-a-real-credential",
            is_active=True,
        )
        page_b = FacebookPage(
            facebook_account_id=account.id,
            page_id=PAGE_B_ID,
            name="E2E Page B",
            username="e2e_page_b",
            access_token_encrypted="e2e-placeholder-not-a-real-credential",
            is_active=True,
        )
        session.add_all([page_a, page_b])
        session.flush()
        session.add(UserPageContext(user_id=user.id, facebook_page_id=page_a.id))

        customer_a = Customer(
            name="E2E Customer A",
            phone="0900000001",
            email="customer-a@example.test",
            default_address="1 Test Street",
        )
        customer_beta = Customer(
            name="E2E Customer Beta",
            phone="0900000003",
            email="customer-beta@example.test",
            default_address="3 Test Street",
        )
        customer_b = Customer(
            name="E2E Customer B",
            phone="0900000002",
            email="customer-b@example.test",
            default_address="2 Test Street",
        )
        session.add_all([customer_a, customer_beta, customer_b])
        session.flush()
        session.add_all(
            [
                CustomerIdentity(
                    customer_id=customer_a.id,
                    facebook_page_id=page_a.id,
                    channel="facebook",
                    external_id="e2e-psid-a",
                    display_name=customer_a.name,
                ),
                CustomerIdentity(
                    customer_id=customer_beta.id,
                    facebook_page_id=page_a.id,
                    channel="facebook",
                    external_id="e2e-psid-beta",
                    display_name=customer_beta.name,
                ),
                CustomerIdentity(
                    customer_id=customer_b.id,
                    facebook_page_id=page_b.id,
                    channel="facebook",
                    external_id="e2e-psid-b",
                    display_name=customer_b.name,
                ),
            ]
        )

        conversation_a = Conversation(
            facebook_page_id=page_a.id,
            page_id=PAGE_A_ID,
            psid="e2e-psid-a",
            customer_id=customer_a.id,
            customer_name=customer_a.name,
        )
        conversation_b = Conversation(
            facebook_page_id=page_b.id,
            page_id=PAGE_B_ID,
            psid="e2e-psid-b",
            customer_id=customer_b.id,
            customer_name=customer_b.name,
        )
        conversation_beta = Conversation(
            facebook_page_id=page_a.id,
            page_id=PAGE_A_ID,
            psid="e2e-psid-beta",
            customer_id=customer_beta.id,
            customer_name=customer_beta.name,
        )
        session.add_all([conversation_a, conversation_beta, conversation_b])
        session.flush()

        product = Product(
            facebook_page_id=page_a.id,
            name="E2E Product A",
            sku="E2E-SKU-A",
            currency="VND",
            sale_price=Decimal("125000.00"),
            description="Deterministic browser test product",
            is_active=True,
        )
        critical_product = Product(
            facebook_page_id=page_a.id,
            name="E2E Critical Tracked Product",
            sku="E2E-CRITICAL-A",
            currency="VND",
            sale_price=Decimal("150000.00"),
            description="Tracked Product for the critical Order lifecycle",
            is_active=True,
        )
        low_stock_product = Product(
            facebook_page_id=page_a.id,
            name="E2E Low Stock Product",
            sku="E2E-LOW-B",
            currency="VND",
            sale_price=Decimal("75000.00"),
            description="Tracked Product for insufficient-stock coverage",
            is_active=True,
        )
        session.add_all([product, critical_product, low_stock_product])
        session.commit()
        assert enable_product_inventory(
            session,
            user,
            str(critical_product.public_id),
            opening_quantity=10,
            note="E2E critical workflow opening stock",
        ) is not None
        assert enable_product_inventory(
            session,
            user,
            str(low_stock_product.public_id),
            opening_quantity=1,
            note="E2E low-stock workflow opening stock",
        ) is not None

        order = Order(
            facebook_page_id=page_a.id,
            customer_id=customer_a.id,
            conversation_id=conversation_a.id,
            order_number="E2E-A-1001",
            status="draft",
            payment_status="unpaid",
            shipping_status="pending",
            currency="VND",
            subtotal_amount=Decimal("250000.00"),
            total_amount=Decimal("250000.00"),
            customer_name_snapshot=customer_a.name,
            customer_phone_snapshot=customer_a.phone,
            customer_email_snapshot=customer_a.email,
            shipping_address=customer_a.default_address,
            created_by_id=user.id,
        )
        session.add(order)
        session.flush()
        session.add_all(
            [
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    item_name=product.name,
                    sku=product.sku,
                    quantity=2,
                    unit_price=Decimal("125000.00"),
                    line_total=Decimal("250000.00"),
                ),
                OrderEvent(
                    order_id=order.id,
                    event_type="ORDER_CREATED",
                    to_value="draft",
                    created_by_id=user.id,
                ),
            ]
        )
        session.commit()
        fixture = {
            "username": E2E_USERNAME,
            "password": E2E_PASSWORD,
            "pages": {"a": PAGE_A_ID, "b": PAGE_B_ID},
            "customer": str(customer_a.public_id),
            "customers": {
                "a": str(customer_a.public_id),
                "beta": str(customer_beta.public_id),
                "page_b": str(customer_b.public_id),
            },
            "products": {
                "baseline": str(product.public_id),
                "critical": {
                    "uuid": str(critical_product.public_id),
                    "starting_stock": 10,
                },
                "low_stock": {
                    "uuid": str(low_stock_product.public_id),
                    "starting_stock": 1,
                },
            },
            "order": str(order.public_id),
        }

    dispose_engine()
    return fixture


def prepare() -> tuple[URL, dict[str, str], dict[str, object]]:
    target = e2e_database_url()
    environment = runtime_environment(target)
    ensure_database(target)
    reset_schema(target)
    migrate(environment)
    fixture = seed(environment)
    return target, environment, fixture


def run_server() -> None:
    _, environment, fixture = prepare()
    print(json.dumps(fixture), flush=True)
    os.environ.update(environment)
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "serve", "cleanup"))
    args = parser.parse_args()

    if args.command == "cleanup":
        target = e2e_database_url()
        ensure_database(target)
        reset_schema(target)
        print(json.dumps({"database": target.database, "records_removed": True}))
    elif args.command == "serve":
        run_server()
    else:
        _, _, fixture = prepare()
        print(json.dumps(fixture))


if __name__ == "__main__":
    main()
