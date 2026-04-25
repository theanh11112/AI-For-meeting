# backend/app/main.py
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
from typing import Optional, Dict, Any, List
import logging
from datetime import datetime
import os
from dotenv import load_dotenv
import asyncio
import json
from threading import Lock
import uuid
import tempfile
import sys
import gc
import wave
import io
import numpy as np

# Thêm thư mục backend vào Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ==================== IMPORT CUSTOM MODULES ====================
from .db import DatabaseManager
from .Process_transcrip import (
    TranscriptProcessor,
    MeetingSummarizer,
    SummaryResponse,
    SYSTEM_PROMPT,
    Agent,
    RunContext,
    Section,
    Block,
)
from .translation import TranslationService
from .whisperx_service import WhisperXService
from .models.user_map import meeting_directory
from .services.speaker_mapper import (
    map_speakers_to_real_names,
    get_all_speakers,
    get_participant_context,
)

# Load environment variables
load_dotenv()

# Configure logger with line numbers and function names
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create console handler with formatting
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)

# Create formatter with line numbers and function names
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d - %(funcName)s()] - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
console_handler.setFormatter(formatter)

# Add handler to logger if not already added
if not logger.handlers:
    logger.addHandler(console_handler)

app = FastAPI(
    title="Meeting Summarizer API",
    description="API for processing and summarizing meeting transcripts",
    version="2.0.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3118",
        "http://localhost:*",
        "tauri://localhost",
        "tauri://*",
        "app://localhost",
        "app://*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600,
)


class TranscriptRequest(BaseModel):
    text: str
    model: str
    model_name: str
    chunk_size: Optional[int] = 5000
    overlap: Optional[int] = 1000


class TranscriptResponse(BaseModel):
    message: str
    num_chunks: int
    data: Dict[str, Any]


class MappingRequest(BaseModel):
    speaker_id: str
    name: str
    email: str


class LocalDiarizeRequest(BaseModel):
    file_path: str


class SummaryProcessor:
    def __init__(self):
        try:
            self.db = DatabaseManager()
            self._lock = Lock()

            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                logger.error("ANTHROPIC_API_KEY environment variable not set")
                raise ValueError("ANTHROPIC_API_KEY environment variable not set")

            logger.info("Initializing SummaryProcessor components")
            self.transcript_processor = TranscriptProcessor()
            self.summarizer = MeetingSummarizer(api_key)
            self.agent = Agent(model=self.summarizer.model, system_prompt=SYSTEM_PROMPT)
            self.collection = None
            self.final_summary_result = None
            logger.info("SummaryProcessor initialized successfully")
        except Exception as e:
            logger.error(
                f"Failed to initialize SummaryProcessor: {str(e)}", exc_info=True
            )
            raise

    async def process_transcript(
        self,
        text: str,
        model: str,
        model_name: str,
        chunk_size: int = 5000,
        overlap: int = 1000,
        speaker_context: str = None,
    ) -> tuple:
        try:
            if not text:
                raise ValueError("Empty transcript text provided")

            if chunk_size <= 0:
                raise ValueError("chunk_size must be positive")
            if overlap < 0:
                raise ValueError("overlap must be non-negative")
            if overlap >= chunk_size:
                overlap = chunk_size - 1

            step_size = chunk_size - overlap
            if step_size <= 0:
                chunk_size = overlap + 1

            logger.info("Initializing ChromaDB collection")
            self.transcript_processor.initialize_collection()
            self.collection = self.transcript_processor.collection

            if not self.collection:
                raise ValueError("Failed to initialize ChromaDB collection")

            logger.info(
                f"Processing transcript of length {len(text)} with chunk_size={chunk_size}, overlap={overlap}"
            )
            num_chunks, all_json_data = (
                await self.transcript_processor.process_transcript(
                    text=text,
                    model=model,
                    model_name=model_name,
                    chunk_size=chunk_size,
                    overlap=overlap,
                    speaker_context=speaker_context,
                )
            )
            logger.info(f"Successfully processed transcript into {num_chunks} chunks")

            return num_chunks, all_json_data
        except Exception as e:
            logger.error(f"Error processing transcript: {str(e)}", exc_info=True)
            raise

    def cleanup(self):
        try:
            logger.info("Cleaning up resources")
            self.transcript_processor.cleanup()
            logger.info("Cleanup completed successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}", exc_info=True)


