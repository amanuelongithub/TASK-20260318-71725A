from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    org_code: str
    username: str
    password: str


class RegisterRequest(BaseModel):
    org_code: str = Field(min_length=2, max_length=64)
    org_name: str = Field(min_length=2, max_length=255)
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=64)
    full_name: str | None = None
    email: str | None = None
    invitation_token: str | None = None # Required if joining existing org

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not (any(ch.isalpha() for ch in value) and any(ch.isdigit() for ch in value)):
            raise ValueError("Password must include letters and numbers")
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PasswordResetRequest(BaseModel):
    org_code: str
    username: str


class PasswordResetConfirm(BaseModel):
    org_code: str
    token: str
    new_password: str = Field(min_length=8, max_length=64)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not (any(ch.isalpha() for ch in value) and any(ch.isdigit() for ch in value)):
            raise ValueError("Password must include letters and numbers")
        return value


class JoinOrganizationRequest(BaseModel):
    org_code: str


class AddMemberRequest(BaseModel):
    username: str
    role: str = "general_user"


class InvitationRequest(BaseModel):
    email_or_username: str
    role: str = "general_user"


class InvitationResponse(BaseModel):
    invitation_id: int
    token: str
    expires_at: str


class JoinInvitationRequest(BaseModel):
    token: str
