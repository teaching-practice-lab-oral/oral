from fastapi import APIRouter

from .users import router as users_router
from .assignments import router as assignments_router
from .exports import router as exports_router
from .audit import router as audit_router
from .rubrics import router as rubrics_router
from .proctoring import router as proctoring_router
from .grading import router as grading_router
from .media import router as media_router
from .result_delivery import router as result_delivery_router

router = APIRouter()
router.include_router(users_router)
router.include_router(assignments_router)
router.include_router(exports_router)
router.include_router(audit_router)
router.include_router(rubrics_router)
router.include_router(proctoring_router)
router.include_router(grading_router)
router.include_router(media_router)
router.include_router(result_delivery_router)
