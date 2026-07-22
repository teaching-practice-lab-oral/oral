"""Generation of versioned shadowing model-audio assets."""

import logging
from uuid import uuid4

from app.services import storage, tts, tts_alignment, worker_client
from app.services.submission_assets import delete_uncommitted_object


logger = logging.getLogger(__name__)


async def generate_asset(
    answers: list,
    student_id: str,
    submission_id: int,
    question_index: int,
    user_id: int | None = None,
) -> dict | None:
    """Generate, align, and upload a uniquely named model-audio asset."""
    if question_index < 0 or question_index >= len(answers):
        return None
    answer = answers[question_index]
    spoken_text = tts_alignment.build_shadowing_tts_text(answer, question_index)
    key = (
        f"audio/{student_id}/{submission_id}/"
        f"shadowing_tts_answer_q{question_index}_{uuid4().hex}.mp3"
    )
    upload_started = False
    try:
        with worker_client.routing_context(
            user_id=user_id,
            student_id=student_id,
            submission_id=submission_id,
            stage=5,
            operation="shadowing_tts",
        ):
            audio_bytes = await tts.generate_speech(spoken_text, tts.SpeechProfile.SHADOWING)
        timing = await tts_alignment.create_tts_timing(
            audio_bytes,
            spoken_text,
            str(answer.get("text", "")),
        )
        upload_started = True
        await storage.upload_file_async(key, audio_bytes, "audio/mpeg")
        return {"key": key, "timing": timing}
    except Exception as exc:
        logger.warning(
            "Shadowing TTS generation failed for submission %s question %s: %s",
            submission_id,
            question_index,
            exc,
        )
        if upload_started:
            await delete_uncommitted_object(key)
        return None
