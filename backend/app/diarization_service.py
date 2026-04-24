import os
import torch
import whisperx
from typing import Dict, Optional
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(env_path)


class WhisperXDiarization:
    def __init__(self):
        self.device = "cpu"
        self.compute_type = "float32"
        print(
            f"🔥 WhisperX using device: {self.device}, compute_type: {self.compute_type}"
        )

        print("📥 Loading Whisper model...")
        try:
            self.model = whisperx.load_model(
                "large-v3",
                device=self.device,
                compute_type=self.compute_type,
                language=None,
            )
            print("✅ Whisper model loaded")
        except Exception as e:
            print(f"❌ Failed to load Whisper model: {e}")
            raise

        print("📥 Loading diarization model...")
        self.diarize_model = None
        hf_token = os.getenv("HUGGINGFACE_TOKEN")
        if not hf_token:
            print("⚠️ HUGGINGFACE_TOKEN not found. Diarization disabled.")
            return

        print(f"🔑 HUGGINGFACE_TOKEN found")
        try:
            from pyannote.audio import Pipeline

            self.diarize_model = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1", token=hf_token
            )
            self.diarize_model.to(torch.device(self.device))
            print("✅ Diarization model loaded")
        except TypeError:
            try:
                self.diarize_model = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1", use_auth_token=hf_token
                )
                self.diarize_model.to(torch.device(self.device))
                print("✅ Diarization model loaded (legacy)")
            except Exception as e:
                print(f"⚠️ Failed to load diarization model: {e}")
        except Exception as e:
            print(f"⚠️ Failed to load diarization model: {e}")

    async def process_audio(self, audio_path: str) -> Dict:
        print(f"🎤 Processing audio: {audio_path}")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        print("📝 Transcribing audio...")
        # ==================== SỬA: TỐI ƯU THAM SỐ CHO WHISPER ====================
        result = self.model.transcribe(
            audio_path,
            batch_size=32,  # Tăng batch_size để xử lý nhanh hơn
            condition_on_previous_text=True,  # Cho phép dùng ngữ cảnh từ chunk trước
            no_speech_threshold=0.6,  # Giảm ngưỡng để nhận diện tốt hơn
            compression_ratio_threshold=2.4,  # Ngưỡng tỷ lệ nén
            logprob_threshold=-1.0,  # Ngưỡng log probability
        )
        # ==================== KẾT THÚC SỬA ====================
        print(f"   Found {len(result['segments'])} segments")

        result_aligned = result
        try:
            if hasattr(self.model, "align_model") and self.model.align_model:
                print("📝 Aligning words...")
                result_aligned = whisperx.align(
                    result["segments"],
                    self.model.align_model,
                    self.model.align_metadata,
                    audio_path,
                    self.device,
                    return_char_alignments=False,
                )
                print(f"   Aligned {len(result_aligned['segments'])} segments")
            else:
                print("⚠️ No align_model available, skipping alignment")
        except Exception as e:
            print(f"⚠️ Alignment failed: {e}")

        diarization = None
        if self.diarize_model:
            print("👥 Running speaker diarization...")
            try:
                import torchaudio

                waveform, sample_rate = torchaudio.load(audio_path)
                diarization = self.diarize_model(
                    {"waveform": waveform, "sample_rate": sample_rate}
                )
                print("✅ Speaker diarization completed")
            except Exception as e:
                print(f"⚠️ Diarization failed: {e}")
                diarization = None

        print("🔀 Merging transcription with speakers...")
        print(
            f"📊 [DIARIZATION] Total segments from WhisperX: {len(result_aligned['segments'])}"
        )
        speaker_counts = {}
        segments = []
        for seg in result_aligned["segments"]:
            speaker = "UNKNOWN"
            if diarization is not None:
                speaker = self._get_speaker_at_time(diarization, seg["start"])
            segments.append(
                {
                    "text": seg["text"].strip(),
                    "start": seg["start"],
                    "end": seg["end"],
                    "speaker": speaker,
                }
            )
            speaker_counts[speaker] = speaker_counts.get(speaker, 0) + 1
            print(
                f"   Segment: {seg['start']:.2f}s - {seg['end']:.2f}s -> Speaker: {speaker}"
            )
            print(f"📊 [DIARIZATION] Speaker distribution: {speaker_counts}")

        print(f"✅ Processed {len(segments)} segments")
        return {"segments": segments}

    def _get_speaker_at_time(self, diarization, timestamp: float) -> Optional[str]:
        """Lấy speaker label tại thời điểm timestamp (Đã fix lỗi itertracks)"""
        try:
            # 1. Cố gắng chuẩn hóa diarization thành đối tượng Annotation
            ann = None
            if hasattr(diarization, "annotation"):
                ann = diarization.annotation
            elif hasattr(diarization, "speaker_diarization"):
                ann = diarization.speaker_diarization
            elif hasattr(diarization, "as_annotation"):
                ann = diarization.as_annotation()
            elif hasattr(diarization, "itertracks"):
                ann = diarization

            # 2. Nếu lấy được Annotation chuẩn, dùng itertracks
            if ann is not None and hasattr(ann, "itertracks"):
                for segment, track, speaker in ann.itertracks(yield_label=True):
                    if segment.start - 0.1 <= timestamp <= segment.end + 0.1:
                        return speaker

            # 3. Fallback: Nếu trả về dạng dict (lý do chính gây lỗi)
            elif isinstance(diarization, dict) and "segments" in diarization:
                for seg in diarization["segments"]:
                    start = float(seg.get("start", 0.0))
                    end = float(seg.get("end", 0.0))
                    if start - 0.1 <= timestamp <= end + 0.1:
                        return seg.get("speaker", seg.get("label", "UNKNOWN"))

        except Exception as e:
            print(f"⚠️ Error getting speaker: {e}")

        return "UNKNOWN"
