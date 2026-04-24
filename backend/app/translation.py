import httpx
import os
import asyncio
from typing import Optional
from datetime import datetime


class TranslationService:
    def __init__(self):
        self.groq_api_key = os.getenv("GROQ_API_KEY")

    SUPPORTED_LANGUAGES = {
        "en": "English",
        "vi": "Vietnamese",
        "zh": "Chinese",
        "ja": "Japanese",
        "ko": "Korean",
        "fr": "French",
        "de": "German",
        "es": "Spanish",
        "ru": "Russian",
        "th": "Thai",
        "hi": "Hindi",
        "it": "Italian",
        "pt": "Portuguese",
        "nl": "Dutch",
        "pl": "Polish",
        "tr": "Turkish",
        "id": "Indonesian",
        "ar": "Arabic",
    }

    def _log(self, level: str, msg: str):
        """Helper để in log có timestamp"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {level} - {msg}")

    async def _call_groq(
        self, client: httpx.AsyncClient, prompt: str, retries: int = 3
    ) -> Optional[str]:
        """Gọi Groq API với retry khi gặp 429"""
        delay = 2
        for attempt in range(retries):
            try:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.groq_api_key}"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a professional translator. Output only the translation, nothing else.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 2000,
                    },
                )

                if response.status_code == 200:
                    result = response.json()
                    translated = result["choices"][0]["message"]["content"].strip()
                    if translated.startswith('"') and translated.endswith('"'):
                        translated = translated[1:-1]
                    return translated

                elif response.status_code == 429:
                    retry_after = int(response.headers.get("retry-after", delay))
                    self._log(
                        "⚠️",
                        f"Rate limit hit, waiting {retry_after}s (attempt {attempt + 1}/{retries})",
                    )
                    await asyncio.sleep(retry_after)
                    delay *= 2

                else:
                    self._log(
                        "❌",
                        f"Translation error: {response.status_code} — {response.text}",
                    )
                    return None

            except httpx.TimeoutException:
                self._log("⚠️", f"Timeout on attempt {attempt + 1}/{retries}")
                await asyncio.sleep(delay)
                delay *= 2

            except Exception as e:
                self._log("❌", f"Translation exception: {e}")
                return None

        self._log("❌", f"All {retries} attempts failed")
        return None

    async def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = None,
        seq: Optional[int] = None,
    ) -> dict:
        """
        Dịch text sang target_lang
        Returns: {"original": text, "translated": translated_text, "source_lang": detected_lang, "sequence": seq}
        """
        # ===== LOG NHẬN REQUEST =====
        self._log(
            "🔵",
            f"[RECV] seq={seq}, text='{text[:80]}{'...' if len(text) > 80 else ''}'",
        )

        # Case 1: text rỗng
        if not text or text.strip() == "":
            self._log("🟢", f"[RESP] seq={seq} -> EMPTY TEXT")
            return {
                "original": text,
                "translated": "",
                "source_lang": source_lang or "unknown",
                "sequence": seq,
            }

        # Case 2: target_lang là "original" (không dịch)
        if target_lang == "original":
            self._log("🟢", f"[RESP] seq={seq} -> ORIGINAL (no translation)")
            return {
                "original": text,
                "translated": text,
                "source_lang": source_lang or "auto",
                "sequence": seq,
            }

        # Case 3: không có API key
        if not self.groq_api_key:
            self._log("⚠️", "No Groq API key found. Translation disabled.")
            self._log("🟢", f"[RESP] seq={seq} -> NO API KEY")
            return {
                "original": text,
                "translated": text,
                "source_lang": source_lang or "unknown",
                "sequence": seq,
            }

        target_name = self.SUPPORTED_LANGUAGES.get(target_lang, target_lang)

        if source_lang and source_lang != "auto":
            source_name = self.SUPPORTED_LANGUAGES.get(source_lang, source_lang)
            prompt = f"Translate the following text from {source_name} to {target_name}. Output only the translation, no explanations, no quotes.\n\nText: {text}\n\nTranslation:"
        else:
            prompt = f"Translate the following text to {target_name}. Output only the translation, no explanations, no quotes.\n\nText: {text}\n\nTranslation:"

        self._log("🟡", f"[API] seq={seq} calling Groq API...")

        async with httpx.AsyncClient(timeout=30.0) as client:
            translated = await self._call_groq(client, prompt)

        # Case 4: dịch thành công
        if translated is not None:
            self._log(
                "🟢",
                f"[RESP] seq={seq} -> SUCCESS, translated='{translated[:80]}{'...' if len(translated) > 80 else ''}'",
            )
            return {
                "original": text,
                "translated": translated,
                "source_lang": source_lang or "auto",
                "sequence": seq,
            }
        # Case 5: dịch thất bại
        else:
            self._log("🔴", f"[RESP] seq={seq} -> FAILED")
            return {
                "original": text,
                "translated": "[Dịch thất bại]",
                "source_lang": source_lang or "unknown",
                "sequence": seq,
            }

    def get_supported_languages(self):
        """Trả về danh sách ngôn ngữ hỗ trợ"""
        return self.SUPPORTED_LANGUAGES
