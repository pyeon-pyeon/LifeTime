"""Admin-only changes. Supabase Auth validates the token; users cannot set app_metadata."""

from uuid import UUID
from typing import Literal, get_args
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .facilities import get_facility_client
from scripts.import_facilities import build_rpc_record, RecordError
from facility_validation import FacilityRecord, normalize_facility_record

router = APIRouter(prefix="/api/admin", tags=["administration"])
bearer = HTTPBearer(auto_error=False)
AdminAction = Literal["approve", "reject", "restore"]


def authenticated_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                        client=Depends(get_facility_client)):
    if credentials is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        response = client.auth.get_user(credentials.credentials)
        user = response.user if response else None
    except Exception:
        raise HTTPException(401, "Invalid authentication") from None
    if user is None:
        raise HTTPException(401, "Invalid authentication")
    if not isinstance(user.app_metadata, dict) or user.app_metadata.get("role") != "admin":
        raise HTTPException(403, "Administrator required")
    return str(user.id)


class ChangeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    record: FacilityRecord


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def normalized_reason(cls, value):
        if not isinstance(value, str):
            raise ValueError("reason must be a string")
        value = value.strip()
        if not 1 <= len(value) <= 500:
            raise ValueError("reason must contain 1 to 500 characters")
        return value


def execute_change(client, name, params):
    try:
        return client.rpc(name, params).execute().data
    except Exception as error:
        code = str(getattr(error, "code", ""))
        if code == "40001" or code == "23505":
            raise HTTPException(409, "Change conflicts with current state") from None
        if code == "P0002":
            raise HTTPException(404, "Change or facility not found") from None
        if code == "42501":
            raise HTTPException(403, "Administrator required") from None
        if code in {"22023", "23514", "22P02", "22007", "22008"}:
            raise HTTPException(422, "Invalid facility change") from None
        raise HTTPException(503, "Facility change service unavailable") from None


@router.post("/facilities/{facility_id}/changes")
def propose_change(facility_id: UUID, request: ChangeProposal,
                   actor=Depends(authenticated_admin), client=Depends(get_facility_client)):
    try:
        normalized_record = normalize_facility_record(request.record.model_dump(mode="json"))
        normalized = {
            "facility": {key: value for key, value in normalized_record.items() if key != "access_hours"},
            "access_hours": normalized_record["access_hours"],
        }
        record = build_rpc_record(normalized)
    except (RecordError, ValueError, TypeError):
        raise HTTPException(422, "Invalid facility change") from None
    return execute_change(client, "propose_facility_change", {
        "p_facility_id": str(facility_id), "p_record": record,
        "p_request_id": str(request.request_id), "p_actor_id": actor})


@router.post("/facility-changes/{change_id}/{action}")
def decide_change(change_id: UUID, action: str, request: DecisionRequest,
                  actor=Depends(authenticated_admin), client=Depends(get_facility_client)):
    if action not in get_args(AdminAction):
        raise HTTPException(404, "Unknown change action")
    return execute_change(client, "decide_facility_change", {
        "p_change_id": str(change_id), "p_action": action,
        "p_request_id": str(request.request_id), "p_actor_id": actor,
        "p_reason": request.reason})


@router.get("/facilities/{facility_id}/history")
def change_history(facility_id: UUID, limit: int = Query(50, ge=1, le=100),
                   actor=Depends(authenticated_admin), client=Depends(get_facility_client)):
    return execute_change(client, "facility_change_history", {
        "p_facility_id": str(facility_id), "p_actor_id": actor, "p_limit": limit})
