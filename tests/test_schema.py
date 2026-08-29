from sqlalchemy import inspect

from app.db.session import engine


def test_user_and_ownership_constraints_exist_in_postgresql() -> None:
    inspector = inspect(engine)
    assert "users" in inspector.get_table_names()

    user_columns = {column["name"]: column for column in inspector.get_columns("users")}
    assert user_columns["email"]["nullable"] is False
    assert user_columns["password_hash"]["nullable"] is False

    unique_constraints = inspector.get_unique_constraints("users")
    assert any(constraint["column_names"] == ["email"] for constraint in unique_constraints)
    check_constraints = inspector.get_check_constraints("users")
    assert any(constraint["name"] == "email_normalized" for constraint in check_constraints)

    knowledge_base_columns = {
        column["name"]: column for column in inspector.get_columns("knowledge_bases")
    }
    assert knowledge_base_columns["owner_id"]["nullable"] is False

    foreign_keys = inspector.get_foreign_keys("knowledge_bases")
    ownership_foreign_key = next(
        foreign_key
        for foreign_key in foreign_keys
        if foreign_key["constrained_columns"] == ["owner_id"]
    )
    assert ownership_foreign_key["referred_table"] == "users"
    assert ownership_foreign_key["referred_columns"] == ["id"]
    options = ownership_foreign_key["options"]
    assert options["ondelete"] == "RESTRICT"

    indexes = inspector.get_indexes("knowledge_bases")
    assert any(index["column_names"] == ["owner_id"] for index in indexes)


def test_document_constraints_and_listing_index_exist_in_postgresql() -> None:
    inspector = inspect(engine)
    assert "documents" in inspector.get_table_names()

    columns = {column["name"]: column for column in inspector.get_columns("documents")}
    assert columns["knowledge_base_id"]["nullable"] is False
    assert columns["original_filename"]["nullable"] is False
    assert columns["content_type"]["nullable"] is False
    assert columns["size_bytes"]["nullable"] is False
    assert columns["checksum_sha256"]["nullable"] is False
    assert columns["storage_key"]["nullable"] is False

    foreign_key = next(
        item
        for item in inspector.get_foreign_keys("documents")
        if item["constrained_columns"] == ["knowledge_base_id"]
    )
    assert foreign_key["referred_table"] == "knowledge_bases"
    assert foreign_key["referred_columns"] == ["id"]
    assert foreign_key["options"]["ondelete"] == "CASCADE"

    unique_constraints = inspector.get_unique_constraints("documents")
    assert any(item["column_names"] == ["storage_key"] for item in unique_constraints)
    indexes = inspector.get_indexes("documents")
    assert any(item["column_names"] == ["knowledge_base_id"] for item in indexes)


def test_ingestion_job_constraints_and_document_relationship_exist_in_postgresql() -> None:
    inspector = inspect(engine)
    assert "ingestion_jobs" in inspector.get_table_names()

    columns = {column["name"]: column for column in inspector.get_columns("ingestion_jobs")}
    assert columns["document_id"]["nullable"] is False
    assert columns["status"]["nullable"] is False
    assert columns["attempt_count"]["nullable"] is False

    foreign_key = next(
        item
        for item in inspector.get_foreign_keys("ingestion_jobs")
        if item["constrained_columns"] == ["document_id"]
    )
    assert foreign_key["referred_table"] == "documents"
    assert foreign_key["referred_columns"] == ["id"]
    assert foreign_key["options"]["ondelete"] == "CASCADE"

    unique_constraints = inspector.get_unique_constraints("ingestion_jobs")
    assert any(item["column_names"] == ["document_id"] for item in unique_constraints)
    constraint_names = {
        constraint["name"] for constraint in inspector.get_check_constraints("ingestion_jobs")
    }
    assert {
        "attempt_count_nonnegative",
        "completion_matches_status",
        "failure_code_length",
        "failure_code_matches_status",
        "status_valid",
    } <= constraint_names
