# backend/app/services/speaker_mapper.py
from app.models.user_map import meeting_directory
from typing import Dict, List, Optional
from datetime import datetime


def map_speakers_to_real_names(transcript_data: dict) -> dict:
    """Thay thế 'SPEAKER_00' thành tên thật trong toàn bộ văn bản"""
    mapped_segments = []
    full_text_with_names = []

    for seg in transcript_data.get("segments", []):
        speaker_id = seg.get("speaker", "UNKNOWN")
        start_time = seg.get("start", 0)
        end_time = seg.get("end", 0)

        participant = meeting_directory.get_participant(speaker_id)

        if participant:
            real_name = participant.name
        else:
            real_name = speaker_id

        mapped_segments.append(
            {
                "start": start_time,
                "end": end_time,
                "speaker_id": speaker_id,
                "speaker_name": real_name,
                "text": seg["text"],
            }
        )

        full_text_with_names.append(
            f"[{real_name}] {start_time:.1f}s - {end_time:.1f}s: {seg['text']}"
        )

    return {"segments": mapped_segments, "full_text": "\n".join(full_text_with_names)}


def get_speaker_info(speaker_id: str) -> Optional[dict]:
    """Lấy thông tin của một speaker cụ thể"""
    participant = meeting_directory.get_participant(speaker_id)
    if participant:
        return {
            "speaker_id": participant.speaker_id,
            "name": participant.name,
            "email": participant.email,
        }
    return None


def get_all_speakers() -> List[dict]:
    """Lấy danh sách tất cả speakers đã được mapping"""
    return [
        {"speaker_id": p.speaker_id, "name": p.name, "email": p.email}
        for p in meeting_directory.get_all_participants()
    ]


def get_speaker_email_by_name(name: str) -> Optional[str]:
    """Tìm email của người tham gia dựa vào tên"""
    for participant in meeting_directory.get_all_participants():
        if participant.name.lower() == name.lower():
            return participant.email
    return None


def get_speaker_name_by_id(speaker_id: str) -> str:
    """Lấy tên thật từ speaker_id"""
    participant = meeting_directory.get_participant(speaker_id)
    return participant.name if participant else speaker_id


def format_transcript_for_ai(
    transcript_data: dict, include_timestamps: bool = True
) -> str:
    """Format transcript để gửi cho AI Agent"""
    if include_timestamps:
        return transcript_data.get("full_text", "")

    lines = []
    for seg in transcript_data.get("segments", []):
        lines.append(f"[{seg['speaker_name']}]: {seg['text']}")
    return "\n".join(lines)


def get_participant_context() -> str:
    """
    🔥 HÀM MỚI: Lấy context đầy đủ về người tham gia cho LLM

    Returns:
        Chuỗi chứa danh sách người tham gia với email
    """
    speakers = get_all_speakers()
    current_date = datetime.now().strftime("%d/%m/%Y")

    context = f"Ngày họp: {current_date}\n"
    context += "Danh sách người tham gia:\n"

    for s in speakers:
        email_display = s.get("email", "❌ Chưa có email")
        context += f"- {s['name']} (Email: {email_display})\n"

    missing_emails = [s["name"] for s in speakers if not s.get("email")]
    if missing_emails:
        context += (
            f"\n⚠️ LƯU Ý: Những người sau chưa có email: {', '.join(missing_emails)}"
        )

    return context


def generate_ai_prompt(transcript_text: str, custom_instructions: str = "") -> str:
    """
    🔥 HÀM TẠO PROMPT CHUẨN - ĐỒNG BỘ VỚI EnhancedSummaryResponse

    Args:
        transcript_text: Transcript đã được mapping tên
        custom_instructions: Hướng dẫn bổ sung cho AI Agent

    Returns:
        Prompt hoàn chỉnh để gửi cho AI Agent
    """
    speaker_context = get_participant_context()
    current_date = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""Bạn là trợ lý AI thư ký cuộc họp chuyên nghiệp.

📌 THÔNG TIN CUỘC HỌP:
{speaker_context}

📝 NỘI DUNG CUỘC HỌP (ĐÃ CÓ TIMESTAMP VÀ TÊN NGƯỜI NÓI):
{transcript_text}

{custom_instructions}

