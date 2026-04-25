# backend/app/model_config.py
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime
import asyncio
import os

logger = logging.getLogger(__name__)


class ModelManager:
    """Quản lý các model và tự động chuyển đổi khi cần - Cloud-First Hybrid cho Mac M2"""

    def __init__(self):
        self.models = {
            "primary": {
                "name": "llama-3.3-70b-versatile",  # 🔥 SIÊU MẠNH & MIỄN PHÍ qua Groq
                "provider": "groq",
                "priority": 1,
                "timeout": 45,
                "max_retries": 3,
                "description": "Llama 3.3 70B via Groq - Perfect for JSON extraction and reasoning",
                "context_length": 128000,
                "requires_api_key": True,
            },
            "fallback": {
                "name": "qwen2.5:7b-instruct",  # 🔥 LOCAL TỐT NHẤT CHO JSON
                "provider": "ollama",
                "priority": 2,
                "timeout": 90,
                "max_retries": 2,
                "description": "Qwen 2.5 7B Local - Fallback when no internet, great for JSON",
                "context_length": 16384,  # Tăng lên để đọc được nhiều hơn
                "requires_api_key": False,
            },
            "emergency": {
                "name": "llama3.2:3b",  # 🔥 SIÊU NHẸ - Chống cháy
                "provider": "ollama",
                "priority": 3,
                "timeout": 30,
                "max_retries": 1,
                "description": "Llama 3.2 3B - Emergency fallback when RAM is overloaded",
                "context_length": 4096,
                "requires_api_key": False,
            },
        }

        self.current_model = "primary"
        self.model_stats = {}
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        self.init_stats()

        # Log API key status
        if self.groq_api_key:
            logger.info(
                "✅ Groq API key found - High-performance cloud model available"
            )
        else:
            logger.warning("⚠️ GROQ_API_KEY not set - Will use local models only")

    def init_stats(self):
        """Khởi tạo thống kê cho từng model"""
        for key in self.models:
            self.model_stats[key] = {
                "success_count": 0,
                "error_count": 0,
                "avg_response_time": 0,
                "last_used": None,
                "is_available": True,
                "consecutive_failures": 0,
            }

    async def get_available_model(
        self, preferred_model: Optional[str] = None, task_type: str = "complex"
    ) -> Dict:
        """Lấy model khả dụng, tự động fallback nếu cần

        Args:
            preferred_model: Tên model ưu tiên
            task_type: Loại tác vụ - "complex" (JSON extraction), "simple", "default"
        """
        # 🔥 Tác vụ phức tạp - ưu tiên Groq Llama 70B nếu có API key
        if task_type == "complex" and self.groq_api_key:
            primary_key = "primary"
            if self.model_stats[primary_key]["is_available"]:
                logger.info(
                    f"🚀 Using Groq Llama 70B for complex task (FREE, high performance)"
                )
                return {"key": primary_key, "config": self.models[primary_key]}

        # 🔥 Tác vụ JSON - ưu tiên Qwen 2.5 (local) nếu Groq không khả dụng
        if task_type == "json_extraction" or not self.groq_api_key:
            fallback_key = "fallback"
            if self.model_stats[fallback_key]["is_available"]:
                logger.info(f"📦 Using Qwen 2.5 for JSON extraction (local, free)")
                return {"key": fallback_key, "config": self.models[fallback_key]}

        # Nếu có model ưu tiên, thử dùng nó trước
        if preferred_model:
            for key, model in self.models.items():
                if model["name"] == preferred_model:
                    # Kiểm tra API key requirement
                    if model.get("requires_api_key") and not self.groq_api_key:
                        logger.warning(
                            f"Model {model['name']} requires API key but not set"
                        )
                        continue
                    if self.model_stats[key]["is_available"]:
                        logger.info(f"Using preferred model: {model['name']}")
                        return {"key": key, "config": model}
                    else:
                        logger.warning(
                            f"Preferred model {model['name']} is unavailable"
                        )

        # Thử primary model (Groq) nếu có API key
        if self.groq_api_key:
            primary_key = "primary"
            if self.model_stats[primary_key]["is_available"]:
                stats = self.model_stats[primary_key]
                total_calls = stats["success_count"] + stats["error_count"]
                if total_calls > 0:
                    error_rate = stats["error_count"] / total_calls
                    if error_rate > 0.6:  # Nếu error rate > 60%, chuyển sang fallback
                        logger.warning(
                            f"Groq error rate too high ({error_rate:.2%}), switching to Qwen fallback"
                        )
                        return self._get_fallback_model()

                logger.info(f"Using primary model: {self.models[primary_key]['name']}")
                return {"key": primary_key, "config": self.models[primary_key]}

        # Nếu primary unavailable hoặc không có API key, dùng fallback
        return self._get_fallback_model()

    def _get_fallback_model(self) -> Dict:
        """Lấy fallback model: ưu tiên Qwen 2.5, sau đó emergency"""

        # Thử Qwen 2.5 local
        fallback_key = "fallback"
        if self.model_stats[fallback_key]["is_available"]:
            logger.info(f"Using Qwen 2.5 fallback: {self.models[fallback_key]['name']}")
            return {"key": fallback_key, "config": self.models[fallback_key]}

        # Thử emergency (llama3.2:3b)
        emergency_key = "emergency"
        if self.model_stats[emergency_key]["is_available"]:
            logger.info(f"Using emergency model: {self.models[emergency_key]['name']}")
            return {"key": emergency_key, "config": self.models[emergency_key]}

        # Nếu tất cả đều unavailable, reset và thử lại
        self.reset_all_models()
        logger.warning("All models unavailable, resetting and using Qwen fallback")
        return {"key": "fallback", "config": self.models["fallback"]}

    def reset_all_models(self):
        """Reset trạng thái của tất cả models"""
        for key in self.models:
            self.model_stats[key]["is_available"] = True
            self.model_stats[key]["consecutive_failures"] = 0
            logger.info(f"Reset availability for model: {key}")

    def update_stats(
        self, model_key: str, success: bool, response_time: float, error_msg: str = None
    ):
        """Cập nhật thống kê cho model"""
        if model_key not in self.model_stats:
            logger.warning(f"Unknown model key: {model_key}")
            return

        stats = self.model_stats[model_key]

        if success:
            stats["success_count"] += 1
            stats["consecutive_failures"] = 0
            logger.debug(f"Model {model_key} success (total: {stats['success_count']})")
        else:
            stats["error_count"] += 1
            stats["consecutive_failures"] += 1
            logger.warning(
                f"Model {model_key} failed: {error_msg} (consecutive: {stats['consecutive_failures']})"
            )

            # Nếu fail 2 lần liên tiếp với cloud model, đánh dấu unavailable
            if stats["consecutive_failures"] >= 2 and model_key == "primary":
                stats["is_available"] = False
                logger.error(
                    f"Cloud model {model_key} marked as unavailable after {stats['consecutive_failures']} consecutive failures"
                )
            # Nếu fail 3 lần liên tiếp với local model
            elif stats["consecutive_failures"] >= 3:
                stats["is_available"] = False
                logger.error(
                    f"Model {model_key} marked as unavailable after {stats['consecutive_failures']} consecutive failures"
                )

        # Cập nhật thời gian response trung bình (Exponential moving average)
        if stats["success_count"] > 0:
            alpha = 0.3
            stats["avg_response_time"] = (
                alpha * response_time + (1 - alpha) * stats["avg_response_time"]
            )
        else:
            stats["avg_response_time"] = response_time

        stats["last_used"] = datetime.now()

    def get_current_model_name(self) -> str:
        """Lấy tên model hiện tại"""
        return self.models[self.current_model]["name"]

    def get_model_info(self) -> Dict:
        """Lấy thông tin về tất cả models"""
        info = {}
        for key, model in self.models.items():
            stats = self.model_stats[key]
            info[key] = {
                "name": model["name"],
                "provider": model["provider"],
                "available": stats["is_available"],
                "success_rate": self._get_success_rate(key),
                "avg_response_time": round(stats["avg_response_time"], 2),
                "description": model["description"],
                "timeout": model["timeout"],
                "context_length": model["context_length"],
            }
        return info

    def _get_success_rate(self, model_key: str) -> float:
        """Tính tỷ lệ thành công của model"""
        stats = self.model_stats[model_key]
        total = stats["success_count"] + stats["error_count"]
        if total == 0:
            return 1.0  # Chưa có dữ liệu, coi như 100%
        return round(stats["success_count"] / total, 2)

    def should_retry_with_fallback(self, model_key: str, error: Exception) -> bool:
        """Quyết định có nên retry với fallback model không"""
        error_str = str(error).lower()

        # Timeout error -> nên retry
        if isinstance(error, asyncio.TimeoutError):
            logger.info(f"Timeout error with {model_key}, should retry with fallback")
            return True

        # Rate limit error -> nên retry
        if "rate limit" in error_str or "too many requests" in error_str:
            logger.info(
                f"Rate limit error with {model_key}, should retry with fallback"
            )
            return True

        # Model not found -> nên retry
        if "not found" in error_str or "model" in error_str:
            logger.info(
                f"Model not found error with {model_key}, should retry with fallback"
            )
            return True

        # API key error -> nên retry với local
        if (
            "api key" in error_str
            or "unauthorized" in error_str
            or "authentication" in error_str
        ):
            logger.info(f"API key error with {model_key}, switching to local fallback")
            return True

        # Function calling/JSON error -> nên retry với fallback
        if "function" in error_str or "tool" in error_str or "json" in error_str:
            logger.info(
                f"Function/JSON error with {model_key}, should retry with fallback"
            )
            return True

        # Connection error -> nên retry
        if "connection" in error_str or "network" in error_str:
            logger.info(
                f"Connection error with {model_key}, should retry with fallback"
            )
            return True

        # Các lỗi khác - chỉ retry nếu chưa fail quá 2 lần
        logger.debug(
            f"Error with {model_key}, retry decision: {self.model_stats[model_key]['consecutive_failures'] < 2}"
        )
        return self.model_stats[model_key]["consecutive_failures"] < 2

    def get_statistics(self) -> Dict:
        """Lấy thống kê chi tiết của tất cả models"""
        stats = {}
        for key, model_stats in self.model_stats.items():
            model_name = self.models[key]["name"]
            stats[model_name] = {
                "success_count": model_stats["success_count"],
                "error_count": model_stats["error_count"],
                "avg_response_time": round(model_stats["avg_response_time"], 2),
                "is_available": model_stats["is_available"],
                "last_used": (
                    model_stats["last_used"].isoformat()
                    if model_stats["last_used"]
                    else None
                ),
            }
        return stats


# Khởi tạo global model manager
model_manager = ModelManager()

# Log thông tin khởi tạo
logger.info(f"Model Manager initialized with {len(model_manager.models)} models")
for key, model in model_manager.models.items():
    api_status = (
        "🌐 Cloud (Groq)" if model.get("requires_api_key") else "💻 Local (Ollama)"
    )
    logger.info(
        f"  - {key}: {model['name']} [{api_status}] (timeout: {model['timeout']}s, context: {model['context_length']})"
    )
