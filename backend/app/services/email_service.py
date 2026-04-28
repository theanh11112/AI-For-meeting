import os
import json
import httpx
from groq import Groq
from fastapi import BackgroundTasks

# Khởi tạo Groq
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Resend API configuration
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_API_URL = "https://api.resend.com/emails"


async def generate_drafts(meeting_summary: str, users_tasks: list, context: str = ""):
    """
    Tạo draft email từ meeting summary và tasks
    Dùng Groq Llama 3.3 70B để sinh nội dung cá nhân hóa
    """
    drafts = []

    # System Prompt: Định hình Người Gửi & Bối cảnh chung
    system_prompt = f"""
    Bạn là AI Email Agent chuyên nghiệp. Bạn sẽ soạn email giao việc ĐẠI DIỆN CHO thông tin người gửi/công ty sau:
    
    [THÔNG TIN NGƯỜI GỬI / CÔNG TY]:
    {context}
    
    [BỐI CẢNH CUỘC HỌP CHUNG]:
    Dưới đây là tóm tắt nội dung cuộc họp vừa diễn ra. Hãy dùng thông tin này để viết phần mở đầu (lý do gửi mail) hoặc nhắc lại ngữ cảnh ngắn gọn cho tự nhiên:
    {meeting_summary}
    
    Yêu cầu đầu ra: 
    - Chỉ trả về JSON format: {{"subject": "tiêu đề", "body": "nội dung email"}}
    - Email phải xưng hô phù hợp với thông tin người gửi, thân thiện nhưng chuyên nghiệp
    - Body email dạng text thuần (không HTML phức tạp)
    - Cuối email nhớ ký tên đại diện công ty
    """

    for user in users_tasks:
        tasks_text = "\n".join(
            [
                f"- {t['task_name']} (Hạn hoàn thành: {t['deadline']})"
                for t in user["tasks"]
            ]
        )

        user_prompt = f"""
        Hãy viết email cho nhân viên này:
        - Tên người nhận: {user['name']}
        - Email: {user['email']}
        
        [NHIỆM VỤ ĐƯỢC GIAO TRONG HỌP]:
        {tasks_text}
        
        Lưu ý: 
        - Dựa vào Tóm tắt cuộc họp để viết lời dẫn
        - Liệt kê các nhiệm vụ trên một cách rõ ràng
        - Giọng văn phù hợp với thông tin người gửi ở trên
        """

        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )

            result = json.loads(response.choices[0].message.content)

            drafts.append(
                {
                    "to_email": user["email"],
                    "to_name": user["name"],
                    "subject": result.get("subject", "Cập nhật công việc từ cuộc họp"),
                    "body": result.get(
                        "body",
                        f"Xin chào {user['name']},\n\nĐây là email tự động từ Meetily.",
                    ),
                }
            )

            print(f"✅ Đã tạo draft cho {user['name']}")

        except Exception as e:
            print(f"❌ Lỗi tạo email cho {user['name']}: {e}")

    return drafts


async def send_single_email(draft: dict):
    """
    Gửi 1 email qua Resend API
    Nếu không có RESEND_API_KEY, chuyển sang chế độ test (in ra console)
    """
    # Chế độ TEST: In ra console thay vì gửi thật
    if not RESEND_API_KEY or RESEND_API_KEY == "your_resend_api_key_here":
        print("\n" + "=" * 60)
        print("📧 [TEST MODE] Email would be sent to:")
        print(f"   To: {draft['to_name']} <{draft['to_email']}>")
        print(f"   Subject: {draft['subject']}")
        print(f"   Body:\n{draft['body']}")
        print("=" * 60 + "\n")
        return {"status": "test_mode", "to": draft["to_email"], "mode": "console"}

    # Chế độ THẬT: Gửi qua Resend API
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": "Meetily <onboarding@resend.dev>",  # Domain mặc định của Resend
                    "to": [draft["to_email"]],
                    "subject": draft["subject"],
                    "text": draft["body"],
                },
            )

            if response.status_code == 200:
                result = response.json()
                print(f"✅ Email sent to {draft['to_email']}, id: {result.get('id')}")
                return {
                    "status": "success",
                    "to": draft["to_email"],
                    "id": result.get("id"),
                }
            else:
                print(f"❌ Failed to send to {draft['to_email']}: {response.text}")
                return {
                    "status": "error",
                    "to": draft["to_email"],
                    "error": response.text,
                }

        except Exception as e:
            print(f"❌ Exception sending to {draft['to_email']}: {e}")
            return {"status": "error", "to": draft["to_email"], "error": str(e)}


async def send_emails_background(drafts: list):
    """
    Gửi nhiều email trong background
    Trả về kết quả của từng email
    """
    results = []
    for draft in drafts:
        result = await send_single_email(draft)
        results.append(result)
    return results
