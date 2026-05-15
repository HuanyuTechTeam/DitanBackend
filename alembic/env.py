"""Alembic 环境配置 - 支持异步 SQLAlchemy"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# 导入项目配置和模型
from app.core.config import get_settings
from app.core.database import Base

# 导入所有模型以确保它们被注册到 Base.metadata
from app.models import (  # noqa: F401
    Gender,
    DiagnosisType,
    MedicalRecordStatus,
    Doctor,
    Patient,
    PatientMedicalRecord,
    PreDiagnosisRecord,
    SanzhenAnalysisResult,
    DiagnosisRecord,
    AIDiagnosisRecord,
    DoctorDiagnosisRecord,
    ChatConversation,
    ChatMessage,
)

# Alembic Config 对象
config = context.config

# 设置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置 target_metadata 用于 autogenerate
target_metadata = Base.metadata

# 获取数据库 URL
settings = get_settings()


def get_url() -> str:
    """获取数据库连接 URL"""
    return settings.database_url


def run_migrations_offline() -> None:
    """以离线模式运行迁移

    这种模式下，只生成 SQL 脚本，不实际执行。
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """执行迁移"""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """以异步模式运行迁移"""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """以在线模式运行迁移"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
