"""Public, read-only workflow metadata."""

from fastapi import APIRouter

from app.services.workflow_policy import workflow_metadata_payload


router = APIRouter(prefix="/api/workflow", tags=["workflow"])


@router.get("/metadata")
def get_workflow_metadata():
    return workflow_metadata_payload()
