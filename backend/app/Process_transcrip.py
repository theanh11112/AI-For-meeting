from chromadb import Client as ChromaClient, Settings
from pydantic import BaseModel
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

# ==================== IMPORT MODEL MANAGER ====================
from .model_config import model_manager

# Set up logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()  # Load environment variables from .env file


class Block(BaseModel):
    """Represents a block of content in a section"""

    id: str
    type: str
    content: str
    color: str


class Section(BaseModel):
    """Represents a section in the meeting summary"""

    title: str
    blocks: List[Block]


class SummaryResponse(BaseModel):
    """Represents the meeting summary response based on a section of the transcript"""

    MeetingName: str
    SectionSummary: Section
    CriticalDeadlines: Section
    KeyItemsDecisions: Section
    ImmediateActionItems: Section
    NextSteps: Section
    OtherImportantPoints: Section
    ClosingRemarks: Section
    IndividualTasks: Section


# ==================== TRANSCRIPT PREPROCESSOR ====================
class TranscriptPreprocessor:
    """Preprocess transcript before chunking"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def sort_by_timestamp(self, transcript_data: List[Dict]) -> List[Dict]:
        """Sort transcript entries by timestamp"""
        try:
            return sorted(transcript_data, key=lambda x: float(x.get("start", 0)))
        except (ValueError, TypeError):
            return transcript_data

    def remove_duplicates(self, transcript_data: List[Dict]) -> List[Dict]:
        """Remove duplicate transcript entries"""
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
        """Merge adjacent segments if they are from same speaker and close in time"""
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
        """Clean transcript text"""
        if not text:
            return ""
        text = re.sub(r"\*.*?\*", "", text)
        text = re.sub(r"\[.*?\]", "", text)
        text = re.sub(r"\(.*?\)", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def preprocess(self, transcript_data: List[Dict]) -> str:
        """Main preprocessing pipeline"""
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
    """Handles the processing and storage of meeting transcripts"""

    def __init__(self):
        self.collection_name = "all_transcripts"
        self.chroma_client = None
        self.collection = None
        self.preprocessor = TranscriptPreprocessor()
        self.initialize_collection()

    def initialize_collection(self):
        """Initialize or get the ChromaDB collection"""
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
        """Cleanup ChromaDB resources"""
        if self.chroma_client:
            try:
                self.collection = None
                self.chroma_client = None
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")

    def split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences using regex"""
        pattern = r"(?<=[.!?…])\s+(?=[A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼỀỀỂẾỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỴÝỶỸ])|(?<=[.!?…])\s*$"
        sentences = re.split(pattern, text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            sentences = re.split(r"[.!?…]\s+", text)
            sentences = [
                s.strip() + "." if not s.endswith((".", "!", "?")) else s.strip()
                for s in sentences
                if s.strip()
            ]

        return [s for s in sentences if s and len(s) > 1]

    def split_long_sentence(self, sentence: str, max_length: int) -> List[str]:
        """Split a very long sentence into smaller parts"""
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
        """Create chunks by grouping sentences"""
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
        """Merge sentence fragments that were split across chunk boundaries"""
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
        model="groq",
        model_name="llama-3.3-70b-versatile",
        transcript_path: str = None,
        chunk_size: int = 20000,
        overlap: int = 1000,
        transcript_data: List[Dict] = None,
    ):
        """Process and store transcript in chunks using ModelManager for intelligent selection"""
        try:
            # Clear any existing collection
            if self.collection:
                try:
                    self.collection.delete(ids=self.collection.get()["ids"])
                except Exception as e:
                    logger.error(f"Error clearing collection: {e}")

            # Load and preprocess transcript
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

            logger.info(f"Raw transcript length: {len(transcript)} chars")
            transcript = self.merge_broken_sentences(transcript)
            logger.info(f"After merge, length: {len(transcript)} chars")

            # Split into sentences
            sentences = self.split_into_sentences(transcript)
            logger.info(f"Split transcript into {len(sentences)} sentences")

            # Sử dụng ModelManager để chọn model
            preferred_model = None
            if model == "groq":
                preferred_model = "llama-3.3-70b-versatile"
            elif model == "ollama":
                preferred_model = "qwen2.5:7b"

            model_info = await model_manager.get_available_model(
                preferred_model=preferred_model
            )
            config = model_info["config"]
            logger.info(
                f"Selected model: {config['name']} (provider: {config['provider']})"
            )

            # Tự động điều chỉnh chunk size dựa trên provider
            if config["provider"] == "ollama":
                max_chunk_size = min(chunk_size, 3000)
                overlap_sentences = max(1, overlap // 500)
                logger.info(f"Using smaller chunk size for Ollama: {max_chunk_size}")
            else:
                max_chunk_size = chunk_size
                overlap_sentences = max(2, overlap // 500)
                logger.info(f"Using normal chunk size for Groq: {max_chunk_size}")

            # Create chunks
            chunks = self.create_chunks_by_sentences(
                sentences, max_chunk_size, overlap_sentences
            )
            logger.info(f"Created {len(chunks)} chunks")

            # Initialize collection and agent
            if not self.collection:
                self.initialize_collection()

            all_json_data = []

            # Khởi tạo agent dựa trên provider thực tế
            if config["provider"] == "groq":
                api_key = os.getenv("GROQ_API_KEY")
                if not api_key:
                    raise ValueError("GROQ_API_KEY not set in environment")
                model_instance = GroqModel(config["name"], api_key=api_key)
                agent = Agent(
                    model_instance,
                    result_type=SummaryResponse,
                    result_retries=config.get("max_retries", 3),
                )
            elif config["provider"] == "ollama":
                model_instance = OllamaModel(config["name"])
                agent = Agent(
                    model_instance,
                    result_type=SummaryResponse,
                    result_retries=config.get("max_retries", 2),
                )
            else:
                raise ValueError(f"Invalid provider: {config['provider']}")

            # Process each chunk
            for i, chunk in enumerate(chunks):
                logger.info(
                    f"Processing chunk {i+1}/{len(chunks)} (length: {len(chunk)} chars)"
                )

                try:
                    summary = await agent.run(
                        f"""Given is a meeting transcript chunk. Please provide a structured summary.
                        If no data for a section, return an empty block array.
                        Each block content should be descriptive and maintain context from the chunk.
                        
                        Transcript chunk:
                        {chunk}
                        
                        Return only JSON, no other text.""",
                    )

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

                    # Add to ChromaDB
                    self.collection.add(
                        documents=[chunk],
                        metadatas=[
                            {
                                "source": f"chunk_{i}",
                                "processed": False,
                                "type": "transcript",
                                "chunk_index": i,
                                "summary": total_summary_in_json,
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


# ==================== MEETING SUMMARIZER ====================
class MeetingSummarizer:
    """Handles the meeting summarization using AI models"""

    def __init__(self, api_key: str = None):
        self.Agenda = Section(title="Agenda", blocks=[])
        self.Decisions = Section(title="Decisions", blocks=[])
        self.ActionItems = Section(title="Action Items", blocks=[])
        self.ClosingRemarks = Section(title="Closing Remarks", blocks=[])
        self.IndividualTasks = Section(title="Individual Tasks", blocks=[])

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

    def add_individual_task(
        self, ctx: RunContext, assignee: str, task: str, deadline: str = None
    ):
        """Add an individual task assigned to a specific person"""
        content = f"[{assignee}]: {task}"
        if deadline:
            content += f" (Deadline: {deadline})"
        block = self.create_block(assignee, content, "task")
        self.IndividualTasks.blocks.append(block)
        return f"Successfully added task for {assignee}: {block.id}"

    def generate_summary(self, ctx: RunContext) -> SummaryResponse:
        return SummaryResponse(
            MeetingName="",
            SectionSummary=Section(title="Section Summary", blocks=[]),
            CriticalDeadlines=Section(title="Critical Deadlines", blocks=[]),
            KeyItemsDecisions=Section(title="Key Items & Decisions", blocks=[]),
            ImmediateActionItems=Section(title="Immediate Action Items", blocks=[]),
            NextSteps=Section(title="Next Steps", blocks=[]),
            OtherImportantPoints=Section(title="Other Important Points", blocks=[]),
            ClosingRemarks=self.ClosingRemarks,
            IndividualTasks=self.IndividualTasks,
        )


# ==================== SYSTEM PROMPT TỐI ƯU CHO EMAIL AGENT ====================
SYSTEM_PROMPT = """You are a professional meeting assistant. Your task is to extract information and organize it into sections.

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
- Individual tasks assigned to specific people (use add_individual_task ONE at a time)
- Any other important points

3. ⚠️ CRITICAL FORMAT FOR INDIVIDUAL TASKS ⚠️
When using add_individual_task, you MUST format task with assignee as the person's name.

The add_individual_task function will automatically format as: [Assignee Name]: Task description (Deadline: date)

For example, if you call:
add_individual_task(assignee="Anne", task="Learn more about offset printing", deadline="tomorrow")

It will create: "[Anne]: Learn more about offset printing (Deadline: tomorrow)"

RULES for assignee:
- Use the person's real name if mentioned (Anne, John, Mr. Richardson)
- Use speaker tags like "Người 01" if name is unknown
- ALWAYS use add_individual_task for tasks with a specific assignee
- NEVER put multiple tasks in one add_individual_task call

RULES for deadline:
- Extract deadline if mentioned in transcript
- If deadline is mentioned like "ngày mai", "tomorrow", "next week", include it
- If no deadline mentioned, leave deadline as None (it will show as "ASAP")

RULES for task:
- Be specific and concise
- Capture the exact action item from the transcript
- Start with a verb if possible

4. SAVE AND FINALIZE
- Use tools sequentially, waiting for each response
- Once all information is processed, call delete_processed_chunks
- Finally call get_final_summary

Available tools:
- query_transcript - Query the ChromaDB for transcript chunks
- add_action_item - Add a general action item
- add_agenda_item - Add an agenda item
- add_decision - Add a decision made in the meeting
- add_individual_task - ADD TASKS FOR SPECIFIC PEOPLE (USE THIS!)
- save_final_summary_result - Save summary to file
- get_final_summary - Get the complete summary
- delete_processed_chunks - Clean up processed chunks

The transcript is stored in ChromaDB - use query_transcript to access it.
Remember to make only ONE tool call at a time and wait for its response.
If you get CHROMADB_EMPTY: All chunks have been processed,
please save the summary to a file and end the process by calling get_final_summary.

Do not run after CHROMADB_EMPTY is received.
"""


# ==================== KHỞI TẠO SINGLETON ====================
processor = TranscriptProcessor()
summarizer = MeetingSummarizer(api_key=None)

_default_model = OllamaModel("qwen2.5:7b")
agent = Agent(
    _default_model,
    result_type=SummaryResponse,
    result_retries=15,
    system_prompt=SYSTEM_PROMPT,
)


# ==================== ĐỊNH NGHĨA TOOLS ====================
@agent.tool
async def query_transcript(ctx: RunContext, query: str) -> str:
    """Query the transcript to extract information."""
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
    """Delete all processed chunks from the collection"""
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
async def add_individual_task(
    ctx: RunContext, assignee: str, task: str, deadline: str = None
) -> str:
    """Add a task assigned to a specific individual"""
    result = summarizer.add_individual_task(ctx, assignee, task, deadline)
    return result


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
                summary.IndividualTasks.blocks,
            ]
        ):
            return "Error: No content found in summary."

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


# Gán tools cho agent
agent.tools = [
    query_transcript,
    add_action_item,
    add_agenda_item,
    add_decision,
    add_individual_task,
    save_final_summary_result,
    get_final_summary,
    delete_processed_chunks,
]

logger.info("✅ Initialized Transcript Processor and Agent with ModelManager support")


def initialize_agent_with_model(
    api_key: str, model_name: str = "llama-3.3-70b-versatile"
):
    """Khởi tạo agent với model phù hợp (được gọi từ main.py)"""
    global agent

    if api_key and api_key.startswith("gsk_"):
        model_instance = GroqModel(model_name, api_key=api_key)
        logger.info(f"Agent initialized with GroqModel: {model_name}")
    elif api_key and api_key.startswith("sk-ant"):
        model_instance = AnthropicModel("claude-3-5-sonnet-latest", api_key=api_key)
        logger.info("Agent initialized with AnthropicModel: Claude 3.5 Sonnet")
    else:
        model_instance = OllamaModel("qwen2.5:7b")
        logger.info("Agent initialized with OllamaModel: Qwen 2.5 7B")

    agent = Agent(
        model_instance,
        result_type=SummaryResponse,
        result_retries=15,
        system_prompt=SYSTEM_PROMPT,
    )

    agent.tools = [
        query_transcript,
        add_action_item,
        add_agenda_item,
        add_decision,
        add_individual_task,
        save_final_summary_result,
        get_final_summary,
        delete_processed_chunks,
    ]

    return agent, summarizer


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(
            description="Process a meeting transcript using AI."
        )
        parser.add_argument(
            "--transcript_path", type=str, help="Path to the transcript file"
        )
        parser.add_argument(
            "--model", type=str, default="groq", choices=["groq", "claude", "ollama"]
        )
        parser.add_argument("--model-name", type=str, default="llama-3.3-70b-versatile")
        parser.add_argument("--chunk-size", type=int, default=20000)
        parser.add_argument("--overlap", type=int, default=1000)
        args = parser.parse_args()

        if not os.path.exists(args.transcript_path):
            raise ValueError(f"File not found: {args.transcript_path}")

        import asyncio

        loop = asyncio.get_event_loop()

        num_chunks, all_json = loop.run_until_complete(
            processor.process_transcript(
                model=args.model,
                model_name=args.model_name,
                transcript_path=args.transcript_path,
                chunk_size=args.chunk_size,
                overlap=args.overlap,
            )
        )
        logger.info(f"Processed transcript into {num_chunks} chunks")

    except Exception as e:
        logger.error(f"Error during summarization: {str(e)}", exc_info=True)
        processor.cleanup()
        exit(1)
