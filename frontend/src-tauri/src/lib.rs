use std::fs;
use std::sync::{Arc, Mutex, atomic::{AtomicBool, Ordering}};
use std::time::Duration;
use serde::{Deserialize, Serialize};

// Declare audio module
pub mod audio;
pub mod ollama;

use audio::{
    default_input_device, default_output_device, AudioStream,
    encode_single_audio,
};
use tauri::{Runtime, AppHandle, Emitter};
use log::{info as log_info, error as log_error, debug as log_debug};
use reqwest::multipart::{Form, Part};

// 🔥 SỬA VẤN ĐỀ 1: Dùng Mutex thay vì static mut (an toàn đa luồng)
static RECORDING_FLAG: AtomicBool = AtomicBool::new(false);
static MIC_BUFFER: Mutex<Option<Arc<Mutex<Vec<f32>>>>> = Mutex::new(None);
static SYSTEM_BUFFER: Mutex<Option<Arc<Mutex<Vec<f32>>>>> = Mutex::new(None);
static MIC_STREAM: Mutex<Option<Arc<AudioStream>>> = Mutex::new(None);
static SYSTEM_STREAM: Mutex<Option<Arc<AudioStream>>> = Mutex::new(None);
static IS_RUNNING_FLAG: Mutex<Option<Arc<AtomicBool>>> = Mutex::new(None);
static RECORDING_START_TIME: Mutex<Option<std::time::Instant>> = Mutex::new(None);

// Audio configuration constants
const CHUNK_DURATION_MS: u32 = 60000;
const CHUNK_OVERLAP_MS: u32 = 2000;
const WHISPER_SAMPLE_RATE: u32 = 16000;
const WAV_SAMPLE_RATE: u32 = 44100;
const WAV_CHANNELS: u16 = 1;
const SENTENCE_TIMEOUT_MS: u64 = 800;
const MIN_CHUNK_DURATION_MS: u32 = 1000;
const MIN_RECORDING_DURATION_MS: u64 = 2000;
const VOICE_ACTIVITY_THRESHOLD: f32 = 0.005;
const MAX_SENTENCE_LENGTH: usize = 200;

#[derive(Debug, Serialize, Clone)]
struct TranscriptUpdate {
    text: String,
    timestamp: String,
    source: String,
    t0: f32,
    t1: f32,
    seq: u64,
}

#[derive(Debug, Deserialize, Clone)]
struct TranscriptSegment {
    text: String,
    t0: f32,
    t1: f32,
}

#[derive(Debug, Deserialize)]
struct TranscriptResponse {
    segments: Vec<TranscriptSegment>,
    buffer_size_ms: i32,
}

#[derive(Debug)]
struct TranscriptAccumulator {
    current_sentence: String,
    sentence_start_time: f32,
    last_update_time: std::time::Instant,
    last_segment_hash: u64,
    last_was_sentence_end: bool,
    seq_counter: u64,
}

impl TranscriptAccumulator {
    fn new() -> Self {
        Self {
            current_sentence: String::new(),
            sentence_start_time: 0.0,
            last_update_time: std::time::Instant::now(),
            last_segment_hash: 0,
            last_was_sentence_end: false,
            seq_counter: 0,
        }
    }

    fn is_sentence_boundary(&self, text: &str, _is_continuation: bool) -> bool {
        if text.ends_with('.') || text.ends_with('!') || text.ends_with('?') {
            return true;
        }
        if self.current_sentence.len() > MAX_SENTENCE_LENGTH {
            return true;
        }
        if self.last_was_sentence_end && !text.is_empty() {
            let first_char = text.chars().next().unwrap();
            if first_char.is_uppercase() {
                return true;
            }
        }
        let lower_text = text.to_lowercase();
        let sentence_starters = [
            " and ", " but ", " so ", " then ", " however ", 
            " therefore ", " consequently ", " additionally ",
            " furthermore ", " moreover ", " nevertheless "
        ];
        for starter in sentence_starters {
            if lower_text.starts_with(starter) && !self.current_sentence.is_empty() {
                return true;
            }
        }
        if text.starts_with('\n') || text.starts_with("\r\n") {
            return true;
        }
        false
    }

