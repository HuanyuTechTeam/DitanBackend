"""Organization isolation and immutable upload provenance.

Revision ID: 003_org_medical_upload
Revises: 002_add_apkio_doctor_bindings
"""

from alembic import op
import sqlalchemy as sa

revision = "003_org_medical_upload"
down_revision = "002_add_apkio_doctor_bindings"
branch_labels = None
depends_on = None

SCOPED_TABLES = (
    "patients",
    "patient_medical_records",
    "pre_diagnosis_records",
    "chat_conversations",
)
UNIQUE_KEYS = (
    ("patients", "phone", "uq_patients_org_phone"),
    ("patient_medical_records", "uuid", "uq_medical_records_org_uuid"),
    ("pre_diagnosis_records", "uuid", "uq_pre_diagnosis_org_uuid"),
)
PARENTS = (
    (
        "patient_medical_records",
        "patient_id",
        "patients",
        "patient_id",
        "fk_medical_records_org_patient",
    ),
    (
        "pre_diagnosis_records",
        "record_id",
        "patient_medical_records",
        "record_id",
        "fk_pre_diagnosis_org_record",
    ),
    (
        "chat_conversations",
        "patient_id",
        "patients",
        "patient_id",
        "fk_chat_org_patient",
    ),
)
AUDIT_COLUMNS = (
    "upload_digest",
    "upload_user_id",
    "upload_device_id",
    "upload_client_session_id",
    "upload_request_id",
)


def _drop_global_uniqueness(table: str, column: str) -> None:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints(table):
        if constraint["column_names"] == [column]:
            assert constraint["name"] is not None
            op.drop_constraint(constraint["name"], table, type_="unique")
    for index in sa.inspect(op.get_bind()).get_indexes(table):
        if index["column_names"] == [column] and index["unique"]:
            assert index["name"] is not None
            op.drop_index(index["name"], table_name=table)
    index_name = f"ix_{table}_{column}"
    if not any(
        i["name"] == index_name for i in sa.inspect(op.get_bind()).get_indexes(table)
    ):
        op.create_index(index_name, table, [column], unique=False)


def upgrade() -> None:
    for table in SCOPED_TABLES:
        op.add_column(
            table,
            sa.Column("org_id", sa.Text(), nullable=False, server_default="__legacy__"),
        )
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    for table, column, name in UNIQUE_KEYS:
        _drop_global_uniqueness(table, column)
        op.create_unique_constraint(name, table, ["org_id", column])
    op.create_unique_constraint(
        "uq_patients_org_id", "patients", ["org_id", "patient_id"]
    )
    op.create_unique_constraint(
        "uq_medical_records_org_id", "patient_medical_records", ["org_id", "record_id"]
    )
    for table, column, parent, parent_column, name in PARENTS:
        for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(table):
            if foreign_key["constrained_columns"] == [column]:
                assert foreign_key["name"] is not None
                op.drop_constraint(foreign_key["name"], table, type_="foreignkey")
        op.create_foreign_key(
            name, table, parent, ["org_id", column], ["org_id", parent_column]
        )
    for column in AUDIT_COLUMNS:
        column_type = (
            sa.String(64)
            if column == "upload_digest"
            else (sa.String(36) if column == "upload_request_id" else sa.Text())
        )
        op.add_column(
            "patient_medical_records", sa.Column(column, column_type, nullable=True)
        )
    for table in SCOPED_TABLES:
        op.alter_column(table, "org_id", server_default=None)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text(
                "LOCK TABLE patients, patient_medical_records, pre_diagnosis_records, "
                "chat_conversations IN ACCESS EXCLUSIVE MODE"
            )
        )
    for table, column, _ in UNIQUE_KEYS:
        duplicate = connection.execute(
            sa.text(
                f'SELECT 1 FROM "{table}" GROUP BY "{column}" HAVING count(*) > 1 LIMIT 1'
            )
        ).first()
        if duplicate is not None:
            raise RuntimeError(
                f"Unsafe downgrade refused: {table}.{column} has cross-organization duplicates; "
                "global uniqueness cannot be restored without losing data. No rows were changed."
            )
    for table, column, parent, parent_column, name in PARENTS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            f"{table}_{column}_fkey", table, parent, [column], [parent_column]
        )
    op.drop_constraint(
        "uq_medical_records_org_id", "patient_medical_records", type_="unique"
    )
    op.drop_constraint("uq_patients_org_id", "patients", type_="unique")
    for table, column, name in UNIQUE_KEYS:
        op.drop_constraint(name, table, type_="unique")
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.create_index(f"ix_{table}_{column}", table, [column], unique=True)
    for column in reversed(AUDIT_COLUMNS):
        op.drop_column("patient_medical_records", column)
    for table in reversed(SCOPED_TABLES):
        op.drop_index(f"ix_{table}_org_id", table_name=table)
        op.drop_column(table, "org_id")
