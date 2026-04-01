from chromadb import Client as ChromaClient, Settings
from groq import file_from_path
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

# Set up logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()  # Load environment variables from .env file


class Block(BaseModel):
    """Represents a block of content in a section
    Blcks are the basic blocks in this structure. one block contains only one item"""

    id: str
    type: str
    content: str
    color: str


class Section(BaseModel):
    """Represents a section in the meeting summary
    One section can have multiple blogs related to the title
    """

    title: str
    blocks: List[Block]


class ActionItem(BaseModel):
    """Represents an action item from the meeting"""

    title: str
    content: str


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


class MeetingMinutes(BaseModel):
    """Represents the meeting minutes response based on a section of the transcript.
    The information shall have stuff like what is discussed, important dates, etc
    The section shall not have sub sections but only a title and blocks. Remember to split sub sections and all to blocks
    """

    Section1: Section
    Section2: Section
    Section3: Section
    Section4: Section


class OverallSummary(BaseModel):
    """Represents the complete meeting summary"""

    Agenda: str
    CriticalDeadlines: Section
    KeyItemsDecisions: Section
    ImmediateActionItems: Section
    NextSteps: Section
    ClosingRemarks: Section


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
            # If timestamp parsing fails, return as is
            return transcript_data

    def remove_duplicates(self, transcript_data: List[Dict]) -> List[Dict]:
        """Remove duplicate transcript entries"""
        seen_texts = set()
        unique_entries = []

        for entry in transcript_data:
            text = entry.get("text", "").strip()
            # Normalize text for comparison
            normalized = " ".join(text.lower().split())

            if normalized and normalized not in seen_texts:
                seen_texts.add(normalized)
                unique_entries.append(entry)
            elif not normalized:
                # Skip empty text entries
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

            # If same speaker and time gap is small, merge
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

        # Remove special markers like *Dog barks*, [laughter], etc.
        text = re.sub(r"\*.*?\*", "", text)
        text = re.sub(r"\[.*?\]", "", text)
        text = re.sub(r"\(.*?\)", "", text)

        # Remove multiple spaces
        text = re.sub(r"\s+", " ", text)

        # Remove leading/trailing spaces
        text = text.strip()

        return text

    def preprocess(self, transcript_data: List[Dict]) -> str:
        """Main preprocessing pipeline"""
        self.logger.info(f"Raw transcript has {len(transcript_data)} segments")

        # Step 1: Clean individual texts
        for entry in transcript_data:
            entry["text"] = self.clean_text(entry.get("text", ""))

        # Filter out entries with empty text after cleaning
        transcript_data = [
            entry for entry in transcript_data if entry.get("text", "").strip()
        ]

        # Step 2: Sort by timestamp
        sorted_data = self.sort_by_timestamp(transcript_data)

        # Step 3: Remove duplicates
        unique_data = self.remove_duplicates(sorted_data)
        self.logger.info(f"After removing duplicates: {len(unique_data)} segments")

        # Step 4: Merge adjacent segments
        merged_data = self.merge_adjacent_segments(unique_data)
        self.logger.info(f"After merging adjacent: {len(merged_data)} segments")

        # Step 5: Combine into final text
        full_text = " ".join([entry.get("text", "") for entry in merged_data])

        # Final cleanup
        full_text = re.sub(r"\s+", " ", full_text).strip()

        self.logger.info(f"Final preprocessed text length: {len(full_text)} characters")

        return full_text


# ==================== END TRANSCRIPT PREPROCESSOR ====================