    fn add_segment(&mut self, segment: &TranscriptSegment) -> Option<TranscriptUpdate> {
        log_debug!("Processing new transcript segment: {:?}", segment);
        self.last_update_time = std::time::Instant::now();
        let clean_text = segment.text
            .replace("[BLANK_AUDIO]", "")
            .replace("[AUDIO OUT]", "")
            .replace("  ", " ")
            .trim()
            .to_string();
        let duration = segment.t1 - segment.t0;
        if clean_text.is_empty() || duration < 0.3 {
            return None;
        }
        if clean_text.len() < 2 && duration < 0.5 {
            return None;
        }
        use std::hash::{Hash, Hasher};
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        segment.text.hash(&mut hasher);
        segment.t0.to_bits().hash(&mut hasher);
        segment.t1.to_bits().hash(&mut hasher);
        let segment_hash = hasher.finish();
        if segment_hash == self.last_segment_hash {
            return None;
        }
        self.last_segment_hash = segment_hash;
        if self.current_sentence.is_empty() {
            self.sentence_start_time = segment.t0;
        }
        if !self.current_sentence.is_empty() && !self.current_sentence.ends_with(' ') {
            self.current_sentence.push(' ');
        }
        self.current_sentence.push_str(&clean_text);
        let is_boundary = self.is_sentence_boundary(&clean_text, false);
        if is_boundary {
            let sentence = std::mem::take(&mut self.current_sentence);
            self.last_was_sentence_end = true;
            self.seq_counter += 1;
            if !sentence.trim().is_empty() {
                let update = TranscriptUpdate {
                    text: sentence.trim().to_string(),
                    timestamp: format!("{:.1} - {:.1}", self.sentence_start_time, segment.t1),
                    source: "Mixed Audio".to_string(),
                    t0: self.sentence_start_time,
                    t1: segment.t1,
                    seq: self.seq_counter,
                };
                log_debug!("Generated transcript update: seq={}", self.seq_counter);
                return Some(update);
            }
        } else {
            self.last_was_sentence_end = false;
        }
        None
    }

    fn check_timeout(&mut self) -> Option<TranscriptUpdate> {
        if !self.current_sentence.is_empty() && 
           self.last_update_time.elapsed() > Duration::from_millis(SENTENCE_TIMEOUT_MS) {
            let sentence = std::mem::take(&mut self.current_sentence);
            let current_time = self.sentence_start_time + (SENTENCE_TIMEOUT_MS as f32 / 1000.0);
            self.seq_counter += 1;
            if !sentence.trim().is_empty() {
                let update = TranscriptUpdate {
                    text: sentence.trim().to_string(),
                    timestamp: format!("{:.1} - {:.1}", self.sentence_start_time, current_time),
                    source: "Mixed Audio".to_string(),
                    t0: self.sentence_start_time,
                    t1: current_time,
                    seq: self.seq_counter,
                };
                log_debug!("Timeout - emitting incomplete sentence: seq={}", self.seq_counter);
                return Some(update);
            }
        }
        None
    }
}

fn has_voice_activity(samples: &[f32], threshold: f32) -> bool {
    let window_size = (WHISPER_SAMPLE_RATE as f32 * 0.025) as usize;
    let step = window_size / 2;
    for chunk in samples.chunks(step) {
        let max_amplitude = chunk.iter().fold(0.0f32, |max, &s| max.max(s.abs()));
        if max_amplitude > threshold {
            return true;
        }
    }
    false
}

fn resample_audio(samples: &[f32], from_rate: u32, to_rate: u32) -> Vec<f32> {
    if from_rate == to_rate {
        return samples.to_vec();
    }
    let ratio = to_rate as f32 / from_rate as f32;
    let new_len = (samples.len() as f32 * ratio) as usize;
    let mut resampled = Vec::with_capacity(new_len);
    for i in 0..new_len {
        let src_pos = i as f32 / ratio;
        let idx = src_pos.floor() as usize;
        let frac = src_pos - idx as f32;
        let sample = if idx + 1 < samples.len() {
            samples[idx] * (1.0 - frac) + samples[idx + 1] * frac
        } else if idx < samples.len() {
            samples[idx]
        } else {
            0.0
        };
        resampled.push(sample);
    }
    resampled
}

