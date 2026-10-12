"""create orders and outbox_tasks tables

Revision ID: 0001_orders_outbox
Revises: 
Create Date: 2026-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_orders_outbox"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Создание ENUM типов данных
    order_status_enum = postgresql.ENUM(
        "PENDING",
        "PAID",
        "PUBLISHING",
        "PUBLISHED",
        "REFUND_REQUIRED",
        "REFUNDED",
        "CANCELLED",
        name="order_status_enum",
        create_type=False,
    )
    order_status_enum.create(op.get_bind(), checkfirst=True)

    outbox_task_type_enum = postgresql.ENUM(
        "PUBLISH_POST",
        "EXECUTE_PAYMENT_REFUND",
        name="outbox_task_type_enum",
        create_type=False,
    )
    outbox_task_type_enum.create(op.get_bind(), checkfirst=True)

    # 2. Создание таблицы orders
    op.create_table(
        "orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("target_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            order_status_enum,
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("content_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("contact_info", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payment_id", sa.String(length=64), nullable=True),
        sa.Column("payment_url", sa.Text(), nullable=True),
        sa.Column("published_message_id", sa.BigInteger(), nullable=True),
        sa.Column("refund_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # Индексы для таблицы orders
    op.create_index("idx_orders_user_id", "orders", ["user_id"], unique=False)
    op.create_index("idx_orders_status", "orders", ["status"], unique=False)
    op.create_index(
        "idx_orders_payment_id",
        "orders",
        ["payment_id"],
        unique=True,
        postgresql_where=sa.text("payment_id IS NOT NULL"),
    )

    # 3. Создание таблицы outbox_tasks
    op.create_table(
        "outbox_tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("task_type", outbox_task_type_enum, nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "execute_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processed", sa.Boolean(), server_default="FALSE", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # Частичный индекс для эффективной выборки воркером (outbox poller)
    op.create_index(
        "idx_outbox_tasks_poll",
        "outbox_tasks",
        ["execute_after"],
        unique=False,
        postgresql_where=sa.text("processed = FALSE AND locked_until IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_outbox_tasks_poll", table_name="outbox_tasks")
    op.drop_table("outbox_tasks")

    op.drop_index("idx_orders_payment_id", table_name="orders")
    op.drop_index("idx_orders_status", table_name="orders")
    op.drop_index("idx_orders_user_id", table_name="orders")
    op.drop_table("orders")

    sa.Enum(name="outbox_task_type_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="order_status_enum").drop(op.get_bind(), checkfirst=True)