# Initialize processor
processor = SummaryProcessor()

# ==================== KHỞI TẠO SERVICES ====================
translation_service = TranslationService()

# ==================== WHISPERX CACHE MANAGEMENT ====================
_whisperx_cache = {"instance": None, "last_used": None, "loading": False}
WHISPERX_IDLE_TIMEOUT = 300


async def get_whisperx_service():
    """Lấy WhisperX service từ cache hoặc tạo mới"""
    global _whisperx_cache

    now = datetime.now()

    if _whisperx_cache["instance"] is not None:
        if (
            _whisperx_cache["last_used"]
            and (now - _whisperx_cache["last_used"]).seconds > WHISPERX_IDLE_TIMEOUT
        ):
            logger.info("⏰ WhisperX idle timeout, unloading...")
            await unload_whisperx()

    if _whisperx_cache["instance"] is None and not _whisperx_cache["loading"]:
        _whisperx_cache["loading"] = True
        try:
            logger.info("🚀 Loading WhisperX service (cached for future use)...")
            _whisperx_cache["instance"] = WhisperXService()
            _whisperx_cache["last_used"] = now
            logger.info("✅ WhisperX service loaded and cached")
        except Exception as e:
            logger.error(f"❌ Failed to load WhisperX: {e}")
            _whisperx_cache["instance"] = None
        finally:
            _whisperx_cache["loading"] = False

    if _whisperx_cache["instance"]:
        _whisperx_cache["last_used"] = now

    return _whisperx_cache["instance"]


async def unload_whisperx():
    """Giải phóng WhisperX service khỏi RAM"""
    global _whisperx_cache

    if _whisperx_cache["instance"]:
        logger.info("♻️ Unloading WhisperX service from RAM...")
        del _whisperx_cache["instance"]
        _whisperx_cache["instance"] = None
        _whisperx_cache["last_used"] = None
        gc.collect()
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except ImportError:
            pass
        logger.info("✅ WhisperX unloaded successfully")


# ==================== REAL-TIME STREAM ENDPOINT (FIXED FOR WHISPERX) ====================
@app.post("/stream")
async def stream_transcribe(audio: UploadFile = File(...)):
    """
    🔥 FIXED: Sửa lỗi 'beam_size' và khớp định dạng trả về của WhisperX
    """
    whisper_service = await get_whisperx_service()

    if whisper_service is None:
        return JSONResponse(
            status_code=503,
            content={
                "segments": [],
                "buffer_size_ms": 0,
                "error": "WhisperX service not available",
            },
        )

    try:
        content = await audio.read()

        if len(content) < 400:
            return JSONResponse(content={"segments": [], "buffer_size_ms": 0})

        # Đọc dữ liệu float32 từ Rust
        audio_data = np.frombuffer(content, dtype=np.float32)

        if len(audio_data) < 1600:
            return JSONResponse(content={"segments": [], "buffer_size_ms": 0})

        # 🔥 SỬA QUAN TRỌNG: WhisperX.model.transcribe trả về Dictionary {'segments': [...]}
        # Không dùng beam_size ở đây vì pipeline của WhisperX đã tối ưu rồi
        result = whisper_service.model.transcribe(
            audio_data, language="en"  # Hoặc None để tự nhận diện
        )

        # Trích xuất segments từ Dictionary
        raw_segments = result.get("segments", [])

        formatted_segments = []
        for seg in raw_segments:
            formatted_segments.append(
                {
                    "text": seg.get("text", "").strip(),
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0),
                    "timestamp": f"{int(seg.get('start', 0) // 60)}:{int(seg.get('start', 0) % 60):02d}",
                }
            )

        # Tính buffer_size_ms cho Rust
        buffer_size_ms = int(len(audio_data) * 1000 / 16000)

        # Trả về kèm buffer_size_ms để Rust không báo lỗi "missing field"
        return JSONResponse(
            content={"segments": formatted_segments, "buffer_size_ms": buffer_size_ms}
        )

    except Exception as e:
        logger.error(f"❌ Real-time transcription error: {e}")
        # Luôn trả về cấu trúc đúng để Rust không bị lỗi
        return JSONResponse(content={"segments": [], "buffer_size_ms": 0})