async fn send_audio_chunk(chunk: Vec<f32>, client: &reqwest::Client) -> Result<TranscriptResponse, String> {
    log_debug!("Preparing to send audio chunk of size: {}", chunk.len());
    let bytes: Vec<u8> = chunk.iter()
        .flat_map(|&sample| {
            let clamped = sample.max(-1.0).min(1.0);
            clamped.to_le_bytes().to_vec()
        })
        .collect();
    let max_retries = 3;
    let mut retry_count = 0;
    let mut last_error = String::new();
    while retry_count <= max_retries {
        if retry_count > 0 {
            let delay = Duration::from_millis(100 * (2_u64.pow(retry_count as u32)));
            log::info!("Retry attempt {} of {}. Waiting {:?} before retry...", 
                      retry_count, max_retries, delay);
            tokio::time::sleep(delay).await;
        }
        let part = Part::bytes(bytes.clone())
            .file_name("audio.raw")
            .mime_str("audio/x-raw")
            .unwrap();
        let form = Form::new().part("audio", part);
        match client.post("http://127.0.0.1:8178/stream")
            .multipart(form)
            .send()
            .await {
                Ok(response) => {
                    match response.json::<TranscriptResponse>().await {
                        Ok(transcript) => return Ok(transcript),
                        Err(e) => {
                            last_error = e.to_string();
                            log::error!("Failed to parse response: {}", last_error);
                        }
                    }
                }
                Err(e) => {
                    last_error = e.to_string();
                    log::error!("Request failed: {}", last_error);
                }
            }
        retry_count += 1;
    }
    Err(format!("Failed after {} retries. Last error: {}", max_retries, last_error))
}

