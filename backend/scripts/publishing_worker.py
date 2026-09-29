"""Dedicated scheduled publishing process: python -m scripts.publishing_worker."""

import logging
import time

from app.db.session import SessionLocal
from app.services.publishing.worker import run_once


def main() -> None:
    while True:
        try:
            with SessionLocal() as session:
                run_once(session)
        except Exception:
            logging.exception("Scheduled publishing worker iteration failed")
        time.sleep(10)


if __name__ == "__main__":
    main()