🎯 NHIỆM VỤ CỦA BẠN:
1. Đọc kỹ nội dung cuộc họp
2. Xác định tất cả các QUYẾT ĐỊNH quan trọng
3. Xác định tất cả các CÔNG VIỆC cần làm (Action Items)
   - Mỗi công việc cần có: task, người được giao, deadline, priority
   - SUY LUẬN NGỮ CẢNH: Tại sao việc này phát sinh?
   - GỢI Ý CÁC BƯỚC THỰC HIỆN cụ thể (3 bước)
4. Xác định các CÂU HỎI cần theo dõi sau cuộc họp

📤 YÊU CẦU ĐẦU RA (CHỈ TRẢ VỀ JSON, KHÔNG CÓ NỘI DUNG KHÁC):
{{
    "meeting_name": "Tên cuộc họp",
    "meeting_date": "{current_date}",
    "general_summary": "Tóm tắt ngắn gọn cuộc họp trong 2-3 câu",
    "action_items": [
        {{
            "task": "Mô tả chi tiết công việc cần làm",
            "assignee_name": "Tên người được giao (phải khớp với danh sách trên)",
            "assignee_email": "Email của người được giao (lấy từ danh sách)",
            "context": "Trích dẫn từ cuộc họp: tại sao việc này cần làm",
            "instructions": "Bước 1: ...\\nBước 2: ...\\nBước 3: ...",
            "deadline": "YYYY-MM-DD hoặc 'Không có'",
            "priority": "Cao/Trung bình/Thấp"
        }}
    ],
    "key_decisions": [
        {{
            "decision": "Quyết định đã được đưa ra",
            "made_by": "Ai đưa ra quyết định này",
            "context": "Bối cảnh dẫn đến quyết định này"
        }}
    ],
    "pending_questions": [
        {{
            "question": "Câu hỏi cần được trả lời sau",
            "asked_by": "Ai đã hỏi",
            "assigned_to": "Ai cần trả lời (nếu có)",
            "urgency": "Cao/Trung bình/Thấp"
        }}
    ],
    "key_topics_discussed": ["Chủ đề 1", "Chủ đề 2"]
}}

⚠️ LƯU Ý QUAN TRỌNG:
- action_items.instructions: Phải có 3 bước cụ thể, bắt đầu bằng số 1., 2., 3.
- action_items.priority: Chỉ dùng "Cao", "Trung bình", "Thấp"
- action_items.assignee_name: Phải khớp chính xác với tên trong danh sách người tham gia
- key_decisions: Sử dụng key "key_decisions" (không phải "decisions")
- Nếu không có thông tin cho trường nào, để mảng rỗng []

Hãy phân tích cẩn thận và trả về JSON chính xác theo format trên!"""

    return prompt


# ==================== HÀM MERGE ACTION ITEMS ====================
def merge_action_items(items_list: List[List[dict]]) -> List[dict]:
    """
    Merge action items từ nhiều chunks lại với nhau

    Args:
        items_list: List các list action items từ mỗi chunk

    Returns:
        List merged action items (đã deduplicate)
    """
    merged = {}

    for items in items_list:
        for item in items:
            task_key = item.get("task", "").lower().strip()

            if task_key not in merged:
                merged[task_key] = item
            else:
                # Merge hoặc lấy phiên bản có nhiều thông tin hơn
                existing = merged[task_key]
                if not existing.get("context") and item.get("context"):
                    existing["context"] = item["context"]
                if not existing.get("instructions") and item.get("instructions"):
                    existing["instructions"] = item["instructions"]
                if not existing.get("deadline") and item.get("deadline"):
                    existing["deadline"] = item["deadline"]
                if not existing.get("priority") and item.get("priority"):
                    existing["priority"] = item["priority"]

    return list(merged.values())


def merge_decisions(decisions_list: List[List[dict]]) -> List[dict]:
    """Merge decisions từ nhiều chunks"""
    merged = {}

    for decisions in decisions_list:
        for decision in decisions:
            key = decision.get("decision", "").lower().strip()[:100]
            if key not in merged:
                merged[key] = decision

    return list(merged.values())


def merge_questions(questions_list: List[List[dict]]) -> List[dict]:
    """Merge pending questions từ nhiều chunks"""
    merged = {}

    for questions in questions_list:
        for question in questions:
            key = question.get("question", "").lower().strip()[:100]
            if key not in merged:
                merged[key] = question

    return list(merged.values())


def merge_topics(topics_list: List[List[str]]) -> List[str]:
    """Merge topics từ nhiều chunks"""
    merged = set()

    for topics in topics_list:
        for topic in topics:
            merged.add(topic)

    return list(merged)
