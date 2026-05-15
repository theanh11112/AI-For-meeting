import os
import json
import logging
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from groq import Groq
from typing import Dict, Any, List

# Cấu hình logging
logger = logging.getLogger(__name__)

# Khởi tạo Groq
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Gmail SMTP Configuration
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")


def clean_email_address(raw_email: str) -> str:
    """Làm sạch địa chỉ email, chỉ giữ lại định dạng email chuẩn"""
    if not raw_email:
        return ""

    # Chuyển thành string
    email_str = str(raw_email)

    # Tìm pattern email
    match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", email_str)
    if match:
        cleaned = match.group(0)
        # Xóa khoảng trắng thừa, xuống dòng, tab
        cleaned = cleaned.strip().replace("\n", "").replace("\r", "").replace("\t", "")
        return cleaned

    return ""


async def generate_drafts(meeting_summary: str, users_tasks: list, context: str = ""):
    """
    Tạo draft email từ meeting summary và tasks
    """
    drafts = []

    system_prompt = f"""
    Bạn là AI Email Agent chuyên nghiệp. Bạn sẽ soạn email giao việc ĐẠI DIỆN CHO thông tin người gửi/công ty sau:
    {context}
    
    [BỐI CẢNH CUỘC HỌP CHUNG]:
    {meeting_summary}
    
    Yêu cầu đầu ra: 
    - Chỉ trả về JSON format: {{"subject": "tiêu đề", "body": "nội dung email"}}
    - Email phải xưng hô phù hợp, thân thiện nhưng chuyên nghiệp
    - Body email dạng text thuần
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
        - Tên: {user['name']}
        - Email: {user['email']}
        - Nhiệm vụ: {tasks_text}
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
                    "to_email": str(user["email"]),
                    "to_name": str(user["name"]),
                    "subject": str(result.get("subject", "Cập nhật công việc")),
                    "body": str(result.get("body", "Nội dung email tự động.")),
                }
            )
            logger.info(f"✅ Đã tạo draft cho {user['name']}")
        except Exception as e:
            logger.error(f"❌ Lỗi tạo email cho {user['name']}: {e}")
            # Tạo draft fallback nếu lỗi
            drafts.append(
                {
                    "to_email": str(user.get("email", "")),
                    "to_name": str(user.get("name", "")),
                    "subject": f"Cập nhật công việc - {user.get('name', 'Nhân viên')}",
                    "body": f"Kính gửi {user.get('name', 'Nhân viên')},\n\nDanh sách công việc được giao:\n{tasks_text}\n\nTrân trọng,\nBan Giám Đốc",
                }
            )

    return drafts


async def send_single_email(draft: dict) -> Dict[str, Any]:
    """Gửi 1 email qua Gmail SMTP với lọc email hợp lệ"""

    # Lấy email và làm sạch
    raw_email = str(draft.get("to_email", ""))
    to_email = clean_email_address(raw_email)

    if not to_email:
        logger.error(
            f"❌ Email không hợp lệ (không tìm thấy email pattern): {raw_email}"
        )
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
    logger.info(f"📧 Đang gửi email tới: {to_name} <{to_email}>")

    # Kiểm tra cấu hình Gmail
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        logger.warning(
            "⚠️ Chưa cấu hình GMAIL_USER hoặc GMAIL_APP_PASSWORD trong file .env"
        )
        print(f"\n📧 [TEST MODE] Gửi cho {to_name} <{to_email}>")
        print(f"Subject: {subject}")
        print(f"Body: {body[:200]}...")
        return {"status": "test_mode"}

    # Gửi email qua Gmail SMTP
    try:
        # Tạo message
        msg = MIMEMultipart()
        msg["From"] = GMAIL_USER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Kết nối SMTP và gửi
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)

        logger.info(f"✅ Đã gửi email thành công tới {to_email}")
        return {"status": "success"}

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "❌ Lỗi xác thực Gmail. Kiểm tra lại GMAIL_USER và GMAIL_APP_PASSWORD trong file .env"
        )
        return {
            "status": "error",
            "error": "SMTP Authentication failed - Check your Gmail credentials",
        }
    except smtplib.SMTPException as e:
        logger.error(f"❌ Lỗi SMTP: {e}")
        return {"status": "error", "error": f"SMTP error: {str(e)}"}
    except Exception as e:
        logger.error(f"❌ Lỗi gửi email: {e}")
        return {"status": "error", "error": str(e)}


async def send_emails_background(drafts: list, process_id: str, db_manager: Any):
    """Gửi nhiều email và log vào DB"""
    for draft in drafts:
        result = await send_single_email(draft)
        if result["status"] in ["success", "test_mode"]:
            await db_manager.log_email_sent(
                process_id=process_id,
                email=draft["to_email"],
                name=draft["to_name"],
                subject=draft["subject"],
                body=draft["body"],
            )
            logger.info(f"✅ Đã log email tới {draft['to_email']} vào DB")
        else:
            logger.error(
                f"❌ Gửi email thất bại cho {draft['to_email']}: {result.get('error', 'Unknown error')}"
            )
