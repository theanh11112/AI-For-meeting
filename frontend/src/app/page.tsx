// app/page.tsx
'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { 
  TranscriptWithSpeaker, 
  EnhancedSummary,
  ModelConfig, 
  SummaryStatus,
  TranslatedSegment,
  SpeakerMap 
} from '@/types';
import { EditableTitle } from '@/components/EditableTitle';
import { RecordingControls } from '@/components/RecordingControls';
import { AISummary } from '@/components/AISummary';
import { useSidebar } from '@/components/Sidebar/SidebarProvider';
import { listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';
import { TranscriptList } from '@/components/Meeting/Transcript/TranscriptList';
import { Toolbar } from '@/components/Meeting/Controls/Toolbar';
import { LanguageSelector } from '@/components/Meeting/Controls/LanguageSelector';
import { SpeakerModal } from '@/components/Meeting/Modals/SpeakerModal';
import { ModelSettingsModal } from '@/components/Meeting/Modals/ModelSettingsModal';
import { formatTimeFromSeconds } from '@/utils/transcriptUtils';

interface TranscriptUpdate {
  text: string;
  timestamp: string;
  source: string;
  t0?: number;
  t1?: number;
  seq?: number;
}

interface OllamaModel {
  name: string;
  id: string;
  size: string;
  modified: string;
}

export default function Home() {
  // States
  const [isRecording, setIsRecording] = useState(false);
  const [transcripts, setTranscripts] = useState<TranscriptWithSpeaker[]>([]);
  
  const transcriptBufferRef = useRef<TranscriptWithSpeaker[]>([]);
  const bufferTimerRef = useRef<number | null>(null);
  const transcriptsRef = useRef<TranscriptWithSpeaker[]>([]);
  const FLUSH_TIMEOUT_MS = 1000;
  
  const [showSummary, setShowSummary] = useState(false);
  const [summaryStatus, setSummaryStatus] = useState<SummaryStatus>('idle');
  const [barHeights, setBarHeights] = useState(['58%', '76%', '58%']);
  const [meetingTitle, setMeetingTitle] = useState('New Call');
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  
  const [aiSummary, setAiSummary] = useState<EnhancedSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  
  const [modelConfig, setModelConfig] = useState<ModelConfig>({
    provider: 'groq',
    model: 'llama-3.3-70b-versatile',
    whisperModel: 'large-v3'
  });
  const [originalTranscript, setOriginalTranscript] = useState<string>('');
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [error, setError] = useState<string>('');

  const [targetLanguage, setTargetLanguage] = useState('en');
  const [translatedSegments, setTranslatedSegments] = useState<TranslatedSegment[]>([]);
  const [isTranslating, setIsTranslating] = useState(false);

  const [lastAudioFile, setLastAudioFile] = useState<string | null>(null);
  const [isDiarizing, setIsDiarizing] = useState(false);
  const [enableDiarization, setEnableDiarization] = useState(true);

  const [speakerMaps, setSpeakerMaps] = useState<SpeakerMap[]>([]);
  const [showSpeakerModal, setShowSpeakerModal] = useState(false);
  const [editingSpeakerId, setEditingSpeakerId] = useState<string>('');
  const [speakerForm, setSpeakerForm] = useState({ name: '', email: '' });
  const [showModelSettings, setShowModelSettings] = useState(false);

  const isStoppingRef = useRef(false);
  const { setCurrentMeeting } = useSidebar();

  // Helper functions
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

        if (segFirstChar && segFirstChar === segFirstChar.toLowerCase() && !lastEndsWithPunct) {
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

  // Speaker Mapping
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

  // Translation
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

  // Diarization
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
        const finalTranscripts: TranscriptWithSpeaker[] = result.segments.map((seg: any, index: number) => ({
          id: `final-${index}-${Date.now()}`,
          text: seg.text.trim(),
          timestamp: formatTimeFromSeconds(seg.start),
          t0: seg.start,
          t1: seg.end,
          speaker: seg.speaker_id || "UNKNOWN",
          seq: index,
          isVerified: true
        }));

        setTranscripts(finalTranscripts);
        transcriptsRef.current = finalTranscripts;
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

  // Recording handlers
  const handleRecordingStart = async () => {
    try {
      const isCurrentlyRecording = await invoke('is_recording');
      if (isCurrentlyRecording) await handleRecordingStop();
      await invoke('start_recording', { args: { whisper_model: modelConfig.whisperModel } });
      setIsRecording(true);
      setTranscripts([]);
      setTranslatedSegments([]);
      setLastAudioFile(null);
      setAiSummary(null);
      setShowSummary(false);
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

  const handleRecordingStop = async () => {
    if (isStoppingRef.current) {
      console.log("Đang xử lý stop, vui lòng đợi...");
      return;
    }
    
    isStoppingRef.current = true;
    setIsRecording(false);
    
    try {
      const { appDataDir } = await import('@tauri-apps/api/path');
      const dataDir = await appDataDir();
      const uniqueId = Date.now();
      const audioPath = `${dataDir}recording-${uniqueId}.wav`;
      
      console.log("🛑 Gửi lệnh stop sang Rust với path:", audioPath);
      await invoke('stop_recording', { savePath: audioPath });

      if (transcriptBufferRef.current.length > 0) {
        flushTranscriptBuffer();
      }
      
      console.log("⏳ Chờ file WAV đóng (2s)...");
      await new Promise(resolve => setTimeout(resolve, 2000));
      setLastAudioFile(audioPath);

      if (enableDiarization) {
        console.log("🚀 Gọi AI nhận diện người nói cho file:", audioPath);
        await runDiarization(audioPath);
      }
      
      setShowSummary(true);
    } catch (err) {
      console.error('Failed to stop recording:', err);
      alert('Lỗi khi dừng ghi âm. Xem console để biết chi tiết.');
    } finally {
      isStoppingRef.current = false;
    }
  };

  // AI Summary
  const generateAISummary = useCallback(async () => {
    if (!transcripts.length) {
      console.warn("No transcripts to summarize");
      return;
    }
    
    setSummaryStatus('processing');
    setSummaryError(null);
    setAiSummary(null);
    
    try {
      const fullTranscript = [...transcripts]
        .sort((a, b) => a.t0 - b.t0)
        .map(t => {
          const speakerName = getSpeakerDisplayName(t.speaker || 'UNKNOWN');
          return `[${speakerName}] ${formatTimeFromSeconds(t.t0)} - ${formatTimeFromSeconds(t.t1)}: ${t.text}`;
        })
        .join('\n');
      
      if (!fullTranscript.trim()) {
        throw new Error('No transcript text available.');
      }
      
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
      
      if (!response.ok) {
        throw new Error('Failed to process transcript');
      }
      
      const { process_id } = await response.json();
      console.log(`📋 Process ID: ${process_id}, polling for results...`);
      
      const pollInterval = setInterval(async () => {
        try {
          const statusResponse = await fetch(`http://localhost:5167/get-summary/${process_id}`);
          if (!statusResponse.ok) {
            throw new Error('Failed to get summary status');
          }
          
          const result = await statusResponse.json();
          
          if (result.status === 'error') {
            clearInterval(pollInterval);
            setSummaryError(result.error || 'Unknown error');
            setSummaryStatus('error');
          } else if (result.status === 'completed') {
            clearInterval(pollInterval);
            
            try {
              const enhancedRes = await fetch(`http://localhost:5167/get-action-items/${process_id}`);
              if (enhancedRes.ok) {
                const enhancedData = await enhancedRes.json();
                console.log('✅ Enhanced summary data received:', enhancedData);
                
                if (enhancedData.meeting_name) {
                  setMeetingTitle(enhancedData.meeting_name);
                }
                
                setAiSummary(enhancedData);
                setSummaryStatus('completed');
              } else {
                const { MeetingName } = result.data;
                if (MeetingName) setMeetingTitle(MeetingName);
                setAiSummary({
                  meeting_name: MeetingName || 'Cuộc họp',
                  meeting_date: new Date().toISOString().split('T')[0],
                  general_summary: '',
                  key_decisions: [],
                  action_items: [],
                  pending_questions: [],
                  key_topics_discussed: []
                });
                setSummaryStatus('completed');
              }
            } catch (enhancedErr) {
              console.error('Error fetching enhanced summary:', enhancedErr);
              const { MeetingName } = result.data;
              if (MeetingName) setMeetingTitle(MeetingName);
              setAiSummary({
                meeting_name: MeetingName || 'Cuộc họp',
                meeting_date: new Date().toISOString().split('T')[0],
                general_summary: '',
                key_decisions: [],
                action_items: [],
                pending_questions: [],
                key_topics_discussed: []
              });
              setSummaryStatus('completed');
            }
          }
        } catch (err) {
          console.error('Polling error:', err);
        }
      }, 3000);
      
      return () => clearInterval(pollInterval);
      
    } catch (err) {
      console.error('Error generating summary:', err);
      setSummaryError(err instanceof Error ? err.message : 'Failed to generate summary');
      setSummaryStatus('error');
    }
  }, [transcripts, modelConfig, getSpeakerDisplayName]);

  const handleRegenerateSummary = useCallback(async () => {
    if (!originalTranscript.trim()) {
      console.warn("No original transcript to regenerate");
      return;
    }
    setSummaryStatus('regenerating');
    setSummaryError(null);
    setAiSummary(null);
    
    try {
      const response = await fetch('http://localhost:5167/process-transcript', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: originalTranscript,
          model: modelConfig.provider,
          model_name: modelConfig.model,
          chunk_size: 40000,
          overlap: 1000,
          force_regenerate: true
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
            
            try {
              const enhancedRes = await fetch(`http://localhost:5167/get-action-items/${process_id}`);
              if (enhancedRes.ok) {
                const enhancedData = await enhancedRes.json();
                if (enhancedData.meeting_name) setMeetingTitle(enhancedData.meeting_name);
                setAiSummary(enhancedData);
                setSummaryStatus('completed');
              } else {
                const { MeetingName } = result.data;
                if (MeetingName) setMeetingTitle(MeetingName);
                setAiSummary({
                  meeting_name: MeetingName || 'Cuộc họp',
                  meeting_date: new Date().toISOString().split('T')[0],
                  general_summary: '',
                  key_decisions: [],
                  action_items: [],
                  pending_questions: [],
                  key_topics_discussed: []
                });
                setSummaryStatus('completed');
              }
            } catch {
              const { MeetingName } = result.data;
              if (MeetingName) setMeetingTitle(MeetingName);
              setAiSummary({
                meeting_name: MeetingName || 'Cuộc họp',
                meeting_date: new Date().toISOString().split('T')[0],
                general_summary: '',
                key_decisions: [],
                action_items: [],
                pending_questions: [],
                key_topics_discussed: []
              });
              setSummaryStatus('completed');
            }
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
  }, [originalTranscript, modelConfig]);

  // Other handlers
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

  const handleTitleChange = (newTitle: string) => {
    setMeetingTitle(newTitle);
    setCurrentMeeting({ id: 'intro-call', title: newTitle });
  };

  const handleSpeakerClick = useCallback((speakerId: string) => {
    setEditingSpeakerId(speakerId);
    const existing = speakerMaps.find(s => s.speaker_id === speakerId);
    setSpeakerForm({
      name: existing ? existing.name : '',
      email: existing ? existing.email : ''
    });
    setShowSpeakerModal(true);
  }, [speakerMaps]);

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

  // Effects
  useEffect(() => {
    transcriptsRef.current = transcripts;
  }, [transcripts]);

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

  useEffect(() => {
    let unlistenFn: (() => void) | undefined;

    const setupListener = async () => {
      try {
        unlistenFn = await listen<TranscriptUpdate>('transcript-update', (event) => {
          const payload = event.payload;
          const t0 = payload.t0 ?? 0;
          const t1 = payload.t1 ?? 0;
          const seq = payload.seq ?? 0;

          console.log(`📝 [FRONTEND] Received: seq=${seq}, t0=${t0.toFixed(2)}s`);
          
          const newTranscript: TranscriptWithSpeaker = {
            id: `${seq}-${Date.now()}`,
            text: payload.text,
            timestamp: payload.timestamp,
            t0: t0,
            t1: t1,
            speaker: undefined,
            seq: seq,
            isVerified: false
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
        const formatSize = (size: number): string => {
          if (size < 1024) return `${size} B`;
          if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
          if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
          return `${(size / (1024 * 1024 * 1024)).toFixed(1)} GB`;
        };
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

  const isSummaryLoading = summaryStatus === 'processing' || summaryStatus === 'summarizing' || summaryStatus === 'regenerating';

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      <div className="flex flex-1 overflow-hidden">
        {/* Left side - Transcript */}
        <div className="w-1/3 min-w-[300px] border-r border-gray-200 bg-white flex flex-col relative">
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

              <Toolbar
                onCopy={handleCopyTranscript}
                onGenerate={handleGenerateSummary}
                onOpenSettings={() => setShowModelSettings(true)}
                isGenerating={summaryStatus === 'processing'}
                hasTranscripts={transcripts.length > 0}
                showSummary={showSummary}
                isRecording={isRecording}
              />

              <LanguageSelector
                value={targetLanguage}
                onChange={setTargetLanguage}
                isTranslating={isTranslating}
              />

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

          <TranscriptList
            transcripts={transcripts}
            translatedSegments={translatedSegments}
            getSpeakerDisplayName={getSpeakerDisplayName}
            onSpeakerClick={handleSpeakerClick}
          />

          <div className="absolute bottom-16 left-1/2 transform -translate-x-1/2 z-10">
            <div className="bg-white rounded-full shadow-lg flex items-center">
              <RecordingControls
                isRecording={isRecording}
                onRecordingStop={handleRecordingStop}
                onRecordingStart={handleRecordingStart}
                onTranscriptReceived={() => {}}
                barHeights={barHeights}
              />
            </div>
          </div>

          <ModelSettingsModal
            isOpen={showModelSettings}
            onClose={() => setShowModelSettings(false)}
            config={modelConfig}
            onConfigChange={setModelConfig}
            models={models}
            error={error}
          />

          <SpeakerModal
            isOpen={showSpeakerModal}
            onClose={() => setShowSpeakerModal(false)}
            speakerId={editingSpeakerId}
            name={speakerForm.name}
            email={speakerForm.email}
            onNameChange={(name) => setSpeakerForm(prev => ({ ...prev, name }))}
            onEmailChange={(email) => setSpeakerForm(prev => ({ ...prev, email }))}
            onSave={handleSaveSpeaker}
          />
        </div>

        {/* Right side - AI Summary */}
        <div className="flex-1 overflow-y-auto bg-white">
          {isSummaryLoading ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <div className="inline-block animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-indigo-500 mb-4"></div>
                <p className="text-gray-600">AI đang phân tích nội dung cuộc họp...</p>
                <p className="text-gray-400 text-xs mt-1">Quá trình này có thể mất vài giây</p>
              </div>
            </div>
          ) : showSummary && (
            <div className="max-w-4xl mx-auto p-6">
              <div className="flex-1 overflow-y-auto">
                <AISummary 
                  summary={aiSummary} 
                  status={summaryStatus} 
                  error={summaryError}
                  onSummaryChange={(newSummary) => setAiSummary(newSummary)}
                  onRegenerateSummary={handleRegenerateSummary}
                />
              </div>
              {/* 🔥 ĐÃ SỬA: Bỏ điều kiện `!== 'processing'` vì đã ở trong `!isSummaryLoading` */}
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