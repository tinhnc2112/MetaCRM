"""Guarded InnoDB order/stock transition and adjustment invariants."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from os import environ
from threading import Barrier
from uuid import uuid4

import pytest
from app.models.auth import User
from app.models.customer_core import Customer
from app.models.facebook import FacebookPage
from app.models.inventory import ProductInventory, StockMovement
from app.models.messenger import Conversation
from app.models.orders import Order, OrderEvent, OrderItem
from app.models.products import Product
from app.services.facebook.inventory import InsufficientInventoryError, adjust_product_inventory
from app.services.facebook.orders import update_order
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


@pytest.fixture()
def stock_case():
    url = environ.get("DATABASE_URL", "")
    try:
        target = make_url(url)
    except Exception:
        pytest.skip("requires guarded disposable MySQL")
    if (
        environ.get("APP_ENV") != "test"
        or environ.get("METACRM_E2E") != "true"
        or target.drivername != "mysql+pymysql"
        or target.database != "metacrm_m0_test_e2e"
        or target.host not in {"localhost", "127.0.0.1"}
    ):
        pytest.skip("requires guarded disposable MySQL")
    engine = create_engine(url, pool_pre_ping=True)
    marker = uuid4().hex
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "e2e.operator"))
        page = session.scalar(select(FacebookPage).where(FacebookPage.page_id == "e2e-page-a"))
        assert user is not None and page is not None
        customer = Customer(name=f"m4-{marker}")
        session.add(customer)
        session.flush()
        conversation = Conversation(
            facebook_page_id=page.id,
            page_id=page.page_id,
            psid=f"m4-{marker}",
            customer_id=customer.id,
        )
        product = Product(
            facebook_page_id=page.id,
            name=f"m4-{marker}",
            sku=f"m4-{marker}",
            currency="VND",
            sale_price=Decimal("1.00"),
            track_inventory=True,
        )
        session.add_all([conversation, product])
        session.flush()
        inventory = ProductInventory(
            product_id=product.id,
            quantity_on_hand=10,
            tracking_started_at=datetime.now(UTC),
        )
        session.add(inventory)
        session.add(
            StockMovement(
                product_id=product.id,
                movement_type="OPENING",
                quantity_delta=10,
                quantity_before=0,
                quantity_after=10,
                idempotency_key=f"M4_OPEN:{marker}",
                created_by_id=user.id,
            )
        )
        order = Order(
            facebook_page_id=page.id,
            customer_id=customer.id,
            conversation_id=conversation.id,
            order_number=f"m4-{marker}",
            status="draft",
            subtotal_amount=Decimal("4.00"),
            total_amount=Decimal("4.00"),
            created_by_id=user.id,
        )
        session.add(order)
        session.flush()
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            item_name="M4 stock item",
            quantity=4,
            unit_price=Decimal("1.00"),
            line_total=Decimal("4.00"),
        )
        session.add(item)
        session.commit()
        keys = (
            user.id,
            customer.id,
            conversation.id,
            product.id,
            order.id,
            item.id,
            str(user.uuid),
            str(product.public_id),
            str(order.public_id),
        )
    try:
        yield engine, keys
    finally:
        user_id, customer_id, conv_id, product_id, order_id, item_id, *_ = keys
        with Session(engine) as session:
            session.execute(delete(StockMovement).where(StockMovement.product_id == product_id))
            session.execute(delete(OrderEvent).where(OrderEvent.order_id == order_id))
            session.execute(delete(OrderItem).where(OrderItem.id == item_id))
            session.execute(delete(Order).where(Order.id == order_id))
            session.execute(
                delete(ProductInventory).where(ProductInventory.product_id == product_id)
            )
            session.execute(delete(Product).where(Product.id == product_id))
            session.execute(delete(Conversation).where(Conversation.id == conv_id))
            session.execute(delete(Customer).where(Customer.id == customer_id))
            session.commit()
        engine.dispose()


def _parallel(call):
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=15)
        return call()

    with ThreadPoolExecutor(max_workers=2) as pool:
        return [future.result(timeout=30) for future in [pool.submit(run) for _ in range(2)]]


def test_parallel_confirm_then_cancel_commits_one_movement_per_transition(stock_case) -> None:
    engine, keys = stock_case
    user_id, _, _, product_id, order_id, item_id, _, _, order_uuid = keys

    def transition(status):
        def perform():
            with Session(engine) as session:
                user = session.get(User, user_id)
                assert user is not None
                result = update_order(session, user, order_uuid, data={"status": status})
                assert result is not None
                return result.status

        return perform

    assert _parallel(transition("confirmed")) == ["confirmed", "confirmed"]
    with Session(engine) as session:
        inventory = session.scalar(
            select(ProductInventory).where(ProductInventory.product_id == product_id)
        )
        assert inventory is not None and inventory.quantity_on_hand == 6
        assert (
            session.scalar(
                select(func.count())
                .select_from(StockMovement)
                .where(
                    StockMovement.order_item_id == item_id,
                    StockMovement.movement_type == "ORDER_OUT",
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OrderEvent)
                .where(OrderEvent.order_id == order_id, OrderEvent.event_type == "ORDER_CONFIRMED")
            )
            == 1
        )

    assert _parallel(transition("cancelled")) == ["cancelled", "cancelled"]
    with Session(engine) as session:
        inventory = session.scalar(
            select(ProductInventory).where(ProductInventory.product_id == product_id)
        )
        assert inventory is not None and inventory.quantity_on_hand == 10
        assert (
            session.scalar(
                select(func.count())
                .select_from(StockMovement)
                .where(
                    StockMovement.order_item_id == item_id,
                    StockMovement.movement_type == "ORDER_CANCEL_RESTORE",
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OrderEvent)
                .where(OrderEvent.order_id == order_id, OrderEvent.event_type == "ORDER_CANCELLED")
            )
            == 1
        )


def test_parallel_confirm_and_adjust_cannot_overdraw_or_partial_commit(stock_case) -> None:
    engine, keys = stock_case
    user_id, _, _, product_id, order_id, item_id, _, product_uuid, order_uuid = keys

    def confirm():
        with Session(engine) as session:
            user = session.get(User, user_id)
            assert user is not None
            try:
                update_order(session, user, order_uuid, data={"status": "confirmed"})
                return "confirmed"
            except InsufficientInventoryError:
                return "rejected"

    def adjust():
        with Session(engine) as session:
            user = session.get(User, user_id)
            assert user is not None
            try:
                adjust_product_inventory(
                    session,
                    user,
                    product_uuid,
                    quantity_delta=-7,
                    note="M4 race",
                    operation_id=uuid4(),
                )
                return "adjusted"
            except InsufficientInventoryError:
                return "rejected"

    barrier = Barrier(2)

    def race(fn):
        barrier.wait(timeout=15)
        return fn()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(race, fn) for fn in (confirm, adjust)]
        outcomes = {f.result(timeout=30) for f in futures}
    assert outcomes in ({"confirmed", "rejected"}, {"adjusted", "rejected"})
    with Session(engine) as session:
        inventory = session.scalar(
            select(ProductInventory).where(ProductInventory.product_id == product_id)
        )
        assert inventory is not None and inventory.quantity_on_hand in {3, 6}
        movements = session.scalars(
            select(StockMovement)
            .where(StockMovement.product_id == product_id)
            .order_by(StockMovement.id)
        ).all()
        assert sum(m.quantity_delta for m in movements) == inventory.quantity_on_hand
        assert sum(m.movement_type == "ORDER_OUT" for m in movements) == ("confirmed" in outcomes)
        assert sum(
            m.event_type == "ORDER_CONFIRMED"
            for m in session.scalars(select(OrderEvent).where(OrderEvent.order_id == order_id))
        ) == ("confirmed" in outcomes)
        assert all(m.order_item_id == item_id for m in movements if m.movement_type == "ORDER_OUT")


def test_deadlock_failure_rolls_back_event_balance_and_movement_then_retry(stock_case) -> None:
    engine, keys = stock_case
    user_id, _, _, product_id, order_id, item_id, _, _, order_uuid = keys
    injected = False

    def deadlock_once(_conn, _cursor, statement, parameters, _context, _executemany):
        nonlocal injected
        if not injected and statement.lstrip().lower().startswith("update product_inventories"):
            injected = True
            raise OperationalError(statement, parameters, Exception("simulated deadlock 1213"))

    event.listen(engine, "before_cursor_execute", deadlock_once)
    try:
        with Session(engine) as session:
            user = session.get(User, user_id)
            assert user is not None
            with pytest.raises(OperationalError):
                update_order(session, user, order_uuid, data={"status": "confirmed"})
    finally:
        event.remove(engine, "before_cursor_execute", deadlock_once)
    assert injected
    with Session(engine) as session:
        assert session.get(Order, order_id).status == "draft"
        inventory = session.scalar(
            select(ProductInventory).where(ProductInventory.product_id == product_id)
        )
        assert inventory is not None and inventory.quantity_on_hand == 10
        assert (
            session.scalar(
                select(func.count())
                .select_from(StockMovement)
                .where(
                    StockMovement.order_item_id == item_id,
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OrderEvent)
                .where(
                    OrderEvent.order_id == order_id,
                )
            )
            == 0
        )
    with Session(engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        assert update_order(session, user, order_uuid, data={"status": "confirmed"}) is not None
    with Session(engine) as session:
        inventory = session.scalar(
            select(ProductInventory).where(ProductInventory.product_id == product_id)
        )
        assert inventory is not None and inventory.quantity_on_hand == 6
        assert (
            session.scalar(
                select(func.count())
                .select_from(StockMovement)
                .where(
                    StockMovement.order_item_id == item_id,
                )
            )
            == 1
        )
