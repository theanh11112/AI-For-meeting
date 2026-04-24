'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { Transcript, Summary, SummaryResponse } from '@/types';
import { EditableTitle } from '@/components/EditableTitle';
import { RecordingControls } from '@/components/RecordingControls';
import { AISummary } from '@/components/AISummary';
import { useSidebar } from '@/components/Sidebar/SidebarProvider';
import { listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';

// Danh sách ngôn ngữ hỗ trợ
const SUPPORTED_LANGUAGES = [
  { code: 'en', name: '🇬🇧 English', short: 'EN' },
  { code: 'vi', name: '🇻🇳 Tiếng Việt', short: 'VI' },
  { code: 'zh', name: '🇨🇳 中文', short: 'ZH' },
  { code: 'ja', name: '🇯🇵 日本語', short: 'JA' },
  { code: 'ko', name: '🇰🇷 한국어', short: 'KO' },
  { code: 'fr', name: '🇫🇷 Français', short: 'FR' },
  { code: 'de', name: '🇩🇪 Deutsch', short: 'DE' },
  { code: 'es', name: '🇪🇸 Español', short: 'ES' },
  { code: 'ru', name: '🇷🇺 Русский', short: 'RU' },
  { code: 'th', name: '🇹🇭 ไทย', short: 'TH' },
  { code: 'hi', name: '🇮🇳 हिन्दी', short: 'HI' },
  { code: 'it', name: '🇮🇹 Italiano', short: 'IT' },
  { code: 'pt', name: '🇵🇹 Português', short: 'PT' },
  { code: 'nl', name: '🇳🇱 Nederlands', short: 'NL' },
  { code: 'pl', name: '🇵🇱 Polski', short: 'PL' },
  { code: 'tr', name: '🇹🇷 Türkçe', short: 'TR' },
  { code: 'id', name: '🇮🇩 Indonesia', short: 'ID' },
  { code: 'ar', name: '🇸🇦 العربية', short: 'AR' },
];

interface TranscriptUpdate {
  text: string;
  timestamp: string;
  source: string;
  t0?: number;
  t1?: number;
  seq?: number;
}

interface ModelConfig {
  provider: 'ollama' | 'groq' | 'claude';
  model: string;
  whisperModel: string;
}

type SummaryStatus = 'idle' | 'processing' | 'summarizing' | 'regenerating' | 'completed' | 'error';

interface OllamaModel {
  name: string;
  id: string;
  size: string;
  modified: string;
}

interface TranslatedSegment {
  timestamp: string;
  original: string;
  translated: string;
  t0: number;
  t1: number;
  speaker?: string;
}

// 🔥 CẬP NHẬT: Thêm trường isVerified
interface TranscriptWithSpeaker extends Transcript {
  t0: number;
  t1: number;
  speaker?: string;
  seq?: number;
  isVerified?: boolean;
}

interface SpeakerMap {
  speaker_id: string;
  name: string;
  email: string;
}

export default function Home() {
  const [isRecording, setIsRecording] = useState(false);
  const [transcripts, setTranscripts] = useState<TranscriptWithSpeaker[]>([]);
  
  // Buffer & Refs cho ghép câu
  const transcriptBufferRef = useRef<TranscriptWithSpeaker[]>([]);
  const bufferTimerRef = useRef<number | null>(null);
  const transcriptsRef = useRef<TranscriptWithSpeaker[]>([]);
  const FLUSH_TIMEOUT_MS = 1000;
  
  const [showSummary, setShowSummary] = useState(false);
  const [summaryStatus, setSummaryStatus] = useState<SummaryStatus>('idle');
  const [barHeights, setBarHeights] = useState(['58%', '76%', '58%']);
  const [meetingTitle, setMeetingTitle] = useState('New Call');
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [aiSummary, setAiSummary] = useState<Summary | null>({
    key_points: { title: "Key Points", blocks: [] },
    action_items: { title: "Action Items", blocks: [] },
    decisions: { title: "Decisions", blocks: [] },
    main_topics: { title: "Main Topics", blocks: [] }
  });
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [modelConfig, setModelConfig] = useState<ModelConfig>({
    provider: 'ollama',
    model: 'llama3.2:latest',
    whisperModel: 'large-v3'
  });
  const [originalTranscript, setOriginalTranscript] = useState<string>('');
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [error, setError] = useState<string>('');

  // State cho dịch
  const [targetLanguage, setTargetLanguage] = useState('en');
  const [translatedSegments, setTranslatedSegments] = useState<TranslatedSegment[]>([]);
  const [isTranslating, setIsTranslating] = useState(false);
  const [detectedLanguage, setDetectedLanguage] = useState<string>('auto');

  // State cho diarization
  const [lastAudioFile, setLastAudioFile] = useState<string | null>(null);
  const [isDiarizing, setIsDiarizing] = useState(false);
  const [enableDiarization, setEnableDiarization] = useState(true);

  // State cho Speaker Mapping
  const [speakerMaps, setSpeakerMaps] = useState<SpeakerMap[]>([]);
  const [showSpeakerModal, setShowSpeakerModal] = useState(false);
  const [editingSpeakerId, setEditingSpeakerId] = useState<string>('');
  const [speakerForm, setSpeakerForm] = useState({ name: '', email: '' });

  const isStoppingRef = useRef(false);

  const modelOptions = {
    ollama: models.map(model => model.name),
    claude: ['claude-3-5-sonnet-latest'],
    groq: ['llama-3.3-70b-versatile'],
  };

  // Đồng bộ refs
  useEffect(() => {
    transcriptsRef.current = transcripts;
  }, [transcripts]);

  useEffect(() => {
    if (models.length > 0 && modelConfig.provider === 'ollama') {
      setModelConfig(prev => ({
        ...prev,
        model: models[0].name
      }));
    }
  }, [models]);

  // Functions cho Speaker Mapping
  const fetchSpeakers = useCallback(async () => {
    try {
      const res = await fetch('http://localhost:5167/speakers');
      const data = await res.json();
      if (data.speakers) setSpeakerMaps(data.speakers);
    } catch (err) {
      console.error('Lỗi khi tải danh bạ speaker:', err);
    }
  }, []);

  useEffect(() => {
    fetchSpeakers();
  }, [fetchSpeakers]);

  const getSpeakerDisplayName = useCallback((speakerId: string): string => {
    const mapped = speakerMaps.find(s => s.speaker_id === speakerId);
    if (mapped) return mapped.name;
    if (!speakerId || speakerId === 'UNKNOWN') return '[?]';
    if (speakerId.startsWith('SPEAKER_')) {
      return speakerId.replace('SPEAKER_', 'Người ');
    }
    return speakerId;
  }, [speakerMaps]);

  const handleSaveSpeaker = async () => {
    if (!speakerForm.name.trim()) return;
    
    try {
      await fetch('http://localhost:5167/speakers/map', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          speaker_id: editingSpeakerId,
          name: speakerForm.name,
          email: speakerForm.email,
        }),
      });
      await fetchSpeakers();
      setShowSpeakerModal(false);
      setSpeakerForm({ name: '', email: '' });
    } catch (err) {
      console.error('Lỗi khi lưu speaker:', err);
    }
  };

  const whisperModels = [
    'tiny', 'tiny.en', 'tiny-q5_1', 'tiny.en-q5_1', 'tiny-q8_0',
    'base', 'base.en', 'base-q5_1', 'base.en-q5_1', 'base-q8_0',
    'small', 'small.en', 'small.en-tdrz', 'small-q5_1', 'small.en-q5_1', 'small-q8_0',
    'medium', 'medium.en', 'medium-q5_0', 'medium.en-q5_0', 'medium-q8_0',
    'large-v1', 'large-v2', 'large-v2-q5_0', 'large-v2-q8_0',
    'large-v3', 'large-v3-q5_0', 'large-v3-turbo', 'large-v3-turbo-q5_0', 'large-v3-turbo-q8_0'
  ];

  const [showModelSettings, setShowModelSettings] = useState(false);
  const { setCurrentMeeting } = useSidebar();

  const formatTimeFromSeconds = (seconds: number): string => {
    if (seconds < 0) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const getSpeakerColor = (speaker: string): string => {
    if (!speaker || speaker === 'UNKNOWN') return 'bg-gray-100 text-gray-500';
    
    const colors = [
      'bg-blue-100 text-blue-700',
      'bg-green-100 text-green-700',
      'bg-purple-100 text-purple-700',
      'bg-orange-100 text-orange-700',
      'bg-pink-100 text-pink-700',
      'bg-indigo-100 text-indigo-700',
      'bg-teal-100 text-teal-700',
      'bg-rose-100 text-rose-700',
      'bg-amber-100 text-amber-700',
      'bg-cyan-100 text-cyan-700',
    ];
    
    const match = speaker.match(/\d+/);
    const index = match ? parseInt(match[0]) % colors.length : 0;
    return colors[index];
  };

  const flushTranscriptBuffer = useCallback(() => {
    const buffer = transcriptBufferRef.current;
    if (!buffer.length) return;

    if (bufferTimerRef.current) {
      clearTimeout(bufferTimerRef.current);
      bufferTimerRef.current = null;
    }

    setTranscripts(prev => {
      const combined = [...prev, ...buffer].sort((a, b) => a.t0 - b.t0);

      const result: TranscriptWithSpeaker[] = [];
      for (const seg of combined) {
        if (result.length === 0) {
          result.push({ ...seg });
          continue;
        }

        const last = result[result.length - 1];

        if (Math.abs(seg.t0 - last.t0) < 0.5) {
          continue;
        }

        const segFirstChar = seg.text.trim().charAt(0);
        const lastTrim = last.text.trim();
        const lastEndsWithPunct = /[.!?…]$/.test(lastTrim);

        if (
          segFirstChar &&
          segFirstChar === segFirstChar.toLowerCase() &&
          !lastEndsWithPunct
        ) {
          last.text = `${last.text} ${seg.text}`.trim();
          last.t1 = seg.t1;
        } else {
          result.push({ ...seg });
        }
      }

      transcriptsRef.current = result;
      return result;
    });

    transcriptBufferRef.current = [];
  }, []);

  const translateWithRetry = useCallback(async (
    text: string, 
    timestamp: string, 
    t0: number, 
    t1: number, 
    speaker?: string, 
    retryCount: number = 0
  ): Promise<TranslatedSegment | null> => {
    if (!text || text.trim() === '') return null;
    
    try {
      const response = await fetch('http://localhost:5167/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text,
          target_lang: targetLanguage,
          source_lang: 'auto',
          sequence: Math.floor(t0 * 100)
        })
      });
      
      if (response.status === 429 && retryCount < 3) {
        await new Promise(resolve => setTimeout(resolve, 2000 * (retryCount + 1)));
        return translateWithRetry(text, timestamp, t0, t1, speaker, retryCount + 1);
      }
      
      if (!response.ok) throw new Error(`Translation API error: ${response.status}`);
      
      const data = await response.json();
      return { original: text, translated: data.translated, timestamp, t0, t1, speaker };
    } catch (err) {
      console.error('Translation error:', err);
      return { original: text, translated: '[Translation failed]', timestamp, t0, t1, speaker };
    }
  }, [targetLanguage]);

  // Dịch tất cả
  useEffect(() => {
    const translateAllSegments = async () => {
      if (transcripts.length === 0) {
        setTranslatedSegments([]);
        return;
      }

      const toTranslate = transcripts.filter(
        t => !translatedSegments.find(s => s.timestamp === t.timestamp)
      );

      if (toTranslate.length === 0) {
        setIsTranslating(false);
        return;
      }

      setIsTranslating(true);

      const BATCH_SIZE = 5;
      const newResults: TranslatedSegment[] = [];

      for (let i = 0; i < toTranslate.length; i += BATCH_SIZE) {
        const batch = toTranslate.slice(i, i + BATCH_SIZE);
        const batchResults = await Promise.all(
          batch.map(t => translateWithRetry(t.text, t.timestamp, t.t0, t.t1, t.speaker))
        );
        const validResults = batchResults.filter((r): r is TranslatedSegment => r !== null);
        newResults.push(...validResults);

        if (i + BATCH_SIZE < toTranslate.length) {
          await new Promise(resolve => setTimeout(resolve, 300));
        }
      }

      setTranslatedSegments(prev => {
        const merged = [...prev];
        for (const newSeg of newResults) {
          if (!merged.find(s => s.timestamp === newSeg.timestamp)) {
            merged.push(newSeg);
          }
        }
        return merged.sort((a, b) => a.t0 - b.t0);
      });

      setIsTranslating(false);
    };

    translateAllSegments();
  }, [transcripts, targetLanguage, translateWithRetry]);

  // 🔥 HÀM DIARIZATION MỚI: Ghi đè hoàn toàn bằng bản chuẩn từ WhisperX
  // 🔥 QUAN TRỌNG: Đã sửa seg.speaker thành seg.speaker_id
  const runDiarization = useCallback(async (audioFilePath: string) => {
    if (!enableDiarization) {
      console.log("Diarization disabled, skipping");
      return;
    }
    
    setIsDiarizing(true);
    
    try {
      console.log("🚀 Đang gửi file lên Backend để tinh chỉnh (WhisperX + Diarization):", audioFilePath);
      
      const response = await fetch('http://localhost:5167/diarize-local', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: audioFilePath }),
      });
      
      if (!response.ok) {
        throw new Error(`Diarization failed: ${response.status}`);
      }
      
      const result = await response.json();
      console.log("✅ Kết quả WhisperX nhận được:", result);
      
      if (result.segments && result.segments.length > 0) {
        // 🔥 BIẾN ĐỔI: Chuyển dữ liệu chuẩn từ Backend thành định dạng hiển thị
        // 🔥 SỬA LỖI: Dùng 'speaker_id' thay vì 'speaker'
        const finalTranscripts: TranscriptWithSpeaker[] = result.segments.map((seg: any, index: number) => ({
          id: `final-${index}-${Date.now()}`,
          text: seg.text.trim(),
          timestamp: formatTimeFromSeconds(seg.start),
          t0: seg.start,
          t1: seg.end,
          speaker: seg.speaker_id || "UNKNOWN",  // 🔥 ĐÃ SỬA: speaker_id
          seq: index,
          isVerified: true  // 🔥 Đánh dấu là bản chuẩn
        }));

        // 🔥 GHI ĐÈ HOÀN TOÀN: Xóa bỏ bản nháp, thay bằng bản chuẩn
        setTranscripts(finalTranscripts);
        transcriptsRef.current = finalTranscripts;
        
        // Xóa sạch buffer để tránh bị lẫn dữ liệu cũ
        transcriptBufferRef.current = [];
        if (bufferTimerRef.current) {
          clearTimeout(bufferTimerRef.current);
          bufferTimerRef.current = null;
        }
      }
    } catch (err) {
      const error = err as { name?: string; message?: string };
      console.error("❌ Lỗi xử lý bản chuẩn:", error.message || error);
    } finally {
      setIsDiarizing(false);
    }
  }, [enableDiarization]);

  useEffect(() => {
    setCurrentMeeting({ id: 'intro-call', title: meetingTitle });
  }, [meetingTitle, setCurrentMeeting]);

  useEffect(() => {
    if (isRecording) {
      const interval = setInterval(() => {
        setBarHeights(prev => {
          const newHeights = [...prev];
          newHeights[0] = Math.random() * 20 + 10 + 'px';
          newHeights[1] = Math.random() * 20 + 10 + 'px';
          newHeights[2] = Math.random() * 20 + 10 + 'px';
          return newHeights;
        });
      }, 300);
      return () => clearInterval(interval);
    }
  }, [isRecording]);

  // Listener cho transcript update
  useEffect(() => {
    let unlistenFn: (() => void) | undefined;

    const setupListener = async () => {
      try {
        unlistenFn = await listen<TranscriptUpdate>('transcript-update', (event) => {
          const payload = event.payload;
          const t0 = payload.t0 ?? 0;
          const t1 = payload.t1 ?? 0;
          const seq = payload.seq ?? 0;

          console.log(`📝 [FRONTEND] Received: seq=${seq}, t0=${t0.toFixed(2)}s, text="${payload.text.substring(0, 50)}..."`);
          
          const newTranscript: TranscriptWithSpeaker = {
            id: `${seq}-${Date.now()}`,
            text: payload.text,
            timestamp: payload.timestamp,
            t0: t0,
            t1: t1,
            speaker: undefined,
            seq: seq,
            isVerified: false  // Bản nháp real-time
          };
          
          const existsInBuffer = transcriptBufferRef.current.some(s => s.seq === seq);
          const existsInTranscripts = transcriptsRef.current.some(s => s.seq === seq);

          if (existsInBuffer || existsInTranscripts) {
            console.log(`⏭️ Bỏ qua tin trùng: seq=${seq}`);
            return;
          }

          transcriptBufferRef.current.push(newTranscript);

          if (bufferTimerRef.current) {
            clearTimeout(bufferTimerRef.current);
          }
          bufferTimerRef.current = window.setTimeout(() => {
            flushTranscriptBuffer();
            bufferTimerRef.current = null;
          }, FLUSH_TIMEOUT_MS);
        });
      } catch (err) {
        console.error('Failed to setup transcript listener:', err);
      }
    };
    setupListener();
    return () => { 
      if (unlistenFn) unlistenFn(); 
      if (bufferTimerRef.current) {
        clearTimeout(bufferTimerRef.current);
        bufferTimerRef.current = null;
      }
    };
  }, [flushTranscriptBuffer]);

  useEffect(() => {
    const loadModels = async () => {
      try {
        const response = await fetch('http://localhost:11434/api/tags');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        const modelList = data.models.map((model: any) => ({
          name: model.name,
          id: model.model,
          size: formatSize(model.size),
          modified: model.modified_at
        }));
        setModels(modelList);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load Ollama models');
      }
    };
    loadModels();
  }, []);

  const formatSize = (size: number): string => {
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    return `${(size / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  };

  const handleRecordingStart = async () => {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const isCurrentlyRecording = await invoke('is_recording');
      if (isCurrentlyRecording) await handleRecordingStop();
      await invoke('start_recording', { args: { whisper_model: modelConfig.whisperModel } });
      setIsRecording(true);
      setTranscripts([]);
      setTranslatedSegments([]);
      setDetectedLanguage('auto');
      setLastAudioFile(null);
      transcriptBufferRef.current = [];
      if (bufferTimerRef.current) {
        clearTimeout(bufferTimerRef.current);
        bufferTimerRef.current = null;
      }
    } catch (err) {
      console.error('Failed to start recording:', err);
      alert('Failed to start recording. Check console for details.');
      setIsRecording(false);
    }
  };

  // 🔥 HÀNH LẠI: handleRecordingStop với cơ chế bản nháp → bản chuẩn
  const handleRecordingStop = async () => {
    if (isStoppingRef.current) {
      console.log("Đang xử lý stop, vui lòng đợi...");
      return;
    }
    
    isStoppingRef.current = true;
    
    // 🔥 ĐỔI TRẠNG THÁI NGAY LẬP TỨC
    setIsRecording(false);
    
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const { appDataDir } = await import('@tauri-apps/api/path');
      const dataDir = await appDataDir();
      
      const uniqueId = Date.now();
      const audioPath = `${dataDir}recording-${uniqueId}.wav`;
      
      console.log("🛑 Gửi lệnh stop sang Rust với path:", audioPath);
      
      // 1. Dừng ghi âm và lưu file
      await invoke('stop_recording', { savePath: audioPath });

      // 2. Ép buffer real-time xả nốt những chữ cuối cùng ra màn hình
      if (transcriptBufferRef.current.length > 0) {
        flushTranscriptBuffer();
      }
      
      // Đợi file WAV đóng hoàn toàn
      console.log("⏳ Chờ file WAV đóng (2s)...");
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      setLastAudioFile(audioPath);

      // 3. Nếu bật Diarization, tiến hành chạy bản chuẩn đè lên
      if (enableDiarization) {
        console.log("🚀 Gọi AI nhận diện người nói cho file:", audioPath);
        await runDiarization(audioPath);
      }
      
      // 4. Hiện màn hình tóm tắt
      setShowSummary(true);
      
    } catch (err) {
      console.error('Failed to stop recording:', err);
      alert('Lỗi khi dừng ghi âm. Xem console để biết chi tiết.');
    } finally {
      isStoppingRef.current = false;
    }
  };

  const handleTranscriptUpdate = (update: any) => {
    console.log('Transcript update received:', update);
  };

  const generateAISummary = useCallback(async () => {
    setSummaryStatus('processing');
    setSummaryError(null);
    try {
      const fullTranscript = [...transcripts]
        .sort((a, b) => a.t0 - b.t0)
        .map(t => {
          const speakerName = getSpeakerDisplayName(t.speaker || 'UNKNOWN');
          return `[${speakerName}] ${formatTimeFromSeconds(t.t0)} - ${formatTimeFromSeconds(t.t1)}: ${t.text}`;
        })
        .join('\n');
      
      if (!fullTranscript.trim()) throw new Error('No transcript text available.');
      setOriginalTranscript(fullTranscript);
      
      const response = await fetch('http://localhost:5167/process-transcript', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: fullTranscript,
          model: modelConfig.provider,
          model_name: modelConfig.model,
          chunk_size: 40000,
          overlap: 1000
        })
      });
      if (!response.ok) throw new Error('Failed to process transcript');
      const { process_id } = await response.json();
      const pollInterval = setInterval(async () => {
        try {
          const statusResponse = await fetch(`http://localhost:5167/get-summary/${process_id}`);
          if (!statusResponse.ok) throw new Error('Failed to get summary');
          const result = await statusResponse.json();
          if (result.status === 'error') {
            setSummaryError(result.error);
            setSummaryStatus('error');
            clearInterval(pollInterval);
          } else if (result.status === 'completed' && result.data) {
            clearInterval(pollInterval);
            const { MeetingName, ...summaryData } = result.data;
            if (MeetingName) setMeetingTitle(MeetingName);
            const formattedSummary = Object.entries(summaryData).reduce((acc: Summary, [key, section]: [string, any]) => {
              acc[key] = {
                title: section.title,
                blocks: section.blocks.map((block: any) => ({
                  ...block,
                  type: 'bullet',
                  color: 'default',
                  content: block.content.trim()
                }))
              };
              return acc;
            }, {} as Summary);
            setAiSummary(formattedSummary);
            setSummaryStatus('completed');
          }
        } catch (err) {
          clearInterval(pollInterval);
          setSummaryStatus('error');
        }
      }, 5000);
      return () => clearInterval(pollInterval);
    } catch (err) {
      setSummaryStatus('error');
    }
  }, [transcripts, modelConfig, getSpeakerDisplayName]);

  const handleTitleChange = (newTitle: string) => {
    setMeetingTitle(newTitle);
    setCurrentMeeting({ id: 'intro-call', title: newTitle });
  };

  const getSummaryStatusMessage = (status: SummaryStatus) => {
    switch (status) {
      case 'idle': return 'Ready to generate summary';
      case 'processing': return 'Processing transcript...';
      case 'summarizing': return 'Generating AI summary...';
      case 'regenerating': return 'Regenerating AI summary...';
      case 'completed': return 'Summary generated successfully!';
      case 'error': return summaryError || 'An error occurred';
      default: return '';
    }
  };

  const handleCopyTranscript = useCallback(() => {
    const fullTranscript = [...transcripts]
      .sort((a, b) => a.t0 - b.t0)
      .map(t => {
        const speakerName = getSpeakerDisplayName(t.speaker || 'UNKNOWN');
        return `[${speakerName}] ${formatTimeFromSeconds(t.t0)}: ${t.text}`;
      })
      .join('\n');
    navigator.clipboard.writeText(fullTranscript);
  }, [transcripts, getSpeakerDisplayName]);

  const handleGenerateSummary = useCallback(async () => {
    if (!transcripts.length) return;
    await generateAISummary();
  }, [transcripts, generateAISummary]);

  const handleRegenerateSummary = useCallback(async () => {
    if (!originalTranscript.trim()) return;
    setSummaryStatus('regenerating');
    setSummaryError(null);
    try {
      const response = await fetch('http://localhost:5167/process-transcript', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: originalTranscript,
          model: modelConfig.provider,
          model_name: modelConfig.model,
          chunk_size: 40000,
          overlap: 1000
        })
      });
      if (!response.ok) throw new Error('Failed to process transcript');
      const { process_id } = await response.json();
      const pollInterval = setInterval(async () => {
        try {
          const statusResponse = await fetch(`http://localhost:5167/get-summary/${process_id}`);
          if (!statusResponse.ok) throw new Error('Failed to get summary');
          const result = await statusResponse.json();
          if (result.status === 'error') {
            setSummaryError(result.error);
            setSummaryStatus('error');
            clearInterval(pollInterval);
          } else if (result.status === 'completed' && result.data) {
            clearInterval(pollInterval);
            const { MeetingName, ...summaryData } = result.data;
            if (MeetingName) setMeetingTitle(MeetingName);
            const formattedSummary = Object.entries(summaryData).reduce((acc: Summary, [key, section]: [string, any]) => {
              acc[key] = {
                title: section.title,
                blocks: section.blocks.map((block: any) => ({
                  ...block,
                  type: 'bullet',
                  color: 'default',
                  content: block.content.trim()
                }))
              };
              return acc;
            }, {} as Summary);
            setAiSummary(formattedSummary);
            setSummaryStatus('completed');
          }
        } catch (err) {
          clearInterval(pollInterval);
          setSummaryStatus('error');
        }
      }, 10000);
      return () => clearInterval(pollInterval);
    } catch (err) {
      setSummaryStatus('error');
    }
  }, [originalTranscript, modelConfig]);

  const isSummaryLoading = summaryStatus === 'processing' || summaryStatus === 'summarizing' || summaryStatus === 'regenerating';

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      <div className="flex flex-1 overflow-hidden">
        {/* Left side - Transcript */}
        <div className="w-1/3 min-w-[300px] border-r border-gray-200 bg-white flex flex-col relative">
          {/* Title area */}
          <div className="p-4 border-b border-gray-200">
            <div className="flex flex-col space-y-3">
              <div className="flex items-center">
                <EditableTitle
                  title={meetingTitle}
                  isEditing={isEditingTitle}
                  onStartEditing={() => setIsEditingTitle(true)}
                  onFinishEditing={() => setIsEditingTitle(false)}
                  onChange={handleTitleChange}
                />
              </div>

              {/* Buttons row */}
              <div className="flex items-center space-x-2">
                <button
                  onClick={handleCopyTranscript}
                  disabled={transcripts.length === 0}
                  className={`px-3 py-2 border rounded-md transition-all duration-200 inline-flex items-center gap-2 shadow-sm ${
                    transcripts.length === 0
                      ? 'bg-gray-50 border-gray-200 text-gray-400 cursor-not-allowed'
                      : 'bg-blue-50 border-blue-200 text-blue-700 hover:bg-blue-100'
                  }`}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 24 24" strokeWidth="2" stroke="currentColor" fill="none">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V7.5l-3.75-3.612z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 3v3.75a.75.75 0 0 0 .75.75H18" />
                  </svg>
                  <span className="text-sm">Copy</span>
                </button>
                {showSummary && !isRecording && (
                  <>
                    <button
                      onClick={handleGenerateSummary}
                      disabled={summaryStatus === 'processing'}
                      className={`px-3 py-2 border rounded-md transition-all duration-200 inline-flex items-center gap-2 shadow-sm ${
                        summaryStatus === 'processing'
                          ? 'bg-yellow-50 border-yellow-200 text-yellow-700'
                          : transcripts.length === 0
                          ? 'bg-gray-50 border-gray-200 text-gray-400 cursor-not-allowed'
                          : 'bg-green-50 border-green-200 text-green-700 hover:bg-green-100'
                      }`}
                    >
                      {summaryStatus === 'processing' ? (
                        <>
                          <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                          </svg>
                          <span className="text-sm">Processing...</span>
                        </>
                      ) : (
                        <>
                          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                          </svg>
                          <span className="text-sm">Generate Note</span>
                        </>
                      )}
                    </button>
                    <button
                      onClick={() => setShowModelSettings(true)}
                      className="px-3 py-2 border rounded-md transition-all duration-200 inline-flex items-center gap-2 shadow-sm bg-gray-50 border-gray-200 text-gray-700 hover:bg-gray-100"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      </svg>
                    </button>
                  </>
                )}
              </div>

              {/* Translation selector */}
              <div className="flex items-center gap-2 p-2 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-200">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-blue-600 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
                </svg>
                <span className="text-xs font-medium text-blue-700 whitespace-nowrap">Dịch sang:</span>
                <select
                  value={targetLanguage}
                  onChange={(e) => setTargetLanguage(e.target.value)}
                  className="flex-1 px-2 py-1 text-sm border border-blue-300 rounded-md bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  {SUPPORTED_LANGUAGES.map(lang => (
                    <option key={lang.code} value={lang.code}>
                      {lang.name}
                    </option>
                  ))}
                </select>
                {isTranslating && (
                  <div className="flex items-center gap-1">
                    <svg className="animate-spin h-3 w-3 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                  </div>
                )}
              </div>

              {/* Diarization toggle */}
              <div className="flex items-center gap-2 mt-1">
                <input
                  type="checkbox"
                  id="enableDiarization"
                  checked={enableDiarization}
                  onChange={(e) => setEnableDiarization(e.target.checked)}
                  className="w-3.5 h-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <label htmlFor="enableDiarization" className="text-xs text-gray-600">
                  Phân biệt người nói (chậm hơn)
                </label>
                {isDiarizing && (
                  <div className="flex items-center gap-1 ml-2">
                    <svg className="animate-spin h-3 w-3 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span className="text-xs text-blue-500">Đang phân tích...</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Transcript content */}
          <div className="flex-1 overflow-y-auto pb-32">
            {transcripts.length > 0 ? (
              <div className="p-3 space-y-3">
                {[...transcripts].sort((a, b) => a.t0 - b.t0).map((item) => {
                  const translatedItem = translatedSegments.find(s => s.timestamp === item.timestamp);
                  const displayName = getSpeakerDisplayName(item.speaker || 'UNKNOWN');
                  const speakerColor = getSpeakerColor(item.speaker || '');
                  
                  return (
                    <div key={item.id} className="relative">
                      <div className="flex items-start gap-2">
                        <span className="text-[10px] font-mono text-gray-400 whitespace-nowrap mt-0.5">
                          {formatTimeFromSeconds(item.t0)}
                        </span>
                        <div className="flex-1">
                          <div className="group w-full">
                            <div className="flex items-center gap-2 mb-0.5">
                              <button 
                                onClick={() => {
                                  const sId = item.speaker || 'UNKNOWN';
                                  setEditingSpeakerId(sId);
                                  const existing = speakerMaps.find(s => s.speaker_id === sId);
                                  setSpeakerForm({
                                    name: existing ? existing.name : '',
                                    email: existing ? existing.email : ''
                                  });
                                  setShowSpeakerModal(true);
                                }}
                                className={`text-[10px] font-semibold px-2 py-0.5 rounded-full cursor-pointer hover:opacity-80 transition-all border border-transparent hover:border-current ${speakerColor} ${!item.speaker ? 'bg-gray-100 text-gray-400' : ''}`}
                                title="Nhấn để định danh người này"
                              >
                                {displayName}
                              </button>
                              {/* 🔥 BADGE VERIFIED: Hiển thị nếu là bản chuẩn từ WhisperX */}
                              {item.isVerified && (
                                <span title="Đã tinh chỉnh bởi WhisperX" className="text-blue-500">
                                  <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
                                    <path fillRule="evenodd" d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.64.304 1.24.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                                  </svg>
                                </span>
                              )}
                            </div>
                            <p className="text-sm text-gray-700 leading-relaxed p-1 -m-1 rounded cursor-pointer transition-all duration-150 group-hover:bg-gray-100">
                              {item.text}
                            </p>
                            {translatedItem && translatedItem.translated && translatedItem.translated !== '[Translation failed]' && (
                              <div className="overflow-hidden transition-all duration-200 max-h-0 group-hover:max-h-24 group-hover:mt-2">
                                <div className="pt-1">
                                  <p className="text-sm text-blue-600 leading-relaxed border-l-2 border-blue-300 pl-2">
                                    {translatedItem.translated}
                                  </p>
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="p-4 text-center text-gray-400 text-sm">
                Chưa có transcript. Nhấn Record để bắt đầu ghi âm.
              </div>
            )}
          </div>

          {/* Recording controls */}
          <div className="absolute bottom-16 left-1/2 transform -translate-x-1/2 z-10">
            <div className="bg-white rounded-full shadow-lg flex items-center">
              <RecordingControls
                isRecording={isRecording}
                onRecordingStop={handleRecordingStop}
                onRecordingStart={handleRecordingStart}
                onTranscriptReceived={handleTranscriptUpdate}
                barHeights={barHeights}
              />
            </div>
          </div>

          {/* Model Settings Modal */}
          {showModelSettings && (
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
              <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-lg font-semibold text-gray-900">Model Settings</h3>
                  <button onClick={() => setShowModelSettings(false)} className="text-gray-500 hover:text-gray-700">
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Summarization Model</label>
                    <div className="flex space-x-2">
                      <select
                        className="px-3 py-2 text-sm bg-white border border-gray-300 rounded-md"
                        value={modelConfig.provider}
                        onChange={(e) => {
                          const provider = e.target.value as ModelConfig['provider'];
                          setModelConfig({ ...modelConfig, provider, model: modelOptions[provider][0] });
                        }}
                      >
                        <option value="claude">Claude</option>
                        <option value="groq">Groq</option>
                        <option value="ollama">Ollama</option>
                      </select>
                      <select
                        className="flex-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md"
                        value={modelConfig.model}
                        onChange={(e) => setModelConfig(prev => ({ ...prev, model: e.target.value }))}
                      >
                        {modelOptions[modelConfig.provider].map(model => (
                          <option key={model} value={model}>{model}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  {modelConfig.provider === 'ollama' && (
                    <div>
                      <h4 className="text-lg font-bold mb-4">Available Ollama Models</h4>
                      {error && <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">{error}</div>}
                      <div className="grid gap-4 max-h-[400px] overflow-y-auto pr-2">
                        {models.map((model) => (
                          <div 
                            key={model.id}
                            className={`bg-white p-4 rounded-lg shadow cursor-pointer transition-colors ${modelConfig.model === model.name ? 'ring-2 ring-blue-500 bg-blue-50' : 'hover:bg-gray-50'}`}
                            onClick={() => setModelConfig(prev => ({ ...prev, model: model.name }))}
                          >
                            <h3 className="font-bold">{model.name}</h3>
                            <p className="text-gray-600">Size: {model.size}</p>
                            <p className="text-gray-600">Modified: {model.modified}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                <div className="mt-6 flex justify-end">
                  <button onClick={() => setShowModelSettings(false)} className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700">Done</button>
                </div>
              </div>
            </div>
          )}

          {/* ==================== MODAL ĐỔI TÊN SPEAKER ==================== */}
          {showSpeakerModal && (
            <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-[60] backdrop-blur-sm">
              <div className="bg-white rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl transform transition-all">
                <div className="flex justify-between items-center mb-5">
                  <h3 className="text-lg font-bold text-gray-900">
                    Định danh {editingSpeakerId}
                  </h3>
                  <button onClick={() => setShowSpeakerModal(false)} className="text-gray-400 hover:text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-full p-1 transition-colors">
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                    </svg>
                  </button>
                </div>
                
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-semibold text-gray-700 mb-1">Tên hiển thị</label>
                    <input
                      type="text"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all"
                      placeholder="VD: Nguyễn Văn A"
                      value={speakerForm.name}
                      onChange={(e) => setSpeakerForm({...speakerForm, name: e.target.value})}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && speakerForm.name.trim()) {
                          handleSaveSpeaker();
                        }
                      }}
                      autoFocus
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-semibold text-gray-700 mb-1">Email (Tùy chọn cho AI gửi thư)</label>
                    <input
                      type="email"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all"
                      placeholder="VD: a@gmail.com"
                      value={speakerForm.email}
                      onChange={(e) => setSpeakerForm({...speakerForm, email: e.target.value})}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && speakerForm.name.trim()) {
                          handleSaveSpeaker();
                        }
                      }}
                    />
                  </div>
                </div>

                <div className="mt-6 flex justify-end gap-3">
                  <button 
                    onClick={() => setShowSpeakerModal(false)} 
                    className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
                  >
                    Hủy
                  </button>
                  <button 
                    onClick={handleSaveSpeaker} 
                    disabled={!speakerForm.name.trim()}
                    className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:bg-blue-300 disabled:cursor-not-allowed transition-colors shadow-sm"
                  >
                    Lưu danh bạ
                  </button>
                </div>
              </div>
            </div>
          )}
          {/* ========================================================== */}
        </div>

        {/* Right side - AI Summary */}
        <div className="flex-1 overflow-y-auto bg-white">
          {isSummaryLoading ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <div className="inline-block animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500 mb-4"></div>
                <p className="text-gray-600">Generating AI Summary...</p>
              </div>
            </div>
          ) : showSummary && (
            <div className="max-w-4xl mx-auto p-6">
              <div className="flex-1 overflow-y-auto p-4">
                <AISummary 
                  summary={aiSummary} 
                  status={summaryStatus} 
                  error={summaryError}
                  onSummaryChange={(newSummary) => setAiSummary(newSummary)}
                  onRegenerateSummary={handleRegenerateSummary}
                />
              </div>
              {summaryStatus !== 'idle' && (
                <div className={`mt-4 p-4 rounded-lg ${
                  summaryStatus === 'error' ? 'bg-red-100 text-red-700' :
                  summaryStatus === 'completed' ? 'bg-green-100 text-green-700' :
                  'bg-blue-100 text-blue-700'
                }`}>
                  <p className="text-sm font-medium">{getSummaryStatusMessage(summaryStatus)}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}