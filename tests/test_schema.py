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
