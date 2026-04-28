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
import json
from threading import Lock
import uuid
import tempfile
import sys
import time

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
    processor as global_processor,
    summarizer as global_summarizer,
    initialize_agent_with_model,
)
from .translation import TranslationService
from .whisperx_service import WhisperXService
from .models.user_map import meeting_directory
from .services.speaker_mapper import map_speakers_to_real_names, get_all_speakers
from .model_config import model_manager

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
    """Request model for transcript text"""

    text: str
    model: str
    model_name: str
    chunk_size: Optional[int] = 20000
    overlap: Optional[int] = 1000


class MappingRequest(BaseModel):
    """Request model for speaker mapping"""

    speaker_id: str
    name: str
    email: str


# Request model cho local diarization
class LocalDiarizeRequest(BaseModel):
    file_path: str


class SummaryProcessor:
    """Handles the processing of summaries in a thread-safe way"""

    def __init__(self):
        try:
            self.db = DatabaseManager()
            self._lock = Lock()

            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                logger.warning("GROQ_API_KEY environment variable not set!")
                logger.warning(
                    "System will attempt to use local Ollama fallback if available."
                )
            else:
                logger.info("GROQ_API_KEY loaded successfully")

            logger.info("Initializing SummaryProcessor components")

            # Sử dụng global processor và summarizer từ Process_transcrip
            self.transcript_processor = global_processor
            self.summarizer = global_summarizer

            # Khởi tạo agent với model phù hợp
            self.agent, _ = initialize_agent_with_model(api_key)

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
        chunk_size: int = 20000,
        overlap: int = 1000,
    ) -> tuple:
        """Process a transcript text"""
        try:
            if not text:
                raise ValueError("Empty transcript text provided")

            logger.info(f"Processing transcript of length {len(text)}")
            num_chunks, all_json_data = (
                await self.transcript_processor.process_transcript(
                    text=text,
                    model=model,
                    model_name=model_name,
                    chunk_size=chunk_size,
                    overlap=overlap,
                )
            )
            logger.info(f"Successfully processed transcript into {num_chunks} chunks")
            return num_chunks, all_json_data
        except Exception as e:
            logger.error(f"Error processing transcript: {str(e)}", exc_info=True)
            raise

    def cleanup(self):
        """Cleanup resources"""
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
whisperx_service = None


# Define tools using processor's agent
@processor.agent.tool
async def query_transcript(ctx: RunContext, query: str) -> str:
    """Query the transcript to extract information. Returns the content and chunk IDs for deletion."""
    try:
        logger.info(f"Querying transcript with: {query}")

        if not processor.transcript_processor.collection:
            logger.error("No ChromaDB collection available")
            return "Error: No transcript loaded. Please process a transcript first."

        collection_data = processor.transcript_processor.collection.get()
        if not collection_data["ids"]:
            logger.info("No chunks left to process")
            return "CHROMADB_EMPTY: All chunks have been processed."

        logger.info("Querying ChromaDB for relevant chunks")
        results = processor.transcript_processor.collection.query(
            query_texts=[query], n_results=1
        )

        if not results or not results["documents"] or not results["documents"][0]:
            logger.info("No results found for query")
            return "No results found for the query"

        combined_result = ""
        chunk_ids = []

        for doc, metadata, id in zip(
            results["documents"][0], results["metadatas"][0], results["ids"][0]
        ):
            combined_result += f"\n{doc}\n"
            chunk_ids.append(id)

        if chunk_ids:
            try:
                logger.info(f"Deleting {len(chunk_ids)} processed chunks")
                processor.transcript_processor.collection.delete(ids=chunk_ids)
                remaining = processor.transcript_processor.collection.get()
                logger.info(f"Remaining chunks: {len(remaining['ids'])}")
            except Exception as e:
                logger.error(f"Error deleting chunks: {str(e)}", exc_info=True)
                return f"Error deleting chunks: {str(e)}"

        return combined_result.strip()

    except Exception as e:
        logger.error(f"Error querying transcript: {str(e)}", exc_info=True)
        return f"Error: {str(e)}"