class TranscriptProcessor:
    """Handles the processing and storage of meeting transcripts"""

    def __init__(self):
        """Initialize the transcript processor"""
        self.collection_name = "all_transcripts"
        self.chroma_client = None
        self.collection = None
        self.preprocessor = TranscriptPreprocessor()  # Initialize preprocessor
        self.initialize_collection()

    def __del__(self):
        """Cleanup ChromaDB connection"""
        if self.chroma_client:
            try:
                self.collection = None
                self.chroma_client = None
            except Exception as e:
                logger.error(f"Error cleaning up ChromaDB: {e}")

    def initialize_collection(self):
        """Initialize or get the ChromaDB collection"""
        try:
            if self.chroma_client:
                self.collection = None
                self.chroma_client = None

            # Create new client with settings
            settings = Settings(allow_reset=True, is_persistent=True)
            self.chroma_client = ChromaClient(settings)

            try:
                # Try to get existing collection
                self.collection = self.chroma_client.get_collection(
                    name=self.collection_name
                )
                logger.info(f"Retrieved existing collection: {self.collection_name}")
            except Exception:
                # Create new collection if it doesn't exist
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
        """Split text into sentences using regex for multiple languages"""
        # Pattern for sentence endings with common delimiters
        # Supports . ! ? ... and handles quotes, brackets
        pattern = r"(?<=[.!?…])\s+(?=[A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼỀỀỂẾỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỴÝỶỸ])|(?<=[.!?…])\s*$"

        # First, split by sentence endings
        sentences = re.split(pattern, text)

        # Clean up sentences
        sentences = [s.strip() for s in sentences if s.strip()]

        # If no sentences found using pattern, try alternative approach
        if not sentences:
            # Split by common sentence delimiters
            sentences = re.split(r"[.!?…]\s+", text)
            sentences = [
                s.strip() + "." if not s.endswith((".", "!", "?")) else s.strip()
                for s in sentences
                if s.strip()
            ]

        # Filter out empty sentences
        sentences = [s for s in sentences if s and len(s) > 1]

        return sentences

    def split_long_sentence(self, sentence: str, max_length: int) -> List[str]:
        """Split a very long sentence into smaller parts"""
        parts = []

        # Try to split by commas, semicolons, or conjunctions
        split_pattern = r"(?<=[,;])\s+|(?<=\s)(?=and\s+|but\s+|or\s+|however\s+|therefore\s+|so\s+|then\s+)"
        sub_sentences = re.split(split_pattern, sentence, flags=re.IGNORECASE)

        if len(sub_sentences) <= 1:
            # If can't split by punctuation, split by words
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
            # Group sub-sentences into chunks
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
        """Create chunks by grouping sentences, ensuring no sentence is cut"""
        chunks = []
        current_chunk = []
        current_length = 0

        for i, sentence in enumerate(sentences):
            sentence_length = len(sentence)

            # If a single sentence is longer than max_chunk_size, split it
            if sentence_length > max_chunk_size:
                # First add current chunk if not empty
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
                    current_length = 0

                # Split long sentence into smaller parts
                sub_parts = self.split_long_sentence(sentence, max_chunk_size)
                chunks.extend(sub_parts)
                continue

            # If adding this sentence would exceed max_chunk_size
            if current_length + sentence_length + 1 > max_chunk_size and current_chunk:
                # Save current chunk
                chunks.append(" ".join(current_chunk))

                # Add overlap sentences
                overlap_start = max(0, len(current_chunk) - overlap_sentences)
                current_chunk = current_chunk[overlap_start:]
                current_length = sum(len(s) for s in current_chunk)

            # Add current sentence
            current_chunk.append(sentence)
            current_length += sentence_length + 1  # +1 for space

        # Add the last chunk if any
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        # Log chunk sizes for debugging
        for i, chunk in enumerate(chunks):
            logger.debug(
                f"Chunk {i} size: {len(chunk)} characters, {len(chunk.split())} words"
            )

        return chunks

    async def process_transcript(
        self,
        text: str = None,
        model="claude",
        model_name="claude-3-5-sonnet-latest",
        transcript_path: str = None,
        chunk_size: int = 5000,
        overlap: int = 1000,
        transcript_data: List[Dict] = None,  # New parameter for structured data
    ):
        """Process and store transcript in chunks using sentence-based splitting

        Args:
            text: Plain text transcript
            model: Model to use (claude, ollama, groq)
            model_name: Specific model name
            transcript_path: Path to transcript file
            chunk_size: Size of chunks in characters
            overlap: Overlap between chunks
            transcript_data: Structured transcript data with timestamps and speaker info
        """
        try:
            # Clear any existing collection
            if self.collection:
                try:
                    self.collection.delete(ids=self.collection.get()["ids"])
                except Exception as e:
                    logger.error(f"Error clearing collection: {e}")

            # Load and preprocess transcript
            if transcript_data:
                # Nếu có dữ liệu transcript đã được parse sẵn (có timestamp)
                logger.info(
                    f"Processing structured transcript data with {len(transcript_data)} segments"
                )
                transcript = self.preprocessor.preprocess(transcript_data)
                logger.info(f"Preprocessed transcript to {len(transcript)} characters")
            elif isinstance(transcript_path, str):
                if os.path.exists(transcript_path):
                    with open(transcript_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    # Try to parse as JSON (structured transcript)
                    try:
                        parsed_data = json.loads(content)
                        if isinstance(parsed_data, list) and len(parsed_data) > 0:
                            # Check if it has timestamp fields
                            if (
                                "start" in parsed_data[0]
                                or "timestamp" in parsed_data[0]
                            ):
                                logger.info(
                                    "Detected JSON transcript with timestamps, applying preprocessing"
                                )
                                transcript = self.preprocessor.preprocess(parsed_data)
                            else:
                                transcript = content
                        else:
                            transcript = content
                    except json.JSONDecodeError:
                        # Plain text file
                        transcript = content

                    logger.info(f"Loaded transcript from file: {transcript_path}")
                else:
                    transcript = transcript_path
            else:
                transcript = text

            # If transcript is still None or empty
            if not transcript or not transcript.strip():
                raise ValueError("No transcript content to process")

            logger.info(f"Processing transcript of length {len(transcript)} characters")
            logger.debug(f"Transcript preview: {transcript[:500]}...")

            # Split into sentences
            sentences = self.split_into_sentences(transcript)
            logger.info(f"Split transcript into {len(sentences)} sentences")

            # Calculate optimal chunk_size based on model
            if model == "ollama":
                # Ollama has smaller context window, use smaller chunks
                max_chunk_size = min(chunk_size, 2000)
                overlap_sentences = max(
                    1, overlap // 500
                )  # Convert overlap to number of sentences
            else:
                # Claude and Groq have larger context windows
                max_chunk_size = chunk_size
                overlap_sentences = max(
                    1, overlap // 500
                )  # Convert overlap to number of sentences

            logger.info(
                f"Using max_chunk_size={max_chunk_size}, overlap_sentences={overlap_sentences}"
            )

            # Create chunks by grouping sentences
            chunks = self.create_chunks_by_sentences(
                sentences, max_chunk_size, overlap_sentences
            )
            logger.info(f"Created {len(chunks)} chunks")

            # Log first few chunks for debugging
            for i in range(min(3, len(chunks))):
                logger.debug(f"Chunk {i} preview: {chunks[i][:100]}...")

            # Add chunks to collection
            if not self.collection:
                self.initialize_collection()

            all_json_data = []

            # Initialize model
            if model == "claude":
                api_key = os.getenv("ANTHROPIC_API_KEY")
                if not api_key:
                    raise ValueError("ANTHROPIC_API_KEY not set in environment")
                model_instance = AnthropicModel(model_name, api_key=api_key)
                agent = Agent(
                    model_instance,
                    result_type=SummaryResponse,
                    result_retries=15,
                )
            elif model == "ollama":
                model_instance = OllamaModel(model_name)
                agent = Agent(
                    model_instance,
                    result_type=SummaryResponse,
                    result_retries=15,
                )
            elif model == "groq":
                api_key = os.getenv("GROQ_API_KEY")
                if not api_key:
                    raise ValueError("GROQ_API_KEY not set in environment")
                model_instance = GroqModel(model_name, api_key=api_key)
                agent = Agent(
                    model_instance,
                    result_type=SummaryResponse,
                    result_retries=15,
                )
            else:
                raise ValueError(f"Invalid model: {model}")

            # Process each chunk
            for i, chunk in enumerate(chunks):
                logger.info(
                    f"Processing chunk {i+1}/{len(chunks)} (length: {len(chunk)} chars, {len(chunk.split())} words)"
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
                        logger.info(f"Successfully generated summary for chunk {i+1}")
                    else:
                        final_summary = summary
                        logger.info(f"Successfully generated summary for chunk {i+1}")

                    # Convert to JSON
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
                    # Continue with next chunk instead of failing completely
                    continue

            logger.info(
                f"Successfully processed {len(all_json_data)}/{len(chunks)} chunks"
            )
            return len(all_json_data), all_json_data

        except Exception as e:
            logger.error(f"Error processing transcript: {str(e)}", exc_info=True)
            raise


class MeetingSummarizer:
    """Handles the meeting summarization using AI models"""

    def __init__(self, api_key: str):
        self.model = AnthropicModel("claude-3-5-sonnet-latest", api_key=api_key)
        self.Agenda = Section(title="Agenda", blocks=[])
        self.Decisions = Section(title="Decisions", blocks=[])
        self.ActionItems = Section(title="Action Items", blocks=[])
        self.ClosingRemarks = Section(title="Closing Remarks", blocks=[])

    def create_block(
        self, title: str, content: str, block_type: str = "item", color: str = "default"
    ) -> Block:
        """Create a new block with a unique ID"""
        return Block(
            id=str(uuid.uuid4()), type=block_type, content=content, color=color
        )

    def add_action_item(self, ctx: RunContext, title: str, content: str):
        """Add an action item to the summary"""
        block = self.create_block(title, content, "action")
        self.ActionItems.blocks.append(block)
        return f"Successfully added action item: {block.id}"

    def add_agenda_item(self, ctx: RunContext, title: str, content: str):
        """Add an agenda item to the summary"""
        block = self.create_block(title, content, "agenda")
        self.Agenda.blocks.append(block)
        return f"Successfully added agenda item: {block.id}"

    def add_decision(self, ctx: RunContext, title: str, content: str):
        """Add a decision to the summary"""
        block = self.create_block(title, content, "decision")
        self.Decisions.blocks.append(block)
        return f"Successfully added decision: {block.id}"

    def generate_summary(self, ctx: RunContext) -> SummaryResponse:
        """Generate the final summary response"""
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

# Initialize components
summarizer = MeetingSummarizer(api_key=os.getenv("ANTHROPIC_API_KEY"))
processor = TranscriptProcessor()

# Create an agent first
agent = Agent(
    summarizer.model,
    result_type=SummaryResponse,
    result_retries=15,
    system_prompt=SYSTEM_PROMPT,
)


# Define tools
@agent.tool
async def query_transcript(ctx: RunContext, query: str) -> str:
    """Query the transcript to extract information. Returns the content and chunk IDs for deletion."""
    try:
        # Check if there are any chunks left
        collection_data = processor.collection.get()
        if not collection_data["ids"]:
            return "CHROMADB_EMPTY: All chunks have been processed."

        # Get unprocessed chunks
        results = processor.collection.query(query_texts=[query], n_results=1)

        if not results or not results["documents"] or not results["documents"][0]:
            return "No results found for the query"

        # Process and immediately delete chunks
        combined_result = ""
        chunk_ids = []

        for doc, metadata, id in zip(
            results["documents"][0], results["metadatas"][0], results["ids"][0]
        ):
            combined_result += f"\n{doc}\n"
            chunk_ids.append(id)

        # Delete the chunks we just processed
        if chunk_ids:
            try:
                processor.collection.delete(ids=chunk_ids)
                logger.info(f"Deleted {len(chunk_ids)} processed chunks")

                # Verify deletion
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

        # Clear the processed chunks
        ctx.processed_chunks.clear()

        return f"Successfully deleted {len(chunk_ids)} chunks"

    except Exception as e:
        logger.error(f"Error deleting chunks: {e}")
        return f"Error deleting chunks: {str(e)}"


@agent.tool
async def add_action_item(ctx: RunContext, title: str, content: str) -> str:
    """Add an action item to the summary"""
    result = summarizer.add_action_item(ctx, title, content)
    return f"Successfully added action item: {result}"


@agent.tool
async def add_agenda_item(ctx: RunContext, title: str, content: str) -> str:
    """Add an agenda item to the summary"""
    result = summarizer.add_agenda_item(ctx, title, content)
    return f"Successfully added agenda item: {result}"


@agent.tool
async def add_decision(ctx: RunContext, title: str, content: str) -> str:
    """Add a decision to the summary"""
    result = summarizer.add_decision(ctx, title, content)
    return f"Successfully added decision: {result}"


@agent.tool
async def save_final_summary_result(ctx: RunContext) -> str:
    """
    Save the final meeting summary result to a file
    args:
        ctx (RunContext): The run context

    returns:
        str: Status message indicating success or failure
    """
    try:
        # Get the final summary result
        summary = summarizer.generate_summary(ctx)

        # Validate summary has content
        if not any(
            [
                summary.Agenda.blocks,
                summary.Decisions.blocks,
                summary.ActionItems.blocks,
                summary.ClosingRemarks.blocks,
            ]
        ):
            return "Error: No content found in summary. Please add some items first."

        # Convert to JSON using Pydantic's json() method which handles nested models
        json_data = summary.model_dump_json(indent=2)

        # Save to file with error handling
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


@agent.tool
async def get_final_summary(ctx: RunContext) -> SummaryResponse:
    """Get the final meeting summary result"""
    return summarizer.generate_summary(ctx)


# Update agent with tools after they are defined
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


def pretty_print_json(obj):
    """Utility function to pretty print JSON objects"""
    if hasattr(obj, "model_dump_json"):
        print(obj.model_dump_json(indent=2))
    else:
        print(json.dumps(obj, indent=2, ensure_ascii=False))


# Example usage
if __name__ == "__main__":
    try:
        # Set up argument parser
        parser = argparse.ArgumentParser(
            description="Process a meeting transcript using AI."
        )
        parser.add_argument(
            "--transcript_path", type=str, help="Path to the transcript file"
        )
        parser.add_argument(
            "--model",
            type=str,
            default="claude",
            choices=["groq", "claude", "ollama"],
            help="Model to use for processing (default: claude)",
        )
        parser.add_argument(
            "--model-name",
            type=str,
            default="claude-3-5-sonnet-latest",
            help="Name of the model to use for processing (default: claude-3-5-sonnet-latest)",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=5000,
            help="Size of the chunks to be used for processing (default: 5000)",
        )
        parser.add_argument(
            "--overlap",
            type=int,
            default=1000,
            help="Overlap between the chunks to be used for processing (default: 1000)",
        )
        args = parser.parse_args()

        # Validate transcript path
        if not os.path.exists(args.transcript_path):
            raise ValueError(f"File not found: {args.transcript_path}")
        elif not os.path.isfile(args.transcript_path):
            raise ValueError(f"Path is not a file: {args.transcript_path}")
        else:
            logger.info(f"File exists and is a file: {args.transcript_path}")

        # Set up async loop
        import asyncio

        loop = asyncio.get_event_loop()

        # Process transcript
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
        logger.info(f"Successfully processed transcript into {len(all_json)} chunks")

        # Create a new JSON object for final summary
        final_summary = {
            "MeetingName": "",
            "SectionSummary": {"title": "Section Summary", "blocks": []},
            "CriticalDeadlines": {"title": "Critical Deadlines", "blocks": []},
            "KeyItemsDecisions": {"title": "Key Items & Decisions", "blocks": []},
            "ImmediateActionItems": {"title": "Immediate Action Items", "blocks": []},
            "NextSteps": {"title": "Next Steps", "blocks": []},
            "OtherImportantPoints": {"title": "Other Important Points", "blocks": []},
            "ClosingRemarks": {"title": "Closing Remarks", "blocks": []},
        }

        # Save raw JSON
        with open("all_json.json", "w", encoding="utf-8") as f:
            json.dump(all_json, f, indent=2, ensure_ascii=False)

        # Combine all JSON objects
        for json_obj in all_json:
            logger.info(f"Processing JSON object")
            json_dict = json.loads(json_obj)
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

        logger.info(
            f"Final summary created with {len(final_summary['SectionSummary']['blocks'])} total blocks"
        )

        # Save final summary
        final_summary_str = json.dumps(final_summary, indent=2, ensure_ascii=False)
        with open("final_summary.json", "w", encoding="utf-8") as f:
            f.write(final_summary_str)

        logger.info(f"Final summary saved to final_summary.json")

    except Exception as e:
        logger.error(f"Error during summarization: {str(e)}", exc_info=True)
        processor.cleanup()
        exit(1)
