from typing import List, Dict, Any, Optional
import logging
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)


class ModelManager:
    """Quản lý các model và tự động chuyển đổi khi cần"""

    def __init__(self):
        self.models = {
            "primary": {
                "name": "llama-3.3-70b-versatile",  # Groq model
                "provider": "groq",
                "priority": 1,
                "timeout": 45,
                "max_retries": 3,
                "description": "Groq API - Llama 3.3 70B (Primary - Fastest)",
                "context_length": 8192,
            },
            "fallback": {
                "name": "qwen2.5:7b-instruct",  # Qwen 2.5 7B via Ollama
                "provider": "ollama",
                "priority": 2,
                "timeout": 120,
                "max_retries": 2,
                "description": "Ollama Local - Qwen 2.5 7B (Fallback)",
                "context_length": 8192,
            },
        }

        self.current_model = "primary"
        self.model_stats = {}
        self.init_stats()

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

    async def get_available_model(self, preferred_model: Optional[str] = None) -> Dict:
        """Lấy model khả dụng, tự động fallback nếu cần"""

        # Nếu có model ưu tiên, thử dùng nó trước
        if preferred_model:
            for key, model in self.models.items():
                if model["name"] == preferred_model:
                    if self.model_stats[key]["is_available"]:
                        logger.info(f"Using preferred model: {model['name']}")
                        self.current_model = key  # ✅ Cập nhật current_model
                        return {"key": key, "config": model}
                    else:
                        logger.warning(
                            f"Preferred model {model['name']} is unavailable"
                        )

        # Thử primary model trước
        primary_key = "primary"
        if self.model_stats[primary_key]["is_available"]:
            stats = self.model_stats[primary_key]
            # Kiểm tra error rate
            total_calls = stats["success_count"] + stats["error_count"]
            if total_calls > 0:
                error_rate = stats["error_count"] / total_calls
                if error_rate > 0.6:  # Nếu error rate > 60%, chuyển sang fallback
                    logger.warning(
                        f"Primary model error rate too high ({error_rate:.2%}), switching to fallback"
                    )
                    return self._get_fallback_model()

            logger.info(
                f"Using primary model: {self.models[primary_key]['name']} (provider: {self.models[primary_key]['provider']})"
            )
            self.current_model = primary_key  # ✅ Cập nhật current_model
            return {"key": primary_key, "config": self.models[primary_key]}

        # Nếu primary unavailable, dùng fallback
        return self._get_fallback_model()

    def _get_fallback_model(self) -> Dict:
        """Lấy fallback model"""
        fallback_key = "fallback"
        if self.model_stats[fallback_key]["is_available"]:
            logger.info(
                f"Using fallback model: {self.models[fallback_key]['name']} (provider: {self.models[fallback_key]['provider']})"
            )
            self.current_model = fallback_key  # ✅ Cập nhật current_model
            return {"key": fallback_key, "config": self.models[fallback_key]}

        # Nếu fallback cũng unavailable, reset cả hai và thử lại
        self.reset_all_models()
        logger.warning("All models unavailable, resetting and using primary")
        self.current_model = "primary"  # ✅ Cập nhật current_model
        return {"key": "primary", "config": self.models["primary"]}

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

            # Nếu fail 3 lần liên tiếp, đánh dấu unavailable
            if stats["consecutive_failures"] >= 3:
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
        if self.current_model in self.models:
            return self.models[self.current_model]["name"]
        return "unknown"

    def get_current_provider(self) -> str:
        """Lấy provider của model hiện tại"""
        if self.current_model in self.models:
            return self.models[self.current_model]["provider"]
        return "unknown"

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
                "is_current": (key == self.current_model),  # ✅ Thêm flag này
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

        # Function calling error -> nên retry với fallback
        if "function" in error_str or "tool" in error_str or "json" in error_str:
            logger.info(
                f"Function calling error with {model_key}, should retry with fallback"
            )
            return True

        # Connection error -> nên retry
        if "connection" in error_str or "timeout" in error_str:
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
                "is_current": (key == self.current_model),  # ✅ Thêm flag này
                "last_used": (
                    model_stats["last_used"].isoformat()
                    if model_stats["last_used"]
                    else None
                ),
            }
        return stats

    def get_current_model_config(self) -> Dict:
        """Lấy config của model hiện tại"""
        if self.current_model in self.models:
            return {
                "key": self.current_model,
                "config": self.models[self.current_model],
                "stats": self.model_stats[self.current_model],
            }
        return None


# Khởi tạo global model manager
model_manager = ModelManager()

# Log thông tin khởi tạo
logger.info(f"Model Manager initialized with {len(model_manager.models)} models")
for key, model in model_manager.models.items():
    logger.info(
        f"  - {key}: {model['name']} (provider: {model['provider']}, timeout: {model['timeout']}s, priority: {model['priority']})"
    )
logger.info(
    f"Current model: {model_manager.get_current_model_name()} (provider: {model_manager.get_current_provider()})"
)