# ==================== ENHANCED BACKGROUND PROCESSING ====================
async def process_transcript_background(process_id: str, transcript: TranscriptRequest):
    try:
        logger.info(f"Starting background processing for process_id: {process_id}")

        speaker_context = get_participant_context()

        num_chunks, all_json_data = await processor.process_transcript(
            text=transcript.text,
            model=transcript.model,
            model_name=transcript.model_name,
            chunk_size=transcript.chunk_size,
            overlap=transcript.overlap,
            speaker_context=speaker_context,
        )

        merged_summary = {
            "meeting_name": "",
            "meeting_date": datetime.now().strftime("%Y-%m-%d"),
            "general_summary": "",
            "key_decisions": [],
            "action_items": [],
            "pending_questions": [],
            "key_topics_discussed": [],
        }

        all_decisions = []
        all_action_items = []
        all_questions = []
        all_topics = []
        general_summaries = []

        for json_str in all_json_data:
            try:
                json_dict = json.loads(json_str)

                if json_dict.get("meeting_name") and not merged_summary["meeting_name"]:
                    merged_summary["meeting_name"] = json_dict["meeting_name"]

                if json_dict.get("general_summary"):
                    general_summaries.append(json_dict["general_summary"])

                for decision in json_dict.get("key_decisions", []):
                    if decision not in all_decisions:
                        all_decisions.append(decision)

                for item in json_dict.get("action_items", []):
                    existing = next(
                        (
                            i
                            for i in all_action_items
                            if i.get("task") == item.get("task")
                        ),
                        None,
                    )
                    if not existing:
                        all_action_items.append(item)

                for question in json_dict.get("pending_questions", []):
                    if question not in all_questions:
                        all_questions.append(question)

                for topic in json_dict.get("key_topics_discussed", []):
                    if topic not in all_topics:
                        all_topics.append(topic)

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON: {e}")

        if general_summaries:
            merged_summary["general_summary"] = " ".join(general_summaries)

        merged_summary["key_decisions"] = all_decisions
        merged_summary["action_items"] = all_action_items
        merged_summary["pending_questions"] = all_questions
        merged_summary["key_topics_discussed"] = all_topics

        if not merged_summary["meeting_name"]:
            merged_summary["meeting_name"] = f"Meeting_{process_id[:8]}"

        speakers = get_all_speakers()
        for item in merged_summary["action_items"]:
            assignee_name = item.get("assignee_name", "")
            for speaker in speakers:
                if speaker["name"].lower() == assignee_name.lower():
                    if not item.get("assignee_email"):
                        item["assignee_email"] = speaker.get("email", "")
                    break

        await processor.db.update_process(
            process_id, status="completed", result=json.dumps(merged_summary)
        )
        logger.info(f"Background processing completed for process_id: {process_id}")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in background processing for {process_id}: {error_msg}")
        await processor.db.update_process(process_id, status="failed", error=error_msg)


# ==================== API ENDPOINTS ====================
@app.post("/process-transcript")
async def process_transcript_api(
    transcript: TranscriptRequest, background_tasks: BackgroundTasks
):
    try:
        process_id = await processor.db.create_process()
        await processor.db.save_transcript(
            process_id,
            transcript.text,
            transcript.model,
            transcript.model_name,
            transcript.chunk_size,
            transcript.overlap,
        )
        background_tasks.add_task(process_transcript_background, process_id, transcript)
        return JSONResponse({"message": "Processing started", "process_id": process_id})
    except Exception as e:
        logger.error(f"Error in process_transcript_api: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-summary/{process_id}")
