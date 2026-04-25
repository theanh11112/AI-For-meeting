# backend/app/whisperx_service.py
import os
import torch
import numpy as np
import librosa
import whisperx
import gc
from pyannote.audio import Pipeline
from dotenv import load_dotenv

load_dotenv()


class WhisperXService:
    def __init__(self):
        self.device = "cpu"
        self.compute_type = "int8"
        self.hf_token = os.getenv("HUGGINGFACE_TOKEN")

        print(f"🚀 Initializing WhisperX on {self.device}...")
        self.model = whisperx.load_model(
            "large-v3-turbo", self.device, compute_type=self.compute_type
        )

        self.align_model = None
        self.align_metadata = None
        self.diarize_pipeline = None

        if self.hf_token:
            try:
                print("📥 Loading diarization pipeline (pyannote 3.0+)...")
                self.diarize_pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.0", token=self.hf_token
                )
                print("✅ Diarization pipeline loaded successfully")
            except Exception as e:
                print(f"⚠️ Diarization load failed: {e}")
        else:
            print("⚠️ No HF token, diarization disabled")

    async def process_audio(self, audio_path: str) -> dict:
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        print(f"🎤 Xử lý Diarization cho file: {audio_path}")
        audio_numpy = None
        sample_rate = None

        # ==================== 1. LOAD AUDIO ====================
        try:
            audio_numpy, sample_rate = librosa.load(audio_path, sr=16000, mono=True)
            print(f"✅ Librosa loaded. Duration: {len(audio_numpy)/sample_rate:.2f}s")

        except Exception as e:
            print(f"⚠️ Librosa fail: {e}")

            try:
                print("🔄 Fallback: Reading RAW audio data (bypassing header)...")
                with open(audio_path, "rb") as f:
                    raw_data = f.read()

                    if len(raw_data) < 44:
                        raise RuntimeError(f"File quá nhỏ: {len(raw_data)} bytes")

                    audio_numpy = (
                        np.frombuffer(raw_data[44:], dtype=np.int16).astype(np.float32)
                        / 32768.0
                    )
                    sample_rate = 44100

                    print(
                        f"   Raw data size: {len(raw_data)} bytes, audio samples: {len(audio_numpy)}"
                    )

                    if sample_rate != 16000:
                        print(f"   🔄 Resampling from {sample_rate}Hz to 16000Hz")
                        audio_numpy = librosa.resample(
                            audio_numpy, orig_sr=sample_rate, target_sr=16000
                        )
                        sample_rate = 16000

                    print(
                        f"✅ RAW fallback successful. Duration: {len(audio_numpy)/sample_rate:.2f}s"
                    )

            except Exception as e2:
                print(f"❌ All loading methods failed: {e2}")
                raise RuntimeError(f"Could not read audio file: {e2}")

        waveform = torch.from_numpy(audio_numpy).unsqueeze(0)

        # ==================== 2. TRANSCRIPTION ====================
        print("📝 Transcribing with WhisperX...")
        try:
            result = self.model.transcribe(
                audio_numpy,
                batch_size=16,
                language="en",
            )
            print(f"✅ Transcription complete: {len(result['segments'])} segments")
        except Exception as e:
            print(f"❌ Transcription failed: {e}")
            raise

        # ==================== 3. ALIGNMENT ====================
        print("🔄 Running alignment...")
        try:
            if self.align_model is None:
                self.align_model, self.align_metadata = whisperx.load_align_model(
                    language_code=result["language"], device=self.device
                )
            result = whisperx.align(
                result["segments"],
                self.align_model,
                self.align_metadata,
                audio_numpy,
                self.device,
            )
            print("✅ Alignment complete")
        except Exception as e:
            print(f"⚠️ Alignment failed: {e}")

        # ==================== 4. DIARIZATION ====================
        if self.diarize_pipeline:
            print("👥 Running speaker diarization...")
            try:
                diarize_output = self.diarize_pipeline(
                    {"waveform": waveform, "sample_rate": sample_rate}
                )

                speaker_segments = []

                if hasattr(diarize_output, "speaker_diarization"):
                    ann = diarize_output.speaker_diarization
                    if hasattr(ann, "itertracks"):
                        for turn, _, speaker in ann.itertracks(yield_label=True):
                            speaker_segments.append(
                                {
                                    "start": float(turn.start),
                                    "end": float(turn.end),
                                    "speaker": speaker,
                                }
                            )
                elif hasattr(diarize_output, "itertracks"):
                    for turn, _, speaker in diarize_output.itertracks(yield_label=True):
                        speaker_segments.append(
                            {
                                "start": float(turn.start),
                                "end": float(turn.end),
                                "speaker": speaker,
                            }
                        )
                elif hasattr(diarize_output, "annotation") and hasattr(
                    diarize_output.annotation, "itertracks"
                ):
                    for turn, _, speaker in diarize_output.annotation.itertracks(
                        yield_label=True
                    ):
                        speaker_segments.append(
                            {
                                "start": float(turn.start),
                                "end": float(turn.end),
                                "speaker": speaker,
                            }
                        )
                elif hasattr(diarize_output, "iterrows"):
                    for _, row in diarize_output.iterrows():
                        speaker_segments.append(
                            {
                                "start": float(row.get("start", 0.0)),
                                "end": float(row.get("end", 0.0)),
                                "speaker": row.get("speaker", "SPEAKER_00"),
                            }
                        )

                print(f"   Found {len(speaker_segments)} speaker segments")

                for segment in result["segments"]:
                    best_speaker = "SPEAKER_00"
                    max_overlap = 0
                    for spk_seg in speaker_segments:
                        overlap_start = max(segment["start"], spk_seg["start"])
                        overlap_end = min(segment["end"], spk_seg["end"])
                        overlap_duration = max(0, overlap_end - overlap_start)
                        if overlap_duration > max_overlap:
                            max_overlap = overlap_duration
                            best_speaker = spk_seg["speaker"]
                    segment["speaker"] = best_speaker

                unique_speakers = sorted(
                    list(set(s["speaker"] for s in speaker_segments))
                )
                if not unique_speakers:
                    unique_speakers = ["SPEAKER_00 (Fallback)"]
                print(f"✅ Diarization finished. Speakers: {unique_speakers}")

            except Exception as e:
                print(f"⚠️ Diarization error: {e}")
                for seg in result["segments"]:
                    seg["speaker"] = "SPEAKER_00"
        else:
            print("⚠️ Diarization disabled, assigning default speaker")
            for seg in result["segments"]:
                seg["speaker"] = "UNKNOWN"

        # ==================== 5. GIẢI PHÓNG RAM NHẸ (KHÔNG XÓA MODEL) ====================
        # 🔥 QUAN TRỌNG: Không del self.model, self.align_model, self.diarize_pipeline ở đây
        # Vì main.py đang cache service này để tái sử dụng
        # Chỉ dọn dẹp các reference tạm thời và clear cache

        # Chỉ clear các biến tạm trong function
        del waveform
        del audio_numpy

        # Gọi dọn rác
        gc.collect()

        # Clear cache Metal (Mac M2)
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
            print("✅ Cleared Metal cache (MPS)")

        print("♻️ WhisperX processing complete (model kept in cache for next use)")

        # ==================== 6. FORMAT OUTPUT ====================
        final_segments = []
        for seg in result["segments"]:
            final_segments.append(
                {
                    "text": seg["text"].strip(),
                    "start": round(seg["start"], 2),
                    "end": round(seg["end"], 2),
                    "speaker": seg.get("speaker", "SPEAKER_00"),
                }
            )

        print(f"📤 Returning {len(final_segments)} segments")
        return {"segments": final_segments}
