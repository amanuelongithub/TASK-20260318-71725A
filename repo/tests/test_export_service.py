from app.services.export_service import _mask_value, build_export_plan


def test_mask_full_name() -> None:
    assert _mask_value("full_name", "Alice") == "A****"


def test_mask_email() -> None:
    assert _mask_value("email", "alice@example.com") == "a***@example.com"


def test_mask_username() -> None:
    assert _mask_value("username", "operator1") == "op***"


def test_non_admin_export_plan_forces_masking_and_no_email() -> None:
    fields, desensitize = build_export_plan(["username", "email", "org_id"], "reviewer", False)
    assert fields == ["username", "org_id"]
    assert desensitize is True


def test_admin_export_plan_allows_email_and_unmasked() -> None:
    fields, desensitize = build_export_plan(["username", "email"], "administrator", False)
    assert fields == ["username", "email"]
    assert desensitize is False