async def get_summary(process_id: str):
    try:
        result = await processor.db.get_transcript_data(process_id)
        if not result:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "process_id": process_id,
                    "error": "Process ID not found",
                },
            )

        status = result["status"].lower()
        summary_data = None
        if result.get("result"):
            try:
                summary_data = json.loads(result["result"])
                if isinstance(summary_data, str):
                    summary_data = json.loads(summary_data)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON data: {str(e)}")

        response = {
            "status": "processing" if status in ["processing", "pending"] else status,
            "meeting_name": summary_data.get("meeting_name") if summary_data else None,
            "process_id": process_id,
            "start": result.get("start_time"),
            "end": result.get("end_time"),
            "data": summary_data,
        }

        if status == "failed":
            response["status"] = "error"
            response["error"] = result.get("error", "Unknown error")
            return JSONResponse(status_code=400, content=response)
        elif status in ["processing", "pending"]:
            return JSONResponse(status_code=202, content=response)
        elif status == "completed":
            if not summary_data:
                response["status"] = "error"
                response["error"] = "Invalid or missing summary data"
                return JSONResponse(status_code=500, content=response)
            return JSONResponse(status_code=200, content=response)
        else:
            response["status"] = "error"
            response["error"] = f"Unknown status: {status}"
            return JSONResponse(status_code=400, content=response)

    except Exception as e:
        logger.error(f"Error getting summary: {str(e)}")
        return JSONResponse(
            status_code=500, content={"status": "error", "error": str(e)}
        )


@app.get("/get-action-items/{process_id}")
async def get_action_items(process_id: str):
    try:
        result = await processor.db.get_transcript_data(process_id)
        if not result or not result.get("result"):
            return JSONResponse(
                status_code=404,
                content={"error": "Process ID not found or no summary available"},
            )

        summary_data = json.loads(result["result"])

        action_items = []
        for item in summary_data.get("action_items", []):
            action_items.append(
                {
                    "task": item.get("task", ""),
                    "assignee_name": item.get("assignee_name", ""),
                    "assignee_email": item.get("assignee_email", ""),
                    "context": item.get("context", ""),
                    "instructions": item.get("instructions", ""),
                    "deadline": item.get("deadline", "Không có"),
                    "priority": item.get("priority", "Trung bình"),
                }
            )

        return JSONResponse(
            content={
                "meeting_name": summary_data.get("meeting_name", ""),
                "meeting_date": summary_data.get("meeting_date", ""),
                "general_summary": summary_data.get("general_summary", ""),
                "action_items": action_items,
                "key_decisions": summary_data.get("key_decisions", []),
                "pending_questions": summary_data.get("pending_questions", []),
                "key_topics_discussed": summary_data.get("key_topics_discussed", []),
            }
        )

    except Exception as e:
        logger.error(f"Error getting action items: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/upload-transcript")
