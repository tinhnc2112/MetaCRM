"""Add a credential-free carrier fixture to the guarded disposable E2E database."""

from app.models.auth import User
from app.models.carriers import CarrierAccount
from app.models.facebook import FacebookPage
from scripts.e2e_harness import e2e_database_url
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def main() -> None:
    target = e2e_database_url()  # Requires METACRM_E2E=true and an _e2e database.
    if target.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("M0 fixtures require a loopback disposable MySQL instance")
    engine = create_engine(target)
    try:
        with Session(engine) as session:
            user = session.scalar(select(User).where(User.username == "e2e.operator"))
            page = session.scalar(select(FacebookPage).where(FacebookPage.page_id == "e2e-page-a"))
            if user is None or page is None:
                raise SystemExit("Run the guarded E2E prepare command before M0 seeding")
            existing = session.scalar(
                select(CarrierAccount).where(CarrierAccount.facebook_page_id == page.id)
            )
            if existing:
                return
            session.add(
                CarrierAccount(
                    facebook_page_id=page.id,
                    provider_code="manual",
                    display_name="M0 disposable manual carrier",
                    status="active",
                    configuration={},
                    created_by_id=user.id,
                )
            )
            session.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
