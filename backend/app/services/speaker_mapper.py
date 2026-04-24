# filepath: backend/app/services/speaker_mapper.py
from app.models.user_map import meeting_directory
from typing import Dict, List, Optional


def map_speakers_to_real_names(transcript_data: dict) -> dict:
    """
    Thay thế 'SPEAKER_00' thành tên thật trong toàn bộ văn bản

    Args:
        transcript_data: Dict từ WhisperX với format:
            {
                "segments": [
                    {"start": 1.0, "end": 5.0, "speaker": "SPEAKER_00", "text": "..."},
                    ...
                ]
            }

    Returns:
        Dict với format:
            {
                "segments": [...],  # Giữ nguyên + thêm speaker_name
                "full_text": "[Nguyễn Văn A] 1.0s - 5.0s: Hôm nay chúng ta bàn về..."
            }
    """
    mapped_segments = []
    full_text_with_names = []

    for seg in transcript_data.get("segments", []):
        speaker_id = seg.get("speaker", "UNKNOWN")
        start_time = seg.get("start", 0)
        end_time = seg.get("end", 0)

        # Tìm thông tin người nói trong danh bạ
        participant = meeting_directory.get_participant(speaker_id)

        if participant:
            real_name = participant.name
        else:
            # Nếu chưa có trong danh bạ, giữ nguyên speaker_id
            real_name = speaker_id

        # Lưu segment đã mapping (dùng cho các mục đích khác)
        mapped_segments.append(
            {
                "start": start_time,
                "end": end_time,
                "speaker_id": speaker_id,
                "speaker_name": real_name,
                "text": seg["text"],
            }
        )

        # 🔥 QUAN TRỌNG: Thêm timestamp để AI Agent hiểu ngữ cảnh thời gian
        # Format: [Tên người nói] start_time - end_time: Nội dung
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
    """
    Tìm email của người tham gia dựa vào tên

    Args:
        name: Tên người cần tìm (VD: "Nguyễn Văn A")

    Returns:
        Email nếu tìm thấy, None nếu không
    """
    for participant in meeting_directory.get_all_participants():
        if participant.name.lower() == name.lower():
            return participant.email
    return None


def get_speaker_name_by_id(speaker_id: str) -> str:
    """
    Lấy tên thật từ speaker_id

    Args:
        speaker_id: Mã speaker (VD: "SPEAKER_00")

    Returns:
        Tên thật nếu có mapping, ngược lại trả về speaker_id
    """
    participant = meeting_directory.get_participant(speaker_id)
    return participant.name if participant else speaker_id


def format_transcript_for_ai(
    transcript_data: dict, include_timestamps: bool = True
) -> str:
    """
    Format transcript để gửi cho AI Agent

    Args:
        transcript_data: Output từ map_speakers_to_real_names
        include_timestamps: Có bao gồm mốc thời gian không

    Returns:
        String đã format sẵn sàng cho AI Agent
    """
    if include_timestamps:
        return transcript_data.get("full_text", "")

    # Format không có timestamp (chỉ có tên)
    lines = []
    for seg in transcript_data.get("segments", []):
        lines.append(f"[{seg['speaker_name']}]: {seg['text']}")

    return "\n".join(lines)


def generate_ai_prompt(transcript_text: str, custom_instructions: str = "") -> str:
    """
    Tạo prompt chuẩn cho AI Agent để trích xuất Action Items và gửi email

    Args:
        transcript_text: Transcript đã được mapping tên (full_text từ map_speakers_to_real_names)
        custom_instructions: Hướng dẫn bổ sung cho AI Agent

    Returns:
        Prompt hoàn chỉnh để gửi cho AI Agent
    """
    speakers = get_all_speakers()

    # Tạo danh sách speaker với email
    speaker_list = "\n".join(
        [
            f"- {s['name']} (Email: {s.get('email', '❌ Chưa có email')})"
            for s in speakers
        ]
    )

    # Tạo danh sách speaker không có email để yêu cầu bổ sung
    missing_emails = [s["name"] for s in speakers if not s.get("email")]
    missing_email_note = ""
    if missing_emails:
        missing_email_note = f"\n\n⚠️ LƯU Ý: Những người sau chưa có email: {', '.join(missing_emails)}. Hãy yêu cầu bổ sung email trước khi gửi task cho họ."

    prompt = f"""Bạn là trợ lý AI thư ký cuộc họp chuyên nghiệp. Nhiệm vụ của bạn:

1. Đọc kỹ nội dung cuộc họp dưới đây
2. Xác định tất cả các công việc cần làm (Action Items)
3. Xác định chính xác người được giao việc dựa trên tên trong danh sách
4. Trích xuất deadline (nếu có)
5. Trả về kết quả dưới dạng JSON chuẩn

📋 DANH SÁCH NGƯỜI THAM GIA (KÈM EMAIL):
{speaker_list}
{missing_email_note}

📝 NỘI DUNG CUỘC HỌP (ĐÃ CÓ TIMESTAMP VÀ TÊN NGƯỜI NÓI):
{transcript_text}

{custom_instructions}

📤 YÊU CẦU ĐẦU RA (CHỈ TRẢ VỀ JSON, KHÔNG CÓ NỘI DUNG KHÁC):
{{
    "meeting_summary": "Tóm tắt ngắn gọn cuộc họp trong 2-3 câu",
    "action_items": [
        {{
            "task": "Mô tả chi tiết công việc cần làm",
            "assignee_name": "Tên người được giao (phải khớp với danh sách trên)",
            "assignee_email": "Email của người được giao (lấy từ danh sách)",
            "deadline": "Hạn hoàn thành (nếu có, format YYYY-MM-DD hoặc 'Không có')",
            "priority": "Cao/Trung bình/Thấp"
        }}
    ],
    "decisions": [
        {{
            "decision": "Quyết định đã được đưa ra",
            "made_by": "Ai đưa ra quyết định này"
        }}
    ],
    "pending_questions": [
        {{
            "question": "Câu hỏi cần được trả lời sau",
            "asked_by": "Ai đã hỏi",
            "assigned_to": "Ai cần trả lời (nếu có)"
        }}
    ]
}}

Hãy phân tích cẩn thận và trả về JSON chính xác!"""

    return prompt