async def upload_transcript(
    background_tasks: BackgroundTasks,
    model: str = "claude",
    model_name: str = "claude-3-5-sonnet-latest",
    chunk_size: Optional[int] = 5000,
    overlap: Optional[int] = 1000,
    file: UploadFile = File(...),
) -> Dict[str, str]:
    logger.info(f"Received transcript file upload: {file.filename}")
    try:
        content = await file.read()
        transcript_text = content.decode()

        transcript = TranscriptRequest(
            text=transcript_text,
            model=model,
            model_name=model_name,
            chunk_size=chunk_size,
            overlap=overlap,
        )

        process_id = await processor.db.create_process()
        await processor.db.save_transcript(
            process_id, transcript_text, model, model_name, chunk_size, overlap
        )
        background_tasks.add_task(process_transcript_background, process_id, transcript)
        return JSONResponse({"message": "Processing started", "process_id": process_id})
    except Exception as e:
        logger.error(f"Error processing transcript file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== TRANSLATION ENDPOINTS ====================
@app.get("/languages")
async def get_languages():
    return translation_service.get_supported_languages()


@app.post("/translate")
async def translate_text(request: dict):
    text = request.get("text", "")
    target_lang = request.get("target_lang", "en")
    source_lang = request.get("source_lang", "auto")
    sequence = request.get("sequence", None)
    result = await translation_service.translate(
        text, target_lang, source_lang, seq=sequence
    )
    return result


# ==================== WHISPERX DIARIZATION ENDPOINTS ====================
@app.post("/diarize")
async def diarize_audio(file: UploadFile = File(...)):
    content = await file.read()
    print(f"📦 Backend nhận được file dung lượng: {len(content)} bytes")

    if len(content) < 100:
        return JSONResponse(
            status_code=400, content={"error": "File quá nhỏ hoặc trống"}
        )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        whisper_service = await get_whisperx_service()
        if whisper_service is None:
            return JSONResponse(
                status_code=503, content={"error": "WhisperX service not available"}
            )

        raw_result = await whisper_service.process_audio(tmp_path)
        mapped_result = map_speakers_to_real_names(raw_result)
        return JSONResponse(content=mapped_result)
    except Exception as e:
        logger.error(f"Error in diarization: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/diarize-local")
async def diarize_local_audio(req: LocalDiarizeRequest):
    if not os.path.exists(req.file_path):
        return JSONResponse(
            status_code=404,
            content={"error": f"File không tồn tại trên ổ cứng: {req.file_path}"},
        )

    try:
        logger.info(f"📦 Backend xử lý file: {req.file_path}")

        whisper_service = await get_whisperx_service()
        if whisper_service is None:
            return JSONResponse(
                status_code=503, content={"error": "WhisperX service not available"}
            )

        raw_result = await whisper_service.process_audio(req.file_path)
        mapped_result = map_speakers_to_real_names(raw_result)

        return JSONResponse(content=mapped_result)
    except Exception as e:
        logger.error(f"Error in local diarization: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ==================== WHISPERX CACHE MANAGEMENT ====================
@app.post("/unload-whisperx")
async def force_unload_whisperx():
    await unload_whisperx()
    return JSONResponse(content={"status": "success", "message": "WhisperX unloaded"})


@app.get("/whisperx-status")
async def whisperx_status():
    return JSONResponse(
        content={
            "loaded": _whisperx_cache["instance"] is not None,
            "last_used": (
                _whisperx_cache["last_used"].isoformat()
                if _whisperx_cache["last_used"]
                else None
            ),
            "idle_timeout_seconds": WHISPERX_IDLE_TIMEOUT,
        }
    )


# ==================== SPEAKER MAPPING ENDPOINTS ====================
@app.get("/speakers")
async def get_speakers():
    return JSONResponse(content={"speakers": get_all_speakers()})


@app.post("/speakers/map")
async def map_speaker(req: MappingRequest):
    try:
        meeting_directory.update_mapping(req.speaker_id, req.name, req.email)
        return JSONResponse(
            content={
                "status": "success",
                "message": f"Đã cập nhật {req.speaker_id} thành {req.name}",
            }
        )
    except Exception as e:
        logger.error(f"Error mapping speaker: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/speakers/{speaker_id}")
async def delete_speaker_mapping(speaker_id: str):
    try:
        meeting_directory.delete_mapping(speaker_id)
        return JSONResponse(
            content={"status": "success", "message": f"Đã xóa mapping cho {speaker_id}"}
        )
    except Exception as e:
        logger.error(f"Error deleting mapping: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== STARTUP & SHUTDOWN ====================
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Initializing services...")
    logger.info("✅ Translation service ready")
    logger.info("ℹ️ WhisperX will be loaded on-demand when needed (saves RAM)")
    logger.info("✅ All services initialized successfully")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("API shutting down, cleaning up resources")
    try:
        await unload_whisperx()
        processor.cleanup()
        logger.info("Successfully cleaned up resources")
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}", exc_info=True)


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    uvicorn.run(app, host="0.0.0.0", port=5167)
