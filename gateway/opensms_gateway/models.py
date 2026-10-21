import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


DEVICE_ID_RE = re.compile(r"^osms-[A-Za-z0-9_-]{3,64}$")
PAIRING_CODE_RE = re.compile(r"^\d{6}$")
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


class PairDeviceRequest(BaseModel):
    pairing_code: str
    device_id: str
    name: str = Field(min_length=1, max_length=80)

    @field_validator("pairing_code")
    @classmethod
    def pairing_code_valid(cls, value: str) -> str:
        if not PAIRING_CODE_RE.fullmatch(value):
            raise ValueError("invalid pairing code")
        return value

    @field_validator("device_id")
    @classmethod
    def device_id_valid(cls, value: str) -> str:
        if not DEVICE_ID_RE.fullmatch(value):
            raise ValueError("invalid device id")
        return value


class MessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    device_id: str
    to_number: str = Field(alias="to")
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("device_id")
    @classmethod
    def device_id_valid(cls, value: str) -> str:
        if not DEVICE_ID_RE.fullmatch(value):
            raise ValueError("invalid device id")
        return value

    @field_validator("to_number")
    @classmethod
    def phone_valid(cls, value: str) -> str:
        if not PHONE_RE.fullmatch(value):
            raise ValueError("invalid destination")
        return value


class PairDeviceResponse(BaseModel):
    device_id: str
    device_credential: str


class MessageAccepted(BaseModel):
    message_id: str
    state: str


class MessageStatus(BaseModel):
    message_id: str
    device_id: str
    to: str
    state: str
    created_at: float
    updated_at: float
    acknowledged_at: Optional[float] = None
    completed_at: Optional[float] = None
    error_code: Optional[str] = None
    dispatch_attempts: int
