"""Alembic environment configuration."""

from logging.config import fileConfig

from alembic import context
from alembic.ddl.mysql import MySQLImpl
from sqlalchemy import Column
from sqlalchemy import engine_from_config, pool
from sqlalchemy import inspect
from sqlalchemy import MetaData
from sqlalchemy import PrimaryKeyConstraint
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import text

from app.core.config import get_settings
from app.db.base import Base
import app.models  # noqa: F401 - registers models with Base metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
ALEMBIC_VERSION_NUM_LENGTH = 255


def _mysql_version_table_impl(
    self,
    *,
    version_table: str,
    version_table_schema: str | None,
    version_table_pk: bool,
    **kw,
):
    version_table_def = Table(
        version_table,
        MetaData(),
        Column("version_num", String(ALEMBIC_VERSION_NUM_LENGTH), nullable=False),
        schema=version_table_schema,
    )
    if version_table_pk:
        version_table_def.append_constraint(
            PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc")
        )
    return version_table_def


def _ensure_version_table_width(engine) -> None:
    if engine.dialect.name != "mysql":
        return

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as preflight_connection:
        inspector = inspect(preflight_connection)
        if not inspector.has_table("alembic_version"):
            return

        version_column = next(
            (
                column
                for column in inspector.get_columns("alembic_version")
                if column["name"] == "version_num"
            ),
            None,
        )
        if version_column is None:
            return

        current_length = getattr(version_column["type"], "length", None)
        if current_length is not None and current_length >= ALEMBIC_VERSION_NUM_LENGTH:
            return

        preflight_connection.execute(
            text(
                "ALTER TABLE alembic_version "
                "DROP PRIMARY KEY, "
                f"MODIFY version_num VARCHAR({ALEMBIC_VERSION_NUM_LENGTH}) NOT NULL, "
                "ADD PRIMARY KEY (version_num)"
            )
        )


MySQLImpl.version_table_impl = _mysql_version_table_impl  # type: ignore[assignment]


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    _ensure_version_table_width(connectable)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
