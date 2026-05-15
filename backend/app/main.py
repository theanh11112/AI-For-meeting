from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
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
import httpx
from groq import Groq
import re
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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


def clean_email(email: str) -> str:
    """Làm sạch email, chỉ giữ lại định dạng email chuẩn"""
    if not email:
        return ""

    # Chuyển thành string
    email_str = str(email)

    # Tìm pattern email
    match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", email_str)
    if match:
        cleaned = match.group(0)
        # Xóa khoảng trắng thừa
        cleaned = cleaned.strip().replace("\n", "").replace("\r", "").replace("\t", "")
        return cleaned

    return email_str


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


# ==================== EMAIL AGENT CLIENTS ====================
email_groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_API_URL = "https://api.resend.com/emails"


# ==================== HÀM CHUẨN HÓA TASK FORMAT ====================
def normalize_task_format(task_content: str, task_id: int = 0) -> str:
    """Chuẩn hóa task content về format: [Tên]: Nội dung công việc (Deadline: ASAP)"""
    original_content = task_content

    if re.match(r"^\[.*?\]:", task_content):
        if "(Deadline:" not in task_content:
            task_content = f"{task_content} (Deadline: ASAP)"
        return task_content

    common_names = [
        "Anne",
        "John",
        "Peter",
        "Mary",
        "David",
        "Sarah",
        "Michael",
        "Lisa",
        "James",
    ]

    found = False
    for name in common_names:
        pattern = re.compile(rf"^(?:{name})\s+(.+)$", re.IGNORECASE)
        match = pattern.match(task_content)
        if match:
            remaining = match.group(1).strip()
            remaining = re.sub(r"^(cần|phải|sẽ)\s+", "", remaining)
            task_content = f"[{name}]: {remaining} (Deadline: ASAP)"
            found = True
            logger.info(
                f"🔄 Chuẩn hóa task {task_id}: '{original_content}' -> '{task_content}'"
            )
            break

    if not found:
        task_content = f"[Người được giao]: {task_content} (Deadline: ASAP)"
        logger.warning(
            f"⚠️ Không tìm thấy tên trong task {task_id}: '{original_content}'"
        )

    return task_content


def normalize_all_tasks(tasks_blocks: list) -> list:
    """Chuẩn hóa tất cả các task blocks"""
    normalized_blocks = []
    for idx, block in enumerate(tasks_blocks):
        if isinstance(block, dict):
            content = block.get("content", "")
            if content:
                new_content = normalize_task_format(content, idx)
                block["content"] = new_content
        normalized_blocks.append(block)
    return normalized_blocks


# ==================== AGENT QA: KIỂM DUYỆT TASK ====================
async def qa_verify_tasks(tasks_blocks: list, original_transcript: str) -> list:
    """Agent QA: Kiểm duyệt xem Task có bịa đặt hay không"""
    if not tasks_blocks:
        return []

    tasks_text = "\n".join(
        [
            f"- ID: {i} | Nội dung: {b.get('content', '')}"
            for i, b in enumerate(tasks_blocks)
        ]
    )
    transcript_snippet = original_transcript[:30000]

    system_prompt = """Bạn là Agent Kiểm Duyệt Chất Lượng (QA Agent) cực kỳ nghiêm khắc. 
Nhiệm vụ của bạn là chống lại chứng "ảo giác" (hallucination) của AI khác.

Quy trình:
1. Đọc nội dung cuộc họp (Transcript).
2. Kiểm tra danh sách Task được giao.
3. Nếu người được giao KHÔNG CÓ TRONG CUỘC HỌP, hoặc công việc ĐÓ KHÔNG HỀ ĐƯỢC NHẮC TỚI -> Đó là task ảo (XÓA).
4. Nếu task hợp lệ và có cơ sở từ nội dung họp -> GIỮ LẠI.

CHỈ TRẢ VỀ JSON CHỨA ID CỦA NHỮNG TASK HỢP LỆ:
{"valid_ids": [0, 2]}"""

    user_prompt = f"""=== NỘI DUNG CUỘC HỌP ===\n{transcript_snippet}\n\n=== DANH SÁCH TASK CẦN KIỂM DUYỆT ===\n{tasks_text}"""

    try:
        logger.info(f"🕵️ Agent QA đang kiểm duyệt {len(tasks_blocks)} tasks...")
        try:
            response = email_groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            result = json.loads(response.choices[0].message.content)
        except Exception:
            result = {"valid_ids": []}

        valid_ids = result.get("valid_ids", [])
        verified_tasks = []
        for vid in valid_ids:
            try:
                idx = int(vid)
                if 0 <= idx < len(tasks_blocks):
                    verified_tasks.append(tasks_blocks[idx])
            except (ValueError, TypeError):
                continue

        removed_count = len(tasks_blocks) - len(verified_tasks)
        if removed_count > 0:
            logger.info(f"✅ Agent QA đã xóa {removed_count} task ảo")
        return verified_tasks
    except Exception as e:
        logger.error(f"❌ Lỗi Agent QA: {e}")
        return tasks_blocks


async def process_and_save_summary(
    process_id: str, all_json_data: List[str], original_transcript: str = ""
) -> Dict[str, Any]:
    """Process JSON chunks, run QA Agent, and save final summary to database"""
    final_summary = {
        "MeetingName": "",
        "SectionSummary": {"title": "Section Summary", "blocks": []},
        "CriticalDeadlines": {"title": "Critical Deadlines", "blocks": []},
        "KeyItemsDecisions": {"title": "Key Items & Decisions", "blocks": []},
        "ImmediateActionItems": {"title": "Immediate Action Items", "blocks": []},
        "NextSteps": {"title": "Next Steps", "blocks": []},
        "OtherImportantPoints": {"title": "Other Important Points", "blocks": []},
        "ClosingRemarks": {"title": "Closing Remarks", "blocks": []},
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
        final_summary["IndividualTasks"]["blocks"].extend(
            json_dict.get("IndividualTasks", {}).get("blocks", [])
        )

    if final_summary["IndividualTasks"]["blocks"]:
        logger.info("📝 Đang chuẩn hóa format tasks...")
        final_summary["IndividualTasks"]["blocks"] = normalize_all_tasks(
            final_summary["IndividualTasks"]["blocks"]
        )

    if original_transcript and final_summary["IndividualTasks"]["blocks"]:
        verified_tasks = await qa_verify_tasks(
            final_summary["IndividualTasks"]["blocks"], original_transcript
        )
        final_summary["IndividualTasks"]["blocks"] = verified_tasks

    if final_summary["MeetingName"]:
        await processor.db.update_meeting_name(process_id, final_summary["MeetingName"])

    await processor.db.update_process(
        process_id,
        status="completed",
        result=json.dumps(final_summary, ensure_ascii=False),
    )
    return final_summary


async def process_transcript_background(process_id: str, transcript: TranscriptRequest):
    """Background task to process transcript with fallback support"""
    start_time = time.time()
    current_model_key = model_manager.current_model
    fallback_attempted = False

    try:
        logger.info(f"Starting background processing for process_id: {process_id}")
        num_chunks, all_json_data = await processor.process_transcript(
            text=transcript.text,
            model=transcript.model,
            model_name=transcript.model_name,
            chunk_size=transcript.chunk_size,
            overlap=transcript.overlap,
        )
        await process_and_save_summary(process_id, all_json_data, transcript.text)
        total_duration = time.time() - start_time
        model_manager.update_stats(
            current_model_key, success=True, response_time=total_duration
        )
        logger.info(f"Background processing completed for process_id: {process_id}")
    except Exception as e:
        error_msg = str(e)
        total_duration = time.time() - start_time
        model_manager.update_stats(
            current_model_key,
            success=False,
            response_time=total_duration,
            error_msg=error_msg,
        )
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
            return JSONResponse(status_code=200, content=response)
        else:
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
    """Dịch text sang ngôn ngữ đích"""
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
            status_code=503, content={"error": "WhisperX service not initialized"}
        )

    content = await file.read()
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


@app.post("/diarize-local")
async def diarize_local_audio(req: LocalDiarizeRequest):
    """Nhận đường dẫn file từ Frontend và tự đọc từ ổ cứng"""
    if not whisperx_service:
        return JSONResponse(
            status_code=503, content={"error": "WhisperX service not initialized"}
        )

    if not os.path.exists(req.file_path):
        return JSONResponse(
            status_code=404, content={"error": f"File không tồn tại: {req.file_path}"}
        )

    try:
        raw_result = await whisperx_service.process_audio(req.file_path)
        mapped_result = map_speakers_to_real_names(raw_result)
        return JSONResponse(content=mapped_result)
    except Exception as e:
        logger.error(f"Error in local diarization: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


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


# ==================== COMPANY CONTEXT MANAGEMENT ====================
COMPANY_CONTEXT_FILE = os.path.join(os.path.dirname(__file__), "company_context.txt")

if not os.path.exists(COMPANY_CONTEXT_FILE):
    with open(COMPANY_CONTEXT_FILE, "w", encoding="utf-8") as f:
        f.write("""Tên công ty: Meetily Corporation
Người gửi: Thế Anh
Chức danh: Giám đốc Điều hành (CEO)
Email người gửi: ceo@meetily.com
Giọng văn: Chuyên nghiệp, thân thiện, rõ ràng, dễ hiểu
Lĩnh vực: Cung cấp giải pháp phần mềm AI và tự động hóa doanh nghiệp
Thông điệp: Đồng hành cùng sự phát triển của đối tác
Chữ ký mặc định: Trân trọng,""")


class UpdateContextRequest(BaseModel):
    content: str


@app.get("/company-context")
async def get_company_context():
    try:
        with open(COMPANY_CONTEXT_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        return {"success": True, "content": content, "file_path": COMPANY_CONTEXT_FILE}
    except Exception as e:
        logger.error(f"Lỗi đọc file context: {e}")
        return {"success": False, "error": str(e)}


@app.post("/company-context")
async def update_company_context(req: UpdateContextRequest):
    try:
        with open(COMPANY_CONTEXT_FILE, "w", encoding="utf-8") as f:
            f.write(req.content)
        logger.info("✅ Đã cập nhật company context")
        return {"success": True, "message": "Đã cập nhật context thành công"}
    except Exception as e:
        logger.error(f"Lỗi ghi file context: {e}")
        return {"success": False, "error": str(e)}


@app.get("/company-context/download")
async def download_company_context():
    try:
        with open(COMPANY_CONTEXT_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        return PlainTextResponse(
            content=content,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=company_context.txt"},
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== MEETING HISTORY ENDPOINTS ====================
@app.get("/meetings")
async def get_all_meetings(limit: int = 5, offset: int = 0):
    try:
        meetings = await processor.db.get_all_meetings(limit, offset)
        return JSONResponse(
            {"status": "success", "meetings": meetings, "total": len(meetings)}
        )
    except Exception as e:
        logger.error(f"Lỗi khi lấy danh sách cuộc họp: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e), "meetings": []},
        )


@app.delete("/meetings/{process_id}")
async def delete_meeting(process_id: str):
    try:
        success = await processor.db.delete_meeting(process_id)
        if success:
            return JSONResponse(
                {"status": "success", "message": "Đã xóa cuộc họp thành công"}
            )
        else:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "error": "Không tìm thấy cuộc họp"},
            )
    except Exception as e:
        logger.error(f"Lỗi khi xóa cuộc họp {process_id}: {e}")
        return JSONResponse(
            status_code=500, content={"status": "error", "error": str(e)}
        )


@app.get("/meetings/{process_id}/detail")
async def get_meeting_detail(process_id: str):
    try:
        result = await processor.db.get_transcript_data(process_id)
        if not result:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "error": "Không tìm thấy cuộc họp"},
            )

        summary_data = None
        if result.get("result"):
            try:
                summary_data = json.loads(result["result"])
                if isinstance(summary_data, str):
                    summary_data = json.loads(summary_data)
            except json.JSONDecodeError:
                summary_data = None

        return JSONResponse(
            {
                "status": "success",
                "process_id": process_id,
                "meeting_name": result.get("meeting_name", "Cuộc họp chưa đặt tên"),
                "transcript": result.get("transcript_text", ""),
                "summary": summary_data,
                "status": result.get("status", "unknown"),
                "created_at": result.get("created_at"),
                "start_time": result.get("start_time"),
                "end_time": result.get("end_time"),
                "model": result.get("model"),
                "model_name": result.get("model_name"),
            }
        )
    except Exception as e:
        logger.error(f"Lỗi khi lấy chi tiết cuộc họp {process_id}: {e}")
        return JSONResponse(
            status_code=500, content={"status": "error", "error": str(e)}
        )


@app.get("/meetings/{process_id}/email-history")
async def get_email_history(process_id: str):
    """Lấy lịch sử email đã gửi của một cuộc họp"""
    try:
        logs = await processor.db.get_email_logs(process_id)
        return {"status": "success", "logs": logs}
    except Exception as e:
        logger.error(f"Lỗi lấy lịch sử email: {e}")
        return JSONResponse(
            status_code=500, content={"status": "error", "error": str(e)}
        )


@app.get("/email-logs")
async def get_all_email_logs(limit: int = 50):
    """Lấy tất cả email logs (toàn hệ thống)"""
    try:
        logs = await processor.db.get_all_email_logs(limit)
        return {"status": "success", "logs": logs}
    except Exception as e:
        logger.error(f"Lỗi lấy tất cả email logs: {e}")
        return JSONResponse(
            status_code=500, content={"status": "error", "error": str(e)}
        )


# ==================== EMAIL AGENT ENDPOINTS ====================

# ==================== EMAIL AGENT ENDPOINTS ====================

# Đọc config từ environment variables
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.7"))
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "4096"))

# Gmail SMTP Configuration (thay thế cho Resend)
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")


class GenerateEmailRequest(BaseModel):
    meeting_summary: str
    users_tasks: list
    context_text: str = ""


class SendEmailsRequest(BaseModel):
    process_id: str
    drafts: list


async def get_company_context_text() -> str:
    try:
        if os.path.exists(COMPANY_CONTEXT_FILE):
            with open(COMPANY_CONTEXT_FILE, "r", encoding="utf-8") as f:
                content = f.read()
                if content and content.strip():
                    return content
    except Exception as e:
        logger.error(f"Lỗi đọc company context: {e}")
    return """Tên công ty: Meetily Corporation
Người gửi: Thế Anh
Chức danh: Giám đốc Điều hành (CEO)
Giọng văn: Chuyên nghiệp, thân thiện, rõ ràng
Lĩnh vực: Cung cấp giải pháp phần mềm AI"""


def clean_email_address(raw_email: str) -> str:
    """Làm sạch địa chỉ email, chỉ giữ lại định dạng email chuẩn"""
    if not raw_email:
        return ""

    email_str = str(raw_email)
    match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", email_str)
    if match:
        cleaned = match.group(0)
        cleaned = cleaned.strip().replace("\n", "").replace("\r", "").replace("\t", "")
        return cleaned
    return ""


async def generate_drafts(
    meeting_summary: str, users_tasks: list, context_text: str = ""
):
    drafts = []
    file_context = await get_company_context_text()
    final_context = (
        file_context if file_context and file_context.strip() else context_text
    )

    for user in users_tasks:
        tasks_list = []
        for t in user.get("tasks", []):
            deadline_text = (
                f" (Hạn: {t['deadline']})"
                if t.get("deadline") and t["deadline"] != "ASAP"
                else ""
            )
            tasks_list.append(f"  • {t['task_name']}{deadline_text}")
        tasks_text = "\n".join(tasks_list)

        writer_sys_prompt = f"""Bạn là Thư ký AI chuyên nghiệp. Hãy soạn bản nháp email giao việc cho nhân viên.
THÔNG TIN NGƯỜI GỬI:
{final_context}

TÓM TẮT CUỘC HỌP:
{meeting_summary}"""

        writer_user_prompt = f"""Viết email cho: {user.get('name', 'Nhân viên')} ({user.get('email', 'email@example.com')}).
CÔNG VIỆC CẦN GIAO:
{tasks_text}

Viết bằng tiếng Việt, thân thiện, chuyên nghiệp. KHÔNG CẦN JSON."""

        try:
            writer_res = email_groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": writer_sys_prompt},
                    {"role": "user", "content": writer_user_prompt},
                ],
                temperature=0.7,
                max_tokens=GROQ_MAX_TOKENS,
            )
            draft_content = writer_res.choices[0].message.content

            editor_sys_prompt = """Bạn là Trưởng phòng Kiểm duyệt Email. Đọc bản nháp, SỬA LỖI và trả về JSON.
{"subject": "Tiêu đề", "body": "Nội dung"}"""

            editor_user_prompt = f"""TASK GỐC:\n{tasks_text}\n\nBẢN NHÁP:\n{draft_content}\n\nTrả về JSON."""

            editor_res = email_groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": editor_sys_prompt},
                    {"role": "user", "content": editor_user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=GROQ_MAX_TOKENS,
            )
            result_text = editor_res.choices[0].message.content
            result = json.loads(result_text)
            drafts.append(
                {
                    "to_email": clean_email_address(user.get("email", "")),
                    "to_name": user.get("name", ""),
                    "subject": result.get("subject", "Cập nhật công việc"),
                    "body": result.get("body", ""),
                }
            )
        except Exception as e:
            logger.error(f"Lỗi tạo email cho {user.get('name')}: {e}")
            drafts.append(
                {
                    "to_email": clean_email_address(user.get("email", "")),
                    "to_name": user.get("name", ""),
                    "subject": f"Cập nhật công việc - {user.get('name')}",
                    "body": f"Kính gửi {user.get('name')},\n\nDanh sách công việc:\n{tasks_text}\n\nTrân trọng,\n{final_context.split(chr(10))[1] if 'Người gửi:' in final_context else 'Ban Giám Đốc'}",
                }
            )
    return drafts


async def send_single_email(draft: dict) -> Dict[str, Any]:
    """Gửi 1 email qua Gmail SMTP với lọc email hợp lệ"""

    # Lấy email và làm sạch
    raw_email = str(draft.get("to_email", ""))
    to_email = clean_email_address(raw_email)

    if not to_email:
        logger.error(f"❌ Email không hợp lệ: {raw_email}")
        return {"status": "error", "error": f"Invalid email format: {raw_email}"}

    # Kiểm tra email có chứa ký tự non-ASCII không
    try:
        to_email.encode("ascii")
    except UnicodeEncodeError:
        logger.error(f"❌ Email chứa ký tự non-ASCII: {to_email}")
        return {
            "status": "error",
            "error": f"Email contains non-ASCII characters: {to_email}",
        }

    subject = str(draft.get("subject", ""))
    body = str(draft.get("body", ""))
    to_name = str(draft.get("to_name", ""))

    logger.info(f"📧 Đã lọc email: {raw_email} -> {to_email}")

    # Kiểm tra cấu hình Gmail
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        logger.warning(
            "⚠️ Chưa cấu hình GMAIL_USER hoặc GMAIL_APP_PASSWORD trong file .env"
        )
        logger.info(f"\n📧 [TEST MODE] Gửi cho {to_name} <{to_email}>")
        logger.info(f"Subject: {subject}")
        logger.info(f"Body: {body[:200]}...")
        return {"status": "test_mode"}

    # Gửi email qua Gmail SMTP
    try:
        msg = MIMEMultipart()
        msg["From"] = GMAIL_USER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)

        logger.info(f"✅ Đã gửi email thành công tới {to_email}")
        return {"status": "success"}

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "❌ Lỗi xác thực Gmail. Kiểm tra lại GMAIL_USER và GMAIL_APP_PASSWORD"
        )
        return {"status": "error", "error": "SMTP Authentication failed"}
    except Exception as e:
        logger.error(f"❌ Lỗi gửi email: {e}")
        return {"status": "error", "error": str(e)}


async def send_emails_background_task(drafts: list, process_id: str):
    """Gửi nhiều email và lưu log vào DB cho từng email"""
    for draft in drafts:
        result = await send_single_email(draft)
        if result["status"] in ["success", "test_mode"]:
            await processor.db.log_email_sent(
                process_id=process_id,
                email=draft["to_email"],
                name=draft["to_name"],
                subject=draft["subject"],
                body=draft["body"],
            )
            logger.info(
                f"✅ Đã lưu log email tới {draft['to_email']} cho process {process_id}"
            )
        else:
            logger.error(
                f"❌ Gửi email thất bại cho {draft['to_email']}: {result.get('error', 'Unknown error')}"
            )


@app.post("/generate-email-drafts")
async def api_generate_drafts(req: GenerateEmailRequest):
    try:
        drafts = await generate_drafts(
            req.meeting_summary, req.users_tasks, req.context_text
        )
        return {"success": True, "drafts": drafts}
    except Exception as e:
        logger.error(f"Lỗi API tạo draft: {e}")
        return {"success": False, "error": str(e)}


@app.post("/send-emails")
async def api_send_emails(req: SendEmailsRequest, background_tasks: BackgroundTasks):
    try:
        background_tasks.add_task(
            send_emails_background_task, req.drafts, req.process_id
        )
        return {"success": True}
    except Exception as e:
        logger.error(f"Lỗi API gửi email: {e}")
        return {"success": False, "error": str(e)}


# ==================== MAIN ====================
if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    uvicorn.run(app, host="0.0.0.0", port=5167)
