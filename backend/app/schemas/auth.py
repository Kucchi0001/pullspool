"""Authentication request/response models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    must_change_password: bool
    created_at: str
    last_login_at: str | None = None


class ServerOut(BaseModel):
    version: str
    build: str
    started_at: str
    uptime_seconds: int


class MeResponse(BaseModel):
    user: UserOut
    server: ServerOut


class LoginResponse(BaseModel):
    user: UserOut


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class ChangeUsernameRequest(BaseModel):
    new_username: str = Field(min_length=3, max_length=32)
    current_password: str = Field(min_length=1, max_length=256)