@processor.agent.tool
async def delete_processed_chunks(ctx: RunContext) -> str:
    """Delete all processed chunks from the collection"""
    try:
        if not hasattr(ctx, "processed_chunks") or not ctx.processed_chunks:
            return "No chunks to delete"

        chunk_ids = list(ctx.processed_chunks)
        processor.transcript_processor.collection.delete(ids=chunk_ids)
        ctx.processed_chunks.clear()
        return f"Successfully deleted {len(chunk_ids)} chunks"

    except Exception as e:
        logger.error(f"Error deleting chunks: {e}")
        return f"Error deleting chunks: {str(e)}"


@processor.agent.tool
async def add_action_item(ctx: RunContext, title: str, content: str) -> str:
    """Add an action item to the summary"""
    try:
        logger.info(f"Adding action item: {title}")
        result = processor.summarizer.add_action_item(ctx, title, content)
        logger.info("Successfully added action item")
        return f"Successfully added action item: {result}"
    except Exception as e:
        logger.error(f"Error adding action item: {str(e)}", exc_info=True)
        return f"Error adding action item: {str(e)}"


@processor.agent.tool
async def add_agenda_item(ctx: RunContext, title: str, content: str) -> str:
    """Add an agenda item to the summary"""
    try:
        logger.info(f"Adding agenda item: {title}")
        result = processor.summarizer.add_agenda_item(ctx, title, content)
        logger.info("Successfully added agenda item")
        return f"Successfully added agenda item: {result}"
    except Exception as e:
        logger.error(f"Error adding agenda item: {str(e)}", exc_info=True)
        return f"Error adding agenda item: {str(e)}"


@processor.agent.tool
async def add_decision(ctx: RunContext, title: str, content: str) -> str:
    """Add a decision to the summary"""
    try:
        logger.info(f"Adding decision: {title}")
        result = processor.summarizer.add_decision(ctx, title, content)
        logger.info("Successfully added decision")
        return f"Successfully added decision: {result}"
    except Exception as e:
        logger.error(f"Error adding decision: {str(e)}", exc_info=True)
        return f"Error adding decision: {str(e)}"


@processor.agent.tool
async def add_individual_task(
    ctx: RunContext, assignee: str, task: str, deadline: str = None
) -> str:
    """Add a task assigned to a specific individual"""
    try:
        logger.info(f"Adding individual task for {assignee}: {task}")
        result = processor.summarizer.add_individual_task(ctx, assignee, task, deadline)
        return result
    except Exception as e:
        logger.error(f"Error adding individual task: {str(e)}", exc_info=True)
        return f"Error adding individual task: {str(e)}"


@processor.agent.tool
async def save_final_summary_result(ctx: RunContext) -> str:
    """Save the final meeting summary result to a file"""
    try:
        summary = processor.summarizer.generate_summary(ctx)

        if not any(
            [
                summary.Agenda.blocks,
                summary.Decisions.blocks,
                summary.ActionItems.blocks,
                summary.ClosingRemarks.blocks,
                summary.IndividualTasks.blocks,
            ]
        ):
            return "Error: No content found in summary. Please add some items first."

        json_data = summary.model_dump_json(indent=2)

        try:
            with open("final_summary_result.json", "w", encoding="utf-8") as f:
                f.write(json_data)
            return "Successfully saved final summary result to file"
        except IOError as e:
            logger.error(f"Failed to write summary to file: {e}")
            return f"Error saving to file: {str(e)}"

    except Exception as e:
        logger.error(f"Error generating or saving summary: {e}")
        return f"Error processing summary: {str(e)}"


@processor.agent.tool
async def get_final_summary(ctx: RunContext) -> SummaryResponse:
    """Get the final meeting summary result"""
    try:
        logger.info("Generating final summary")
        summary = processor.summarizer.generate_summary(ctx)
        logger.info("Successfully generated final summary")
        return summary
    except Exception as e:
        logger.error(f"Error generating final summary: {str(e)}", exc_info=True)
        raise


async def process_and_save_summary(
    process_id: str, all_json_data: List[str]
) -> Dict[str, Any]:
    """Process JSON chunks and save final summary to database"""
    final_summary = {
        "MeetingName": "",
        "SectionSummary": {"title": "Section Summary", "blocks": []},
        "CriticalDeadlines": {"title": "Critical Deadlines", "blocks": []},
        "KeyItemsDecisions": {"title": "Key Items & Decisions", "blocks": []},
        "ImmediateActionItems": {"title": "Immediate Action Items", "blocks": []},
        "NextSteps": {"title": "Next Steps", "blocks": []},
        "OtherImportantPoints": {"title": "Other Important Points", "blocks": []},
        "ClosingRemarks": {"title": "Closing Remarks", "blocks": []},
        # 🔥 THÊM MỤC INDIVIDUAL TASKS
        "IndividualTasks": {"title": "Individual Tasks (Assignment)", "blocks": []},
    }

    for json_str in all_json_data:
        json_dict = json.loads(json_str)

        if json_dict.get("MeetingName") and not final_summary["MeetingName"]:
            final_summary["MeetingName"] = json_dict["MeetingName"]
        final_summary["SectionSummary"]["blocks"].extend(
            json_dict.get("SectionSummary", {}).get("blocks", [])
        )
        final_summary["CriticalDeadlines"]["blocks"].extend(
            json_dict.get("CriticalDeadlines", {}).get("blocks", [])
        )
        final_summary["KeyItemsDecisions"]["blocks"].extend(
            json_dict.get("KeyItemsDecisions", {}).get("blocks", [])
        )
        final_summary["ImmediateActionItems"]["blocks"].extend(
            json_dict.get("ImmediateActionItems", {}).get("blocks", [])
        )
        final_summary["NextSteps"]["blocks"].extend(
            json_dict.get("NextSteps", {}).get("blocks", [])
        )
        final_summary["OtherImportantPoints"]["blocks"].extend(
            json_dict.get("OtherImportantPoints", {}).get("blocks", [])
        )
        final_summary["ClosingRemarks"]["blocks"].extend(
            json_dict.get("ClosingRemarks", {}).get("blocks", [])
        )
        # 🔥 THÊM DÒNG NÀY ĐỂ GỘP CÁC BLOCK TASK TỪ CÁC CHUNK
        final_summary["IndividualTasks"]["blocks"].extend(
            json_dict.get("IndividualTasks", {}).get("blocks", [])
        )

    if final_summary["MeetingName"]:
        await processor.db.update_meeting_name(process_id, final_summary["MeetingName"])

    await processor.db.update_process(
        process_id, status="completed", result=json.dumps(final_summary)
    )

    return final_summary


async def process_transcript_background(process_id: str, transcript: TranscriptRequest):
    """Background task to process transcript with fallback support"""
    start_time = time.time()
    current_model_key = model_manager.current_model
    fallback_attempted = False

    try:
        logger.info(f"Starting background processing for process_id: {process_id}")

        # Process transcript
        num_chunks, all_json_data = await processor.process_transcript(
            text=transcript.text,
            model=transcript.model,
            model_name=transcript.model_name,
            chunk_size=transcript.chunk_size,
            overlap=transcript.overlap,
        )

        # Save summary to database
        await process_and_save_summary(process_id, all_json_data)

        # Cập nhật thống kê thành công
        total_duration = time.time() - start_time
        model_manager.update_stats(
            current_model_key, success=True, response_time=total_duration
        )

        logger.info(f"Background processing completed for process_id: {process_id}")

    except Exception as e:
        error_msg = str(e)
        total_duration = time.time() - start_time

        # Cập nhật thống kê thất bại cho primary model
        model_manager.update_stats(
            current_model_key,
            success=False,
            response_time=total_duration,
            error_msg=error_msg,
        )

        # KIỂM TRA FALLBACK
        if not fallback_attempted and model_manager.should_retry_with_fallback(
            current_model_key, e
        ):
            logger.warning(
                f"Primary model failed, attempting fallback for process {process_id}"
            )

            # Lấy fallback model
            fallback_info = await model_manager.get_available_model()
            if fallback_info["key"] != current_model_key:
                logger.info(
                    f"Retrying with fallback model: {fallback_info['config']['name']}"
                )
                fallback_attempted = True
                fallback_start_time = time.time()

                try:
                    # Retry với fallback model
                    fallback_transcript = TranscriptRequest(
                        text=transcript.text,
                        model=fallback_info["config"]["provider"],
                        model_name=fallback_info["config"]["name"],
                        chunk_size=transcript.chunk_size,
                        overlap=transcript.overlap,
                    )

                    # Gọi lại process_transcript với fallback
                    num_chunks, all_json_data = await processor.process_transcript(
                        text=fallback_transcript.text,
                        model=fallback_transcript.model,
                        model_name=fallback_transcript.model_name,
                        chunk_size=fallback_transcript.chunk_size,
                        overlap=fallback_transcript.overlap,
                    )

                    # LƯU KẾT QUẢ FALLBACK VÀO DATABASE
                    await process_and_save_summary(process_id, all_json_data)

                    # Cập nhật thống kê cho fallback model
                    fallback_duration = time.time() - fallback_start_time
                    model_manager.update_stats(
                        fallback_info["key"],
                        success=True,
                        response_time=fallback_duration,
                    )

                    logger.info(
                        f"✅ Fallback processing successful for process {process_id}"
                    )
                    return  # Thoát thành công

                except Exception as fallback_error:
                    logger.error(f"❌ Fallback also failed: {str(fallback_error)}")
                    # Cập nhật thống kê thất bại cho fallback
                    model_manager.update_stats(
                        fallback_info["key"],
                        success=False,
                        response_time=time.time() - fallback_start_time,
                        error_msg=str(fallback_error),
                    )

        # Nếu đến được đây, cả primary và fallback đều thất bại
        logger.error(f"Error in background processing for {process_id}: {error_msg}")
        await processor.db.update_process(process_id, status="failed", error=error_msg)


@app.post("/process-transcript")
async def process_transcript_api(
    transcript: TranscriptRequest, background_tasks: BackgroundTasks
):
    """Process a transcript text with background processing"""
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
    """Get the summary for a given process ID"""
    try:
        result = await processor.db.get_transcript_data(process_id)
        if not result:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "meetingName": None,
                    "process_id": process_id,
                    "data": None,
                    "start": None,
                    "end": None,
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
                logger.error(
                    f"Failed to parse JSON data for process {process_id}: {str(e)}"
                )

        response = {
            "status": "processing" if status in ["processing", "pending"] else status,
            "meetingName": summary_data.get("MeetingName") if summary_data else None,
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
        logger.error(f"Error getting summary for {process_id}: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "meetingName": None,
                "process_id": process_id,
                "data": None,
                "start": None,
                "end": None,
                "error": str(e),
            },
        )


@app.post("/upload-transcript")
async def upload_transcript(
    background_tasks: BackgroundTasks,
    model: str = "groq",
    model_name: str = "llama-3.3-70b-versatile",
    chunk_size: Optional[int] = 20000,
    overlap: Optional[int] = 1000,
    file: UploadFile = File(...),
) -> Dict[str, str]:
    """Upload and process a transcript file"""
    logger.info(f"Received transcript file upload: {file.filename}")
    try:
        content = await file.read()
        transcript_text = content.decode()
        logger.info("Successfully decoded transcript file content")

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


# ==================== MODEL STATUS ENDPOINT ====================
@app.get("/model-status")
async def get_model_status():
    """Lấy trạng thái hiện tại của model manager"""
    try:
        return {
            "status": "success",
            "current_model": model_manager.get_current_model_name(),
            "current_provider": model_manager.get_current_provider(),
            "models": model_manager.get_model_info(),
            "statistics": model_manager.get_statistics(),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error getting model status: {e}")
        return {"status": "error", "error": str(e)}


# ==================== STARTUP & SHUTDOWN EVENTS ====================
@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    global whisperx_service
    logger.info("🚀 Initializing services...")

    try:
        whisperx_service = WhisperXService()
        logger.info("✅ WhisperX service ready")
    except Exception as e:
        logger.error(f"❌ Failed to initialize WhisperX: {e}")
        whisperx_service = None


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on API shutdown"""
    logger.info("API shutting down, cleaning up resources")
    try:
        processor.cleanup()
        logger.info("Successfully cleaned up resources")
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}", exc_info=True)


# ==================== TRANSLATION ENDPOINTS ====================
@app.get("/languages")
async def get_languages():
    """Trả về danh sách ngôn ngữ hỗ trợ"""
    return translation_service.get_supported_languages()


@app.post("/translate")
async def translate_text(request: dict):
    """
    Dịch text sang ngôn ngữ đích

    Request body:
    {
        "text": "text to translate",
        "target_lang": "en",
        "source_lang": "auto" (optional),
        "sequence": 0 (optional)
    }
    """
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
    """Nhận diện người nói từ file audio (dùng WhisperX) và tự động map tên"""
    if not whisperx_service:
        return JSONResponse(
            status_code=503,
            content={"error": "WhisperX service not initialized. Please check logs."},
        )

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
        raw_result = await whisperx_service.process_audio(tmp_path)
        mapped_result = map_speakers_to_real_names(raw_result)
        return JSONResponse(content=mapped_result)
    except Exception as e:
        logger.error(f"Error in diarization: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# API mới: Nhận đường dẫn file thay vì file blob
@app.post("/diarize-local")
async def diarize_local_audio(req: LocalDiarizeRequest):
    """Nhận đường dẫn file từ Frontend và tự đọc từ ổ cứng"""
    if not whisperx_service:
        return JSONResponse(
            status_code=503,
            content={"error": "WhisperX service not initialized. Please check logs."},
        )

    if not os.path.exists(req.file_path):
        return JSONResponse(
            status_code=404,
            content={"error": f"File không tồn tại trên ổ cứng: {req.file_path}"},
        )

    try:
        logger.info(f"📦 Backend trực tiếp đọc file từ: {req.file_path}")

        # Gọi trực tiếp whisperx_service đọc file từ ổ cứng
        raw_result = await whisperx_service.process_audio(req.file_path)

        # Map tên thật từ danh bạ
        mapped_result = map_speakers_to_real_names(raw_result)

        return JSONResponse(content=mapped_result)
    except Exception as e:
        logger.error(f"Error in local diarization: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ==================== SPEAKER MAPPING ENDPOINTS ====================
@app.get("/speakers")
async def get_speakers():
    """Lấy danh sách tất cả những người tham gia đã được đặt tên"""
    return JSONResponse(content={"speakers": get_all_speakers()})


@app.post("/speakers/map")
async def map_speaker(req: MappingRequest):
    """Cập nhật tên và email cho một SPEAKER_XX"""
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
    """Xóa một mapping"""
    try:
        meeting_directory.delete_mapping(speaker_id)
        return JSONResponse(
            content={"status": "success", "message": f"Đã xóa mapping cho {speaker_id}"}
        )
    except Exception as e:
        logger.error(f"Error deleting mapping: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    uvicorn.run(app, host="0.0.0.0", port=5167)
