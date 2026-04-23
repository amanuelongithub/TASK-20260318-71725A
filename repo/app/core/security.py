import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(settings.aes_key.encode("utf-8")[:32].ljust(32, b"0"))
    return Fernet(key)


def encrypt_field(value: str) -> bytes:
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt_field(value: bytes) -> str:
    return _fernet().decrypt(value).decode("utf-8")


def deterministic_hash(value: str | None) -> str:
    if value is None:
        return ""
    import hmac
    # Use HMAC with the secret key for deterministic but keyed hashing
    return hmac.new(settings.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str, org_id: int, roles: list[str], expires_delta: timedelta | None = None) -> str:
    import uuid
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload: dict[str, Any] = {
        "sub": subject,
        "org_id": org_id,
        "roles": roles,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc


def mask_value(field: str, value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if field in {"full_name", "patient_name", "doctor_name"}:
        return text[0] + "*" * (len(text) - 1) if len(text) > 1 else "*"
    if field == "email":
        if "@" not in text:
            return "***"
        name, domain = text.split("@", 1)
        return (name[:1] + "***@" + domain) if name else "***@" + domain
    if field == "username":
        return text[:2] + "***" if len(text) > 2 else "***"
    if field in {"phone_number", "id_card_num", "license_number", "patient_number", "appointment_number", "expense_number"}:
        return text[:4] + "*" * (len(text) - 4) if len(text) > 4 else "*" * len(text)
    if field == "notes" or field == "comment":
        return "MATCHED_SENSITIVE_CONTENT_REDACTED"
    return text


def desensitize_response(data: Any, role_name: Any) -> Any:
    from app.models.entities import RoleType
    # ADMINs see everything cleartext in the API
    # Some roles might be passed as string values or Enum members
    role_str = str(role_name.value if hasattr(role_name, "value") else role_name)
    if role_str == RoleType.ADMIN.value:
        return data
    
    sensitive_fields = {
        "full_name", "email", "username", "phone_number", "id_card_num", 
        "license_number", "patient_number", "appointment_number", "expense_number",
        "notes", "comment", "email_encrypted", "id_card_num_encrypted", "phone_number_encrypted"
    }
    
    if data is None:
        return None

    if isinstance(data, list):
        return [desensitize_response(item, role_name) for item in data]
    
    # Handle Pydantic models (v1/v2)
    if hasattr(data, "model_dump"): # Pydantic v2
        data_dict = data.model_dump()
        return desensitize_response(data_dict, role_name)
    if hasattr(data, "dict"): # Pydantic v1
        data_dict = data.dict()
        return desensitize_response(data_dict, role_name)
    if hasattr(data, "__dict__"):
        # SQLAlchemy models or other objects. 
        # Start with __dict__ to get columns/state.
        obj_dict = {k: v for k, v in data.__dict__.items() if not k.startswith("_")}
        
        # Explicitly add sensitive properties that might be @property (unindexed by __dict__)
        for field in sensitive_fields:
            if field not in obj_dict and hasattr(data, field):
                obj_dict[field] = getattr(data, field)
                
        return desensitize_response(obj_dict, role_name)

    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            if k in sensitive_fields:
                new_dict[k] = mask_value(k, v)
            else:
                new_dict[k] = desensitize_response(v, role_name)
        return new_dict
    
    return data

