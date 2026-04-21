import pytest

from app.schemas.auth import RegisterRequest


def test_password_requires_letters_and_numbers() -> None:
    with pytest.raises(ValueError):
        RegisterRequest(org_code="o1", org_name="Org", username="u1", password="abcdefgh")
