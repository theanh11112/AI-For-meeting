import aiosqlite
import json
from datetime import datetime, timedelta
import uuid
from typing import Optional, Dict, Any, List
import logging
import asyncio
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path: str = "summaries.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the database with required tables"""
        import sqlite3

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS summary_processes (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    processing_time REAL DEFAULT 0.0,
                    metadata TEXT,
                    audio_file_path TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transcripts (
                    process_id TEXT PRIMARY KEY,
                    meeting_name TEXT,
                    transcript_text TEXT NOT NULL,
                    model TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    chunk_size INTEGER,
                    overlap INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (process_id) REFERENCES summary_processes(id)
                )
            """)

            # 🔥 BẢNG EMAIL LOGS
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_logs (
                    id TEXT PRIMARY KEY,
                    process_id TEXT NOT NULL,
                    recipient_email TEXT NOT NULL,
                    recipient_name TEXT,
                    subject TEXT,
                    body TEXT,
                    sent_at TEXT NOT NULL,
                    status TEXT DEFAULT 'success',
                    error_message TEXT,
                    FOREIGN KEY (process_id) REFERENCES summary_processes(id)
                )
            """)

            # 🔥 BẢNG SPEAKER CONTRIBUTIONS (cho biểu đồ đóng góp)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS speaker_contributions (
                    id TEXT PRIMARY KEY,
                    process_id TEXT NOT NULL,
                    speaker_name TEXT NOT NULL,
                    contribution_percent REAL DEFAULT 0,
                    talk_time_seconds REAL DEFAULT 0,
                    sentence_count INTEGER DEFAULT 0,
                    analyzed_at TEXT NOT NULL,
                    FOREIGN KEY (process_id) REFERENCES summary_processes(id),
                    UNIQUE(process_id, speaker_name)
                )
            """)

            conn.commit()

    @asynccontextmanager
    async def _get_connection(self):
        """Get a new database connection"""
        conn = await aiosqlite.connect(self.db_path)
        try:
            yield conn
        finally:
            await conn.close()

    async def create_process(self) -> str:
        """Create a new process entry and return its ID"""
        process_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        async with self._get_connection() as conn:
            await conn.execute(
                "INSERT INTO summary_processes (id, status, created_at, updated_at, start_time) VALUES (?, ?, ?, ?, ?)",
                (process_id, "pending", now, now, now),
            )
            await conn.commit()

        return process_id

    async def update_process(
        self,
        process_id: str,
        status: str,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        chunk_count: Optional[int] = None,
        processing_time: Optional[float] = None,
        metadata: Optional[Dict] = None,
        audio_file_path: Optional[str] = None,
    ):
        """Update a process status and result"""
        now = datetime.utcnow().isoformat()

        async with self._get_connection() as conn:
            update_fields = ["status = ?", "updated_at = ?"]
            params = [status, now]

            if result:
                update_fields.append("result = ?")
                params.append(json.dumps(result))
            if error:
                update_fields.append("error = ?")
                params.append(error)
            if chunk_count is not None:
                update_fields.append("chunk_count = ?")
                params.append(chunk_count)
            if processing_time is not None:
                update_fields.append("processing_time = ?")
                params.append(processing_time)
            if metadata:
                update_fields.append("metadata = ?")
                params.append(json.dumps(metadata))
            if audio_file_path:
                update_fields.append("audio_file_path = ?")
                params.append(audio_file_path)
            if status == "completed" or status == "failed":
                update_fields.append("end_time = ?")
                params.append(now)

            params.append(process_id)
            query = (
                f"UPDATE summary_processes SET {', '.join(update_fields)} WHERE id = ?"
            )
            await conn.execute(query, params)
            await conn.commit()

    async def get_process(self, process_id: str) -> Optional[Dict[str, Any]]:
        """Get a process by its ID"""
        async with self._get_connection() as conn:
            async with conn.execute(
                "SELECT id, status, created_at, updated_at, result, error, start_time, end_time, chunk_count, processing_time, metadata, audio_file_path FROM summary_processes WHERE id = ?",
                (process_id,),
            ) as cursor:
                row = await cursor.fetchone()

                if not row:
                    return None

                result = {
                    "id": row[0],
                    "status": row[1],
                    "created_at": row[2],
                    "updated_at": row[3],
                    "start_time": row[6],
                    "end_time": row[7],
                    "chunk_count": row[8],
                    "processing_time": row[9],
                    "audio_file_path": row[11],
                }

                if row[4]:  # result
                    result["result"] = json.loads(row[4])
                if row[5]:  # error
                    result["error"] = row[5]
                if row[10]:  # metadata
                    result["metadata"] = json.loads(row[10])

                return result

    async def save_transcript(
        self,
        process_id: str,
        transcript_text: str,
        model: str,
        model_name: str,
        chunk_size: int,
        overlap: int,
    ):
        """Save transcript data"""
        now = datetime.utcnow().isoformat()
        async with self._get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO transcripts (process_id, transcript_text, model, model_name, chunk_size, overlap, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    process_id,
                    transcript_text,
                    model,
                    model_name,
                    chunk_size,
                    overlap,
                    now,
                ),
            )
            await conn.commit()

    async def update_meeting_name(self, process_id: str, meeting_name: str):
        """Update meeting name for a transcript"""
        async with self._get_connection() as conn:
            await conn.execute(
                """
                UPDATE transcripts SET meeting_name = ? WHERE process_id = ?
            """,
                (meeting_name, process_id),
            )
            await conn.commit()

    async def update_audio_file_path(self, process_id: str, audio_file_path: str):
        """Update audio file path for a process"""
        async with self._get_connection() as conn:
            await conn.execute(
                """
                UPDATE summary_processes SET audio_file_path = ? WHERE id = ?
            """,
                (audio_file_path, process_id),
            )
            await conn.commit()

    async def get_audio_file_path(self, process_id: str) -> Optional[str]:
        """Get audio file path for a process"""
        async with self._get_connection() as conn:
            async with conn.execute(
                "SELECT audio_file_path FROM summary_processes WHERE id = ?",
                (process_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0]
                return None

    async def get_transcript_data(self, process_id: str):
        """Get transcript data for a process"""
        async with self._get_connection() as conn:
            async with conn.execute(
                """
                SELECT t.*, p.status, p.result, p.audio_file_path
                FROM transcripts t 
                JOIN summary_processes p ON t.process_id = p.id 
                WHERE t.process_id = ?
            """,
                (process_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(zip([col[0] for col in cursor.description], row))
                return None

    # ==================== MEETING HISTORY METHODS ====================

    async def get_all_meetings(
        self, limit: int = 5, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Lấy danh sách tất cả các cuộc họp để hiển thị ở Sidebar"""
        async with self._get_connection() as conn:
            async with conn.execute(
                """
                SELECT 
                    p.id, 
                    COALESCE(t.meeting_name, 'Cuộc họp chưa đặt tên') as meeting_name,
                    p.created_at,
                    p.status,
                    p.start_time,
                    p.end_time,
                    p.audio_file_path
                FROM summary_processes p
                LEFT JOIN transcripts t ON p.id = t.process_id
                WHERE p.status IN ('completed', 'failed', 'pending')
                ORDER BY p.created_at DESC
                LIMIT ? OFFSET ?
            """,
                (limit, offset),
            ) as cursor:
                rows = await cursor.fetchall()
                meetings = []
                for row in rows:
                    meetings.append(
                        {
                            "process_id": row[0],
                            "meeting_name": row[1],
                            "created_at": row[2],
                            "status": row[3].lower() if row[3] else "pending",
                            "start_time": row[4],
                            "end_time": row[5],
                            "audio_file_path": row[6],
                        }
                    )
                return meetings

    async def delete_meeting(self, process_id: str) -> bool:
        """Xóa vĩnh viễn một cuộc họp khỏi Database"""
        async with self._get_connection() as conn:
            # Xóa speaker contributions trước (do có khóa ngoại)
            await conn.execute(
                "DELETE FROM speaker_contributions WHERE process_id = ?", (process_id,)
            )
            # Xóa email logs
            await conn.execute(
                "DELETE FROM email_logs WHERE process_id = ?", (process_id,)
            )
            # Xóa transcripts
            await conn.execute(
                "DELETE FROM transcripts WHERE process_id = ?", (process_id,)
            )
            # Xóa summary_processes
            cursor = await conn.execute(
                "DELETE FROM summary_processes WHERE id = ?", (process_id,)
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def cleanup_old_processes(self, hours: int = 24):
        """Clean up processes older than specified hours"""
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        async with self._get_connection() as conn:
            # Xóa speaker contributions trước
            await conn.execute(
                "DELETE FROM speaker_contributions WHERE process_id IN (SELECT id FROM summary_processes WHERE created_at < ?)",
                (cutoff,),
            )
            # Xóa email logs
            await conn.execute(
                "DELETE FROM email_logs WHERE process_id IN (SELECT id FROM summary_processes WHERE created_at < ?)",
                (cutoff,),
            )
            await conn.execute(
                "DELETE FROM summary_processes WHERE created_at < ?", (cutoff,)
            )
            await conn.commit()

    # ==================== EMAIL LOGS METHODS ====================

    async def log_email_sent(
        self,
        process_id: str,
        email: str,
        name: str,
        subject: str,
        body: str,
        status: str = "success",
        error_message: str = None,
    ):
        """Lưu log email đã gửi vào database"""
        log_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        async with self._get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO email_logs 
                (id, process_id, recipient_email, recipient_name, subject, body, sent_at, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log_id,
                    process_id,
                    email,
                    name,
                    subject,
                    body,
                    now,
                    status,
                    error_message,
                ),
            )
            await conn.commit()
            logger.info(f"✅ Đã lưu log email cho process {process_id} gửi đến {email}")

    async def get_email_logs(self, process_id: str) -> List[Dict[str, Any]]:
        """Lấy lịch sử email đã gửi của một cuộc họp"""
        async with self._get_connection() as conn:
            async with conn.execute(
                """
                SELECT * FROM email_logs 
                WHERE process_id = ? 
                ORDER BY sent_at DESC
                """,
                (process_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, row)) for row in rows]

    async def get_all_email_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Lấy tất cả email logs (có giới hạn)"""
        async with self._get_connection() as conn:
            async with conn.execute(
                """
                SELECT e.*, COALESCE(t.meeting_name, 'Unknown') as meeting_name
                FROM email_logs e
                LEFT JOIN transcripts t ON e.process_id = t.process_id
                ORDER BY e.sent_at DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, row)) for row in rows]

    # ==================== SPEAKER CONTRIBUTIONS METHODS ====================

    async def save_speaker_contributions(
        self,
        process_id: str,
        contributions: List[Dict[str, Any]],
    ):
        """Lưu phân tích mức độ đóng góp của các thành viên"""
        now = datetime.utcnow().isoformat()

        async with self._get_connection() as conn:
            for speaker in contributions:
                speaker_id = str(uuid.uuid4())
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO speaker_contributions 
                    (id, process_id, speaker_name, contribution_percent, talk_time_seconds, sentence_count, analyzed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        speaker_id,
                        process_id,
                        speaker.get("name"),
                        speaker.get("contribution", 0),
                        speaker.get("talk_time", 0),
                        speaker.get("sentence_count", 0),
                        now,
                    ),
                )
            await conn.commit()
            logger.info(f"✅ Đã lưu phân tích đóng góp cho process {process_id}")

    async def get_speaker_contributions(self, process_id: str) -> List[Dict[str, Any]]:
        """Lấy phân tích mức độ đóng góp của các thành viên"""
        async with self._get_connection() as conn:
            async with conn.execute(
                """
                SELECT speaker_name, contribution_percent, talk_time_seconds, sentence_count
                FROM speaker_contributions 
                WHERE process_id = ?
                ORDER BY contribution_percent DESC
                """,
                (process_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "name": row[0],
                        "contribution": row[1],
                        "talk_time": row[2],
                        "sentence_count": row[3],
                    }
                    for row in rows
                ]
