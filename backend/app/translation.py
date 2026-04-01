import httpx
import os
from typing import Optional


class TranslationService:
    def __init__(self):
        self.groq_api_key = os.getenv("GROQ_API_KEY")

    # Danh sách ngôn ngữ hỗ trợ
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

    async def translate(
        self, text: str, target_lang: str, source_lang: str = None
    ) -> dict:
        """
        Dịch text sang target_lang
        Returns: {"original": text, "translated": translated_text, "source_lang": detected_lang}
        """
        if not text or text.strip() == "":
            return {
                "original": text,
                "translated": "",
                "source_lang": source_lang or "unknown",
            }

        # Nếu target_lang là "original", không dịch
        if target_lang == "original":
            return {
                "original": text,
                "translated": text,
                "source_lang": source_lang or "auto",
            }

        # Nếu không có Groq API key
        if not self.groq_api_key:
            print("⚠️ No Groq API key found. Translation disabled.")
            return {
                "original": text,
                "translated": text,
                "source_lang": source_lang or "unknown",
            }

        target_name = self.SUPPORTED_LANGUAGES.get(target_lang, target_lang)

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Prompt để dịch
            if source_lang and source_lang != "auto":
                source_name = self.SUPPORTED_LANGUAGES.get(source_lang, source_lang)
                prompt = f"Translate the following text from {source_name} to {target_name}. Output only the translation, no explanations, no quotes.\n\nText: {text}\n\nTranslation:"
            else:
                prompt = f"Translate the following text to {target_name}. Output only the translation, no explanations, no quotes.\n\nText: {text}\n\nTranslation:"

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
                    # Loại bỏ quotes nếu có
                    if translated.startswith('"') and translated.endswith('"'):
                        translated = translated[1:-1]
                    return {
                        "original": text,
                        "translated": translated,
                        "source_lang": source_lang or "auto",
                    }
                else:
                    print(f"Translation error: {response.status_code}")
                    return {
                        "original": text,
                        "translated": text,
                        "source_lang": source_lang or "unknown",
                    }

            except Exception as e:
                print(f"Translation exception: {e}")
                return {
                    "original": text,
                    "translated": text,
                    "source_lang": source_lang or "unknown",
                }

    def get_supported_languages(self):
        """Trả về danh sách ngôn ngữ hỗ trợ"""
        return self.SUPPORTED_LANGUAGES
