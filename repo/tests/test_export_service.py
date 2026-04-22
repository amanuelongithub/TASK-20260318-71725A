from app.services.export_service import _mask_column, build_export_plan


def test_mask_full_name() -> None:
    assert _mask_column("full_name", "Alice") == "A****"


def test_mask_email() -> None:
    assert _mask_column("email", "alice@example.com") == "a***@example.com"


def test_mask_username() -> None:
    assert _mask_column("username", "operator1") == "op***"


def test_non_admin_export_plan_forces_masking_and_no_email() -> None:
    # UPDATED: Added 'users' entity_type to match 4-arg signature
    fields, desensitize = build_export_plan("users", ["username", "email", "org_id"], "reviewer", False)
    assert fields == ["username", "org_id"]
    assert desensitize is True


def test_admin_export_plan_allows_email_and_unmasked() -> None:
    # UPDATED: Added 'users' entity_type to match 4-arg signature
    fields, desensitize = build_export_plan("users", ["username", "email"], "administrator", False)
    assert fields == ["username", "email"]
    assert desensitize is False
