from fastapi import APIRouter

from .core import router as core_router
from .feedback import router as feedback_router
from .shadowing import router as shadowing_router
from .roleplay import router as roleplay_router
from .audio import router as audio_router
from .job_profiles import router as job_profiles_router
from .records import router as records_router
from .reflections import router as reflections_router
from .proctoring import router as proctoring_router

router = APIRouter()
router.include_router(core_router)
router.include_router(feedback_router)
router.include_router(shadowing_router)
router.include_router(roleplay_router)
router.include_router(audio_router)
router.include_router(job_profiles_router)
router.include_router(records_router)
router.include_router(reflections_router)
router.include_router(proctoring_router)

__all__ = ["router"]
