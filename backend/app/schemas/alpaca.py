"""Pydantic request/response models for the Alpaca client layer.

These schemas are the only place plaintext credentials appear, and only on the
inbound ``CredentialSubmit`` model. No response model can serialize a secret.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CredentialSubmit(BaseModel):
    """Inbound payload carrying the plaintext Alpaca API Key and Secret."""

    api_key: str = Field(min_length=1)
    secret: str = Field(min_length=1)

    @field_validator("api_key", "secret")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field is required")  # R1.7
        return v


class CredentialMetadata(BaseModel):
    """Non-sensitive credential metadata. Never carries a secret (R1.3, R6.1)."""

    exists: bool
    key_id_last4: str | None = None       # last 4 of API Key ID (R6.1)
    validation_status: str | None = None  # e.g. "valid" (R6.1)
    updated_at: datetime | None = None
    # No secret field anywhere (R1.3)


class DeletionResult(BaseModel):
    """Outcome of a credential deletion request (R6.3/R6.4)."""

    deleted: bool
    detail: str  # e.g. "credentials removed" or "no credentials to delete"


class AccountStatus(BaseModel):
    """Paper account status and balance returned to the frontend (R3.1, R5.3)."""

    cash: Decimal            # numeric monetary value (R3.1)
    buying_power: Decimal    # numeric monetary value (R3.1)
    status: str              # account status reported by Alpaca (R3.1)
    mode: Literal["paper"] = "paper"  # Active_Mode (R5.3)