#[tauri::command]
async fn start_recording<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    log_info!("Attempting to start recording...");
    if is_recording() {
        log_error!("Recording already in progress");
        return Err("Recording already in progress".to_string());
    }
    RECORDING_FLAG.store(true, Ordering::SeqCst);
    log_info!("Recording flag set to true");
    
    *RECORDING_START_TIME.lock().unwrap() = Some(std::time::Instant::now());
    *MIC_BUFFER.lock().unwrap() = Some(Arc::new(Mutex::new(Vec::new())));
    *SYSTEM_BUFFER.lock().unwrap() = Some(Arc::new(Mutex::new(Vec::new())));
    
    let mic_device = Arc::new(default_input_device().map_err(|e| {
        log_error!("Failed to get default input device: {}", e);
        e.to_string()
    })?);
    let system_device = Arc::new(default_output_device().map_err(|e| {
        log_error!("Failed to get default output device: {}", e);
        e.to_string()
    })?);
    let is_running = Arc::new(AtomicBool::new(true));
    let mic_stream = AudioStream::from_device(mic_device.clone(), is_running.clone())
        .await
        .map_err(|e| {
            log_error!("Failed to create microphone stream: {}", e);
            e.to_string()
        })?;
    let mic_stream = Arc::new(mic_stream);
    let system_stream = AudioStream::from_device(system_device.clone(), is_running.clone())
        .await
        .map_err(|e| {
            log_error!("Failed to create system stream: {}", e);
            e.to_string()
        })?;
    let system_stream = Arc::new(system_stream);
    
    *MIC_STREAM.lock().unwrap() = Some(mic_stream.clone());
    *SYSTEM_STREAM.lock().unwrap() = Some(system_stream.clone());
    *IS_RUNNING_FLAG.lock().unwrap() = Some(is_running.clone());
    
    let client = reqwest::Client::new();
    let app_handle = app.clone();
    let mic_receiver = mic_stream.subscribe().await;
    let mut mic_receiver_clone = mic_receiver.resubscribe();
    let mut system_receiver = system_stream.subscribe().await;
    let temp_dir = std::env::temp_dir();
    let debug_dir = temp_dir.join("meeting_minutes_debug");
    fs::create_dir_all(&debug_dir).map_err(|e| {
        log_error!("Failed to create debug directory: {}", e);
        e.to_string()
    })?;
    let chunk_counter = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let chunk_counter_clone = chunk_counter.clone();
    let mut accumulator = TranscriptAccumulator::new();
    let mut cumulative_seconds: f32 = 0.0;
    println!("⏱️ [RUST] cumulative_seconds initialized to 0.0");
    let device_config = mic_stream.device_config.clone();
    let sample_rate = device_config.sample_rate().0;
    let channels = device_config.channels();
    tokio::spawn(async move {
        let chunk_samples = (WHISPER_SAMPLE_RATE as f32 * (CHUNK_DURATION_MS as f32 / 1000.0)) as usize;
        let overlap_samples = (WHISPER_SAMPLE_RATE as f32 * (CHUNK_OVERLAP_MS as f32 / 1000.0)) as usize;
        let min_samples = (WHISPER_SAMPLE_RATE as f32 * (MIN_CHUNK_DURATION_MS as f32 / 1000.0)) as usize;
        let mut current_chunk: Vec<f32> = Vec::with_capacity(chunk_samples);
        let mut last_chunk_tail: Vec<f32> = Vec::new();
        let mut last_chunk_time = std::time::Instant::now();
        log_info!("Mic config: {} Hz, {} channels", sample_rate, channels);
        while is_running.load(Ordering::SeqCst) {
            if let Some(update) = accumulator.check_timeout() {
                if let Err(e) = app_handle.emit("transcript-update", update) {
                    log_error!("Failed to send timeout transcript update: {}", e);
                }
            }
            let mut new_samples = Vec::new();
            let mut mic_samples = Vec::new();
            let mut system_samples = Vec::new();
            
            while let Ok(chunk) = mic_receiver_clone.try_recv() {
                log_debug!("Received {} mic samples", chunk.len());
                let chunk_clone = chunk.clone();
                mic_samples.extend(chunk);
                if let Some(buffer) = MIC_BUFFER.lock().unwrap().as_ref() {
                    if let Ok(mut guard) = buffer.lock() {
                        guard.extend(chunk_clone);
                    }
                }
            }
            while let Ok(chunk) = system_receiver.try_recv() {
                log_debug!("Received {} system samples", chunk.len());
                let chunk_clone = chunk.clone();
                system_samples.extend(chunk);
                if let Some(buffer) = SYSTEM_BUFFER.lock().unwrap().as_ref() {
                    if let Ok(mut guard) = buffer.lock() {
                        guard.extend(chunk_clone);
                    }
                }
            }
            let max_len = mic_samples.len().max(system_samples.len());
            for i in 0..max_len {
                let mic_sample = if i < mic_samples.len() { mic_samples[i] } else { 0.0 };
                let system_sample = if i < system_samples.len() { system_samples[i] } else { 0.0 };
                // 🔥 BẬT MIC: Mix cả mic và system
                let mixed = (mic_sample * 1.2) + (system_sample * 0.7);
                new_samples.push(mixed.clamp(-1.0, 1.0));
            }
            let samples_to_process = if !last_chunk_tail.is_empty() {
                let mut combined = last_chunk_tail.clone();
                combined.extend(new_samples);
                combined
            } else {
                new_samples
            };
            for sample in samples_to_process {
                current_chunk.push(sample);
            }
            let should_send = current_chunk.len() >= chunk_samples || 
                            (current_chunk.len() >= min_samples && 
                             last_chunk_time.elapsed() >= Duration::from_millis(CHUNK_DURATION_MS as u64));
            if should_send {
                log_info!("Should send chunk with {} samples", current_chunk.len());
                let chunk_to_send = current_chunk.clone();
                
                // 🔥 SỬA VẤN ĐỀ 3: Tính thời gian đúng với sample_rate thực tế
                let chunk_duration_secs = chunk_to_send.len() as f32 / sample_rate as f32;
                
                let has_voice = has_voice_activity(&chunk_to_send, VOICE_ACTIVITY_THRESHOLD);
                if !has_voice {
                    println!("🔇 [RUST] Skipping silent chunk (no voice activity detected)");
                    cumulative_seconds += chunk_duration_secs;
                    current_chunk.clear();
                    last_chunk_time = std::time::Instant::now();
                    continue;
                }
                if chunk_to_send.len() > overlap_samples {
                    last_chunk_tail = chunk_to_send[chunk_to_send.len() - overlap_samples..].to_vec();
                } else {
                    last_chunk_tail = chunk_to_send.clone();
                }
                current_chunk.clear();
                last_chunk_time = std::time::Instant::now();
                let chunk_num = chunk_counter_clone.fetch_add(1, Ordering::SeqCst);
                log_info!("Processing chunk {}", chunk_num);
                println!("🔄 [RUST] Overlap: chunk {} tail size = {} samples ({:.1}s)", 
                chunk_num, last_chunk_tail.len(), 
                last_chunk_tail.len() as f32 / WHISPER_SAMPLE_RATE as f32);
                if !mic_samples.is_empty() {
                    let mic_chunk_path = debug_dir.join(format!("chunk_{}_mic.wav", chunk_num));
                    let mic_bytes: Vec<u8> = mic_samples.iter()
                        .flat_map(|&sample| {
                            let clamped = sample.max(-1.0).min(1.0);
                            clamped.to_le_bytes().to_vec()
                        })
                        .collect();
                    let _ = encode_single_audio(&mic_bytes, WAV_SAMPLE_RATE, 1, &mic_chunk_path);
                }
                if !system_samples.is_empty() {
                    let system_chunk_path = debug_dir.join(format!("chunk_{}_system.wav", chunk_num));
                    let system_bytes: Vec<u8> = system_samples.iter()
                        .flat_map(|&sample| {
                            let clamped = sample.max(-1.0).min(1.0);
                            clamped.to_le_bytes().to_vec()
                        })
                        .collect();
                    let _ = encode_single_audio(&system_bytes, WAV_SAMPLE_RATE, 1, &system_chunk_path);
                }
                if !chunk_to_send.is_empty() {
                    let mixed_chunk_path = debug_dir.join(format!("chunk_{}_mixed.wav", chunk_num));
                    let mixed_bytes: Vec<u8> = chunk_to_send.iter()
                        .flat_map(|&sample| {
                            let clamped = sample.max(-1.0).min(1.0);
                            clamped.to_le_bytes().to_vec()
                        })
                        .collect();
                    let _ = encode_single_audio(&mixed_bytes, WAV_SAMPLE_RATE, 1, &mixed_chunk_path);
                }
                if chunk_num > 10 {
                    if let Ok(entries) = fs::read_dir(&debug_dir) {
                        for entry in entries.flatten() {
                            if let Some(name) = entry.file_name().to_str() {
                                if name.starts_with("chunk_") && 
                                   name.ends_with(".wav") && 
                                   !name.contains(&format!("chunk_{}", chunk_num)) {
                                    let _ = fs::remove_file(entry.path());
                                }
                            }
                        }
                    }
                }
                let before_len = chunk_to_send.len();
                println!("📊 [RUST] Resample: before={} samples @ {}Hz", before_len, sample_rate);
                let whisper_samples = if sample_rate != WHISPER_SAMPLE_RATE {
                    resample_audio(&chunk_to_send, sample_rate, WHISPER_SAMPLE_RATE)
                } else {
                    chunk_to_send
                };
                let after_len = whisper_samples.len();
                println!("📊 [RUST] Resample: after={} samples @ {}Hz (ratio={:.2})", 
                         after_len, WHISPER_SAMPLE_RATE,
                         after_len as f32 / before_len as f32);
                println!("🎙️ [RUST] Sending chunk {}: {} samples ({:.1}s)", 
                         chunk_num, whisper_samples.len(),
                         whisper_samples.len() as f32 / WHISPER_SAMPLE_RATE as f32);
                match send_audio_chunk(whisper_samples, &client).await {
                    Ok(response) => {
                        println!("✅ [RUST] Whisper response: {} segments", response.segments.len());
                        for (i, seg) in response.segments.iter().enumerate() {
                            let text_preview: String = seg.text.chars().take(50).collect();
                            println!("   Segment {}: t0={:.2}s, t1={:.2}s, text='{}'", 
                                     i, seg.t0, seg.t1, text_preview);
                        } 
                        log_info!("Received {} transcript segments", response.segments.len());
                        for segment in response.segments {
                            let adjusted_t0 = segment.t0 + cumulative_seconds;
                            let adjusted_t1 = segment.t1 + cumulative_seconds;
                            let adjusted_segment = TranscriptSegment {
                                text: segment.text,
                                t0: adjusted_t0,
                                t1: adjusted_t1,
                            };
                            if let Some(update) = accumulator.add_segment(&adjusted_segment) {
                                if let Err(e) = app_handle.emit("transcript-update", update) {
                                    log_error!("Failed to emit transcript update: {}", e);
                                }
                            }
                        }
                        cumulative_seconds += chunk_duration_secs;
                        println!("⏱️ [RUST] cumulative_seconds updated: {:.1}s (+{:.1}s)", 
                                 cumulative_seconds, chunk_duration_secs);
                    }
                    Err(e) => {
                        log_error!("Transcription error: {}", e);
                        cumulative_seconds += chunk_duration_secs;
                    }
                }
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        if let Some(update) = accumulator.check_timeout() {
            if let Err(e) = app_handle.emit("transcript-update", update) {
                log_error!("Failed to send final transcript update: {}", e);
            }
        }
        log_info!("Transcription task ended");
    });
    Ok(())
}

// 🔥 SỬA QUAN TRỌNG: Nhận trực tiếp save_path thay vì struct
#[tauri::command]
async fn stop_recording(save_path: String) -> Result<(), String> {
    log_info!("Attempting to stop recording...");
    
    if !RECORDING_FLAG.load(Ordering::SeqCst) {
        log_info!("Recording is already stopped");
        return Ok(());
    }

    let elapsed_ms = RECORDING_START_TIME.lock().unwrap()
        .map(|start| start.elapsed().as_millis() as u64)
        .unwrap_or(0);

    if elapsed_ms < MIN_RECORDING_DURATION_MS {
        let remaining = MIN_RECORDING_DURATION_MS - elapsed_ms;
        log_info!("Waiting for minimum recording duration ({} ms remaining)...", remaining);
        tokio::time::sleep(Duration::from_millis(remaining)).await;
    }

    RECORDING_FLAG.store(false, Ordering::SeqCst);
    log_info!("Recording flag set to false");
    
    // 🔥 SỬA LỖI Send: Lấy và giải phóng lock ngay lập tức
    let is_running_opt = IS_RUNNING_FLAG.lock().unwrap().take();
    if let Some(is_running) = is_running_opt {
        is_running.store(false, Ordering::SeqCst);
        tokio::time::sleep(Duration::from_millis(100)).await;
        
        // Lấy và giải phóng lock cho MIC_STREAM
        let mic_stream_opt = MIC_STREAM.lock().unwrap().take();
        if let Some(mic_stream) = mic_stream_opt {
            log_info!("Stopping microphone stream...");
            let _ = mic_stream.stop().await;
        }
        
        // Lấy và giải phóng lock cho SYSTEM_STREAM
        let system_stream_opt = SYSTEM_STREAM.lock().unwrap().take();
        if let Some(system_stream) = system_stream_opt {
            log_info!("Stopping system stream...");
            let _ = system_stream.stop().await;
        }
        
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    
    // 🔥 Lấy dữ liệu buffer an toàn
    let mic_data = MIC_BUFFER.lock().unwrap().take()
        .and_then(|b| b.lock().ok().map(|g| g.clone()))
        .unwrap_or_default();
    let system_data = SYSTEM_BUFFER.lock().unwrap().take()
        .and_then(|b| b.lock().ok().map(|g| g.clone()))
        .unwrap_or_default();
    
    let max_len = mic_data.len().max(system_data.len());
    let mut mixed_data = Vec::with_capacity(max_len);
    
    for i in 0..max_len {
        let mic_sample = if i < mic_data.len() { mic_data[i] } else { 0.0 };
        let system_sample = if i < system_data.len() { system_data[i] } else { 0.0 };
        // 🔥 BẬT MIC: Mix cả mic và system khi lưu file
        let mixed = (mic_sample * 1.2) + (system_sample * 0.7);
        mixed_data.push(mixed.clamp(-1.0, 1.0));
    }

    if mixed_data.is_empty() {
        log_error!("No audio data captured");
        return Err("No audio data captured".to_string());
    }
    
    log_info!("Mixed {} audio samples", mixed_data.len());
    
    let mut bytes = Vec::with_capacity(mixed_data.len() * 2);
    for &sample in mixed_data.iter() {
        let value = (sample.max(-1.0).min(1.0) * 32767.0) as i16;
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    
    log_info!("Converted to {} bytes of PCM data", bytes.len());

    let data_size = bytes.len() as u32;
    let sample_rate = WAV_SAMPLE_RATE;
    let channels = 1u16;
    let bits_per_sample = 16u16;
    let block_align = channels * (bits_per_sample / 8);
    let byte_rate = sample_rate * block_align as u32;
    let file_size = 36 + data_size;
    
    let mut wav_file = Vec::with_capacity(44 + bytes.len());
    
    // Header chuẩn RIFF
    wav_file.extend_from_slice(b"RIFF");
    wav_file.extend_from_slice(&file_size.to_le_bytes());
    wav_file.extend_from_slice(b"WAVE");
    wav_file.extend_from_slice(b"fmt ");
    wav_file.extend_from_slice(&16u32.to_le_bytes());
    wav_file.extend_from_slice(&1u16.to_le_bytes());
    wav_file.extend_from_slice(&channels.to_le_bytes());
    wav_file.extend_from_slice(&sample_rate.to_le_bytes());
    wav_file.extend_from_slice(&byte_rate.to_le_bytes());
    wav_file.extend_from_slice(&block_align.to_le_bytes());
    wav_file.extend_from_slice(&bits_per_sample.to_le_bytes());
    wav_file.extend_from_slice(b"data");
    wav_file.extend_from_slice(&data_size.to_le_bytes());
    wav_file.extend_from_slice(&bytes);
    
    // 🔥 QUAN TRỌNG: Dùng đúng đường dẫn save_path từ Frontend
    log_info!("💾 ĐANG GHI FILE VÀO: {} ({} bytes)", save_path, wav_file.len());
    
    if let Some(parent) = std::path::Path::new(&save_path).parent() {
        if !parent.exists() {
            log_info!("Creating directory: {:?}", parent);
            if let Err(e) = std::fs::create_dir_all(parent) {
                let err_msg = format!("Failed to create save directory: {}", e);
                log_error!("{}", err_msg);
                return Err(err_msg);
            }
        }
    }

    log_info!("Saving recording to: {}", save_path);
    match fs::write(&save_path, wav_file) {
        Ok(_) => log_info!("✅ Rust đã lưu file thành công tại: {}", save_path),
        Err(e) => {
            let err_msg = format!("Failed to save recording: {}", e);
            log_error!("{}", err_msg);
            return Err(err_msg);
        }
    }
    
    Ok(())
}

#[tauri::command]
fn is_recording() -> bool {
    RECORDING_FLAG.load(Ordering::SeqCst)
}

#[tauri::command]
fn read_audio_file(file_path: String) -> Result<Vec<u8>, String> {
    match std::fs::read(&file_path) {
        Ok(data) => Ok(data),
        Err(e) => Err(format!("Failed to read audio file: {}", e))
    }
}

#[tauri::command]
async fn save_transcript(file_path: String, content: String) -> Result<(), String> {
    log::info!("Saving transcript to: {}", file_path);
    if let Some(parent) = std::path::Path::new(&file_path).parent() {
        if !parent.exists() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("Failed to create directory: {}", e))?;
        }
    }
    std::fs::write(&file_path, content)
        .map_err(|e| format!("Failed to write transcript: {}", e))?;
    log::info!("Transcript saved successfully");
    Ok(())
}

pub fn run() {
    log::set_max_level(log::LevelFilter::Info);
    tauri::Builder::default()
        .setup(|_app| {
            log::info!("Application setup complete");
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            start_recording,
            stop_recording,
            is_recording,
            read_audio_file,
            save_transcript,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}