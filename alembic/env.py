# alembic/env.py (최종 수정본)
import sys
import os
from logging.config import fileConfig

from sqlalchemy import pool, engine_from_config
from sqlalchemy.engine import Connection

from alembic import context

from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "diag_project"))

from diag_project.models import *
from sqlmodel import SQLModel

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

# --- DATABASE_URL 처리 방식 변경: 항상 절대 경로 사용 ---
DB_FILE_NAME = "sql_app.db"

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(project_root, DB_FILE_NAME)

ALEMBIC_SYNC_DATABASE_URL = f"sqlite:///{DB_PATH}"

config.set_main_option("sqlalchemy.url", ALEMBIC_SYNC_DATABASE_URL)
# --- DATABASE_URL 처리 방식 변경 끝 ---


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True
            # render_as_batch=True
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()