# backend/app/Process_transcrip.py
from chromadb import Client as ChromaClient, Settings
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.groq import GroqModel
import json
import logging
import uuid
import os
import argparse
import re
from dotenv import load_dotenv
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()


# ==================== DETAILED ACTION ITEM MODEL ====================
class DetailedActionItem(BaseModel):
    task: str = Field(description="Tên/mô tả ngắn gọn của công việc")
    assignee_name: str = Field(description="Tên người được giao việc")
    assignee_email: str = Field(description="Email của người được giao việc")
    context: str = Field(
        description="Dẫn chứng từ nội dung họp: tại sao việc này phát sinh"
    )
    instructions: str = Field(
        description="AI gợi ý 3 bước cụ thể để thực hiện việc này"
    )
    deadline: str = Field(description="Hạn hoàn thành (YYYY-MM-DD hoặc 'Không có')")
    priority: str = Field(description="Cao, Trung bình, Thấp")


class Decision(BaseModel):
    decision: str = Field(description="Quyết định đã được đưa ra")
    made_by: str = Field(description="Ai đưa ra quyết định này")
    context: str = Field(description="Bối cảnh/Lý do dẫn đến quyết định")
    timestamp: Optional[str] = Field(
        default=None, description="Thời điểm quyết định (nếu có)"
    )


class PendingQuestion(BaseModel):
    question: str = Field(description="Câu hỏi cần được trả lời")
    asked_by: str = Field(description="Ai đã hỏi")
    assigned_to: str = Field(description="Ai cần trả lời (nếu có)")
    urgency: str = Field(default="Trung bình", description="Cao, Trung bình, Thấp")


class EnhancedSummaryResponse(BaseModel):
    meeting_name: str = Field(description="Tên cuộc họp")
    meeting_date: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d"),
        description="Ngày họp",
    )
    general_summary: str = Field(
        description="Tóm tắt 1 đoạn văn về toàn bộ nội dung cuộc họp"
    )
    key_decisions: List[Decision] = Field(
        default_factory=list, description="Các quyết định quan trọng"
    )
    action_items: List[DetailedActionItem] = Field(
        default_factory=list, description="Các công việc cần làm (chi tiết)"
    )
    pending_questions: List[PendingQuestion] = Field(
        default_factory=list, description="Câu hỏi cần theo dõi sau"
    )
    key_topics_discussed: List[str] = Field(
        default_factory=list, description="Các chủ đề chính đã thảo luận"
    )


# ==================== LEGACY MODELS ====================
class Block(BaseModel):
    id: str
    type: str
    content: str
    color: str


class Section(BaseModel):
    title: str
    blocks: List[Block]


class SummaryResponse(BaseModel):
    MeetingName: str
    SectionSummary: Section
    CriticalDeadlines: Section
    KeyItemsDecisions: Section
    ImmediateActionItems: Section
    NextSteps: Section
    OtherImportantPoints: Section
    ClosingRemarks: Section


# ==================== ENHANCED SYSTEM PROMPT ====================
ENHANCED_SYSTEM_PROMPT = """Bạn là thư ký AI chuyên nghiệp với nhiệm vụ phân tích cuộc họp và trích xuất thông tin CHI TIẾT.

🔴 NHIỆM VỤ CHÍNH:
1. Tóm tắt nội dung cuộc họp (ngắn gọn, đủ ý)
2. Xác định tất cả QUYẾT ĐỊNH quan trọng (có ai quyết định, tại sao)
3. Xác định tất cả CÔNG VIỆC CẦN LÀM (có người được giao, hạn, độ ưu tiên)
4. Suy luận NGỮ CẢNH: Tại sao công việc này phát sinh? (trích dẫn từ cuộc họp)
5. Gợi ý CÁC BƯỚC THỰC HIỆN cụ thể cho từng công việc
6. Xác định các CÂU HỎI cần theo dõi sau cuộc họp

📋 YÊU CẦU ĐẦU RA (JSON):
- meeting_name: Tên cuộc họp
- meeting_date: Ngày họp (format YYYY-MM-DD)
- general_summary: Tóm tắt 1-2 câu
- key_decisions: Mỗi decision có decision, made_by, context
- action_items: Mỗi item có task, assignee_name, assignee_email, context, instructions, deadline, priority
- pending_questions: Mỗi question có question, asked_by, assigned_to, urgency
- key_topics_discussed: List các chủ đề chính

⚠️ QUAN TRỌNG:
- context: Phải trích dẫn hoặc diễn giải từ nội dung cuộc họp
- instructions: Gợi ý 3 bước cụ thể, thực tế, có thể làm được
- priority: Phân loại dựa trên urgency (Cao = cần làm ngay, Trung bình = có thể lên kế hoạch, Thấp = không gấp)

📤 CHỈ TRẢ VỀ JSON, KHÔNG CÓ NỘI DUNG KHÁC!"""


# ==================== TRANSCRIPT PREPROCESSOR ====================
class TranscriptPreprocessor:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def sort_by_timestamp(self, transcript_data: List[Dict]) -> List[Dict]:
        try:
            return sorted(transcript_data, key=lambda x: float(x.get("start", 0)))
        except (ValueError, TypeError):
            return transcript_data

    def remove_duplicates(self, transcript_data: List[Dict]) -> List[Dict]:
        seen_texts = set()
        unique_entries = []
        for entry in transcript_data:
            text = entry.get("text", "").strip()
            normalized = " ".join(text.lower().split())
            if normalized and normalized not in seen_texts:
                seen_texts.add(normalized)
                unique_entries.append(entry)
            elif not normalized:
                continue
        return unique_entries

    def merge_adjacent_segments(
        self, transcript_data: List[Dict], time_threshold: float = 2.0
    ) -> List[Dict]:
        if not transcript_data:
            return []
        merged = []
        current = transcript_data[0].copy()
        for next_seg in transcript_data[1:]:
            try:
                current_end = float(current.get("end", 0))
                next_start = float(next_seg.get("start", 0))
                time_gap = next_start - current_end
            except (ValueError, TypeError):
                time_gap = float("inf")
            if (
                current.get("speaker") == next_seg.get("speaker")
                and time_gap <= time_threshold
            ):
                current["text"] += " " + next_seg.get("text", "")
                current["end"] = next_seg.get("end", current["end"])
            else:
                merged.append(current)
                current = next_seg.copy()
        merged.append(current)
        return merged

    def clean_text(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"\*.*?\*", "", text)
        text = re.sub(r"\[.*?\]", "", text)
        text = re.sub(r"\(.*?\)", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def preprocess(self, transcript_data: List[Dict]) -> str:
        self.logger.info(f"Raw transcript has {len(transcript_data)} segments")
        for entry in transcript_data:
            entry["text"] = self.clean_text(entry.get("text", ""))
        transcript_data = [
            entry for entry in transcript_data if entry.get("text", "").strip()
        ]
        sorted_data = self.sort_by_timestamp(transcript_data)
        unique_data = self.remove_duplicates(sorted_data)
        merged_data = self.merge_adjacent_segments(unique_data)
        full_text = " ".join([entry.get("text", "") for entry in merged_data])
        full_text = re.sub(r"\s+", " ", full_text).strip()
        self.logger.info(f"Final preprocessed text length: {len(full_text)} characters")
        return full_text


# ==================== TRANSCRIPT PROCESSOR ====================
class TranscriptProcessor:
    def __init__(self):
        self.collection_name = "all_transcripts"
        self.chroma_client = None
        self.collection = None
        self.preprocessor = TranscriptPreprocessor()
        self.initialize_collection()

    def __del__(self):
        if self.chroma_client:
            try:
                self.collection = None
                self.chroma_client = None
            except Exception as e:
                logger.error(f"Error cleaning up ChromaDB: {e}")

    def initialize_collection(self):
        try:
            if self.chroma_client:
                self.collection = None
                self.chroma_client = None
            settings = Settings(allow_reset=True, is_persistent=True)
            self.chroma_client = ChromaClient(settings)
            try:
                self.collection = self.chroma_client.get_collection(
                    name=self.collection_name
                )
                logger.info(f"Retrieved existing collection: {self.collection_name}")
            except Exception:
                logger.info(f"Creating new collection: {self.collection_name}")
                self.collection = self.chroma_client.create_collection(
                    name=self.collection_name
                )
            if not self.collection:
                raise RuntimeError("Failed to initialize ChromaDB collection")
        except Exception as e:
            logger.error(f"Error initializing ChromaDB: {e}")
            raise

    def cleanup(self):
        if self.chroma_client:
            try:
                self.collection = None
                self.chroma_client = None
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")

    def split_into_sentences(self, text: str) -> List[str]:
        pattern = r"(?<=[.!?…])\s+(?=[A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼỀỀỂẾỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỴÝỶỸ])|(?<=[.!?…])\s*$"
        sentences = re.split(pattern, text)
        sentences = [s.strip() for s in sentences if s.strip()]
        sentences = [s for s in sentences if s and len(s) > 1]
        return sentences if sentences else [text]

    def split_long_sentence(self, sentence: str, max_length: int) -> List[str]:
        parts = []
        split_pattern = r"(?<=[,;])\s+|(?<=\s)(?=and\s+|but\s+|or\s+|however\s+|therefore\s+|so\s+|then\s+)"
        sub_sentences = re.split(split_pattern, sentence, flags=re.IGNORECASE)
        if len(sub_sentences) <= 1:
            words = sentence.split()
            current_part = []
            current_length = 0
            for word in words:
                if current_length + len(word) + 1 > max_length and current_part:
                    parts.append(" ".join(current_part))
                    current_part = [word]
                    current_length = len(word)
                else:
                    current_part.append(word)
                    current_length += len(word) + 1
            if current_part:
                parts.append(" ".join(current_part))
        else:
            current_part = []
            current_length = 0
            for sub in sub_sentences:
                sub_len = len(sub)
                if current_length + sub_len + 1 > max_length and current_part:
                    parts.append(" ".join(current_part))
                    current_part = [sub]
                    current_length = sub_len
                else:
                    current_part.append(sub)
                    current_length += sub_len + 1
            if current_part:
                parts.append(" ".join(current_part))
        return parts if parts else [sentence]

    def create_chunks_by_sentences(
        self,
        sentences: List[str],
        max_chunk_size: int = 4000,
        overlap_sentences: int = 2,
    ) -> List[str]:
        chunks = []
        current_chunk = []
        current_length = 0
        for i, sentence in enumerate(sentences):
            sentence_length = len(sentence)
            if sentence_length > max_chunk_size:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
                    current_length = 0
                sub_parts = self.split_long_sentence(sentence, max_chunk_size)
                chunks.extend(sub_parts)
                continue
            if current_length + sentence_length + 1 > max_chunk_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                overlap_start = max(0, len(current_chunk) - overlap_sentences)
                current_chunk = current_chunk[overlap_start:]
                current_length = sum(len(s) for s in current_chunk)
            current_chunk.append(sentence)
            current_length += sentence_length + 1
        if current_chunk:
            chunks.append(" ".join(current_chunk))
        return chunks

    def merge_broken_sentences(self, text: str) -> str:
        if not text:
            return text
        parts = [p.strip() for p in re.split(r"[\r\n]+", text) if p.strip()]
        if not parts:
            return text
        merged_parts = []
        for part in parts:
            if not merged_parts:
                merged_parts.append(part)
                continue
            prev = merged_parts[-1]
            if not re.search(r"[.!?…]\s*$", prev) and re.match(
                r"^[a-z0-9]", part, re.IGNORECASE
            ):
                merged_parts[-1] = prev + " " + part
            else:
                merged_parts.append(part)
        return " ".join(merged_parts)

    async def process_transcript(
        self,
        text: str = None,
        model="claude",
        model_name="claude-3-5-sonnet-latest",
        transcript_path: str = None,
        chunk_size: int = 5000,
        overlap: int = 1000,
        transcript_data: List[Dict] = None,
        speaker_context: str = None,
    ):
        try:
            if self.collection:
                try:
                    self.collection.delete(ids=self.collection.get()["ids"])
                except Exception as e:
                    logger.error(f"Error clearing collection: {e}")

            if transcript_data:
                logger.info(
                    f"Processing structured transcript data with {len(transcript_data)} segments"
                )
                transcript = self.preprocessor.preprocess(transcript_data)
            elif isinstance(transcript_path, str) and os.path.exists(transcript_path):
                with open(transcript_path, "r", encoding="utf-8") as f:
                    content = f.read()
                try:
                    parsed_data = json.loads(content)
                    if isinstance(parsed_data, list) and len(parsed_data) > 0:
                        if "start" in parsed_data[0] or "timestamp" in parsed_data[0]:
                            transcript = self.preprocessor.preprocess(parsed_data)
                        else:
                            transcript = content
                    else:
                        transcript = content
                except json.JSONDecodeError:
                    transcript = content
            else:
                transcript = text

            if not transcript or not transcript.strip():
                raise ValueError("No transcript content to process")

            transcript = self.merge_broken_sentences(transcript)
            logger.info(f"Processing transcript of length {len(transcript)} characters")

            sentences = self.split_into_sentences(transcript)
            logger.info(f"Split transcript into {len(sentences)} sentences")

            if model == "ollama":
                max_chunk_size = min(chunk_size, 2000)
                overlap_sentences = max(1, overlap // 500)
            else:
                max_chunk_size = chunk_size
                overlap_sentences = max(1, overlap // 500)

            chunks = self.create_chunks_by_sentences(
                sentences, max_chunk_size, overlap_sentences
            )
            logger.info(f"Created {len(chunks)} chunks")

            if not self.collection:
                self.initialize_collection()

            all_json_data = []

            if model == "claude":
                api_key = os.getenv("ANTHROPIC_API_KEY")
                if not api_key:
                    raise ValueError("ANTHROPIC_API_KEY not set")
                model_instance = AnthropicModel(model_name, api_key=api_key)
                agent = Agent(
                    model_instance,
                    result_type=EnhancedSummaryResponse,
                    result_retries=15,
                )
            elif model == "ollama":
                model_instance = OllamaModel(
                    model_name, base_url="http://localhost:11434/v1"
                )
                # 🔥 THÊM CẤU HÌNH TỐI ƯU CHO QWEN 2.5 TRÊN MAC M2
                agent = Agent(
                    model_instance,
                    result_type=EnhancedSummaryResponse,
                    result_retries=10,
                    model_settings={
                        "temperature": 0.1,  # Giữ AI trả về JSON chuẩn
                        "num_ctx": 16384,  # Đủ để đọc 20-30 phút họp
                    },
                )
            elif model == "groq":
                api_key = os.getenv("GROQ_API_KEY")
                if not api_key:
                    raise ValueError("GROQ_API_KEY not set")
                model_instance = GroqModel(model_name, api_key=api_key)
                agent = Agent(
                    model_instance,
                    result_type=EnhancedSummaryResponse,
                    result_retries=15,
                )
            else:
                raise ValueError(f"Invalid model: {model}")

            for i, chunk in enumerate(chunks):
                logger.info(
                    f"Processing chunk {i+1}/{len(chunks)} (length: {len(chunk)} chars)"
                )

                enhanced_prompt = f"""{ENHANCED_SYSTEM_PROMPT}

📌 THÔNG TIN NGƯỜI THAM GIA:
{speaker_context if speaker_context else "Chưa có thông tin người tham gia"}

📝 NỘI DUNG CHUNK {i+1}/{len(chunks)}:
{chunk}

Hãy phân tích chunk này và trả về JSON theo đúng format."""

                try:
                    summary = await agent.run(enhanced_prompt)
                    if hasattr(summary, "data"):
                        final_summary = summary.data
                    else:
                        final_summary = summary

                    if hasattr(final_summary, "model_dump"):
                        total_summary_in_json = json.dumps(
                            final_summary.model_dump(), indent=2, ensure_ascii=False
                        )
                    else:
                        total_summary_in_json = json.dumps(
                            final_summary, indent=2, ensure_ascii=False
                        )

                    all_json_data.append(total_summary_in_json)

                    self.collection.add(
                        documents=[chunk],
                        metadatas=[
                            {
                                "source": f"chunk_{i}",
                                "processed": False,
                                "type": "transcript",
                                "chunk_index": i,
                            }
                        ],
                        ids=[f"id_{i}"],
                    )
                    logger.info(f"Successfully processed chunk {i+1}")
                except Exception as e:
                    logger.error(
                        f"Error processing chunk {i+1}: {str(e)}", exc_info=True
                    )
                    continue

            logger.info(
                f"Successfully processed {len(all_json_data)}/{len(chunks)} chunks"
            )
            return len(all_json_data), all_json_data

        except Exception as e:
            logger.error(f"Error processing transcript: {str(e)}", exc_info=True)
            raise


class MeetingSummarizer:
    def __init__(self, api_key: str):
        self.model = AnthropicModel("claude-3-5-sonnet-latest", api_key=api_key)
        self.Agenda = Section(title="Agenda", blocks=[])
        self.Decisions = Section(title="Decisions", blocks=[])
        self.ActionItems = Section(title="Action Items", blocks=[])
        self.ClosingRemarks = Section(title="Closing Remarks", blocks=[])

    def create_block(
        self, title: str, content: str, block_type: str = "item", color: str = "default"
    ) -> Block:
        return Block(
            id=str(uuid.uuid4()), type=block_type, content=content, color=color
        )

    def add_action_item(self, ctx: RunContext, title: str, content: str):
        block = self.create_block(title, content, "action")
        self.ActionItems.blocks.append(block)
        return f"Successfully added action item: {block.id}"

    def add_agenda_item(self, ctx: RunContext, title: str, content: str):
        block = self.create_block(title, content, "agenda")
        self.Agenda.blocks.append(block)
        return f"Successfully added agenda item: {block.id}"

    def add_decision(self, ctx: RunContext, title: str, content: str):
        block = self.create_block(title, content, "decision")
        self.Decisions.blocks.append(block)
        return f"Successfully added decision: {block.id}"

    def generate_summary(self, ctx: RunContext) -> SummaryResponse:
        return SummaryResponse(
            Agenda=self.Agenda,
            Decisions=self.Decisions,
            ActionItems=self.ActionItems,
            ClosingRemarks=self.ClosingRemarks,
        )


SYSTEM_PROMPT = """You are a meeting summarizer agent. Your task is to:

1. EXTRACT INFORMATION
- Use query_transcript to get information about the meeting
- Ask one question at a time and wait for the response
- Process each response completely before making the next tool call
- IMPORTANT: Make only ONE tool call at a time and wait for its response
- If query_transcript returns "CHROMADB_EMPTY", proceed to finalization

2. ORGANIZE INFORMATION
After gathering information, organize it into:
- Agenda items (use add_agenda_item ONE at a time)
- Key decisions made (use add_decision ONE at a time)
- Action items assigned (use add_action_item ONE at a time)
- Any other important points

3. SAVE AND FINALIZE
- Use tools sequentially, waiting for each response
- Once all information is processed, call delete_processed_chunks
- Finally call get_final_summary

Available tools:
- query_transcript
- add_action_item
- add_agenda_item
- add_decision
- save_final_summary_result
- get_final_summary
- delete_processed_chunks

The transcript is stored in ChromaDB - use query_transcript to access it.
Remember to make only ONE tool call at a time and wait for its response.
If you get CHROMADB_EMPTY: All chunks have been processed,
please save the summary to a file and end the process by calling final_result.

Do not run after CHROMADB_EMPTY is received.
"""


summarizer = MeetingSummarizer(api_key=os.getenv("ANTHROPIC_API_KEY"))
processor = TranscriptProcessor()

agent = Agent(
    summarizer.model,
    result_type=SummaryResponse,
    result_retries=15,
    system_prompt=SYSTEM_PROMPT,
)


@agent.tool
async def query_transcript(ctx: RunContext, query: str) -> str:
    try:
        collection_data = processor.collection.get()
        if not collection_data["ids"]:
            return "CHROMADB_EMPTY: All chunks have been processed."

        results = processor.collection.query(query_texts=[query], n_results=1)

        if not results or not results["documents"] or not results["documents"][0]:
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
                processor.collection.delete(ids=chunk_ids)
                logger.info(f"Deleted {len(chunk_ids)} processed chunks")
                remaining = processor.collection.get()
                logger.info(f"Remaining chunks: {len(remaining['ids'])}")
            except Exception as e:
                logger.error(f"Error deleting chunks: {e}")
                return f"Error deleting chunks: {str(e)}"

        return combined_result.strip()

    except Exception as e:
        logger.error(f"Error querying transcript: {e}")
        return f"Error: {str(e)}"


@agent.tool
async def delete_processed_chunks(ctx: RunContext) -> str:
    try:
        if not hasattr(ctx, "processed_chunks") or not ctx.processed_chunks:
            return "No chunks to delete"
        chunk_ids = list(ctx.processed_chunks)
        processor.collection.delete(ids=chunk_ids)
        ctx.processed_chunks.clear()
        return f"Successfully deleted {len(chunk_ids)} chunks"
    except Exception as e:
        logger.error(f"Error deleting chunks: {e}")
        return f"Error deleting chunks: {str(e)}"


@agent.tool
async def add_action_item(ctx: RunContext, title: str, content: str) -> str:
    result = summarizer.add_action_item(ctx, title, content)
    return f"Successfully added action item: {result}"


@agent.tool
async def add_agenda_item(ctx: RunContext, title: str, content: str) -> str:
    result = summarizer.add_agenda_item(ctx, title, content)
    return f"Successfully added agenda item: {result}"


@agent.tool
async def add_decision(ctx: RunContext, title: str, content: str) -> str:
    result = summarizer.add_decision(ctx, title, content)
    return f"Successfully added decision: {result}"


@agent.tool
async def save_final_summary_result(ctx: RunContext) -> str:
    try:
        summary = summarizer.generate_summary(ctx)
        if not any(
            [
                summary.Agenda.blocks,
                summary.Decisions.blocks,
                summary.ActionItems.blocks,
                summary.ClosingRemarks.blocks,
            ]
        ):
            return "Error: No content found in summary. Please add some items first."
        json_data = summary.model_dump_json(indent=2)
        with open("final_summary_result.json", "w", encoding="utf-8") as f:
            f.write(json_data)
        return "Successfully saved final summary result to file"
    except Exception as e:
        logger.error(f"Error generating or saving summary: {e}")
        return f"Error processing summary: {str(e)}"


@agent.tool
async def get_final_summary(ctx: RunContext) -> SummaryResponse:
    return summarizer.generate_summary(ctx)


agent.tools = [
    query_transcript,
    add_action_item,
    add_agenda_item,
    add_decision,
    save_final_summary_result,
    get_final_summary,
    delete_processed_chunks,
]

logger.info("Initialized QA Agent")
