'use client';

import { useState, useEffect, useContext, useCallback, useRef } from 'react';
import { Transcript, Summary, SummaryResponse } from '@/types';
import { EditableTitle } from '@/components/EditableTitle';
import { TranscriptView } from '@/components/TranscriptView';
import { RecordingControls } from '@/components/RecordingControls';
import { AISummary } from '@/components/AISummary';
import { useSidebar } from '@/components/Sidebar/SidebarProvider';
import { listen } from '@tauri-apps/api/event';
import { writeTextFile } from '@tauri-apps/plugin-fs';
import { downloadDir } from '@tauri-apps/api/path';
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

export default function Home() {
  const [isRecording, setIsRecording] = useState(false);
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
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
  const [summaryResponse, setSummaryResponse] = useState<SummaryResponse | null>(null);
  const [isCollapsed, setIsCollapsed] = useState(false);
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
  const [translatedSegments, setTranslatedSegments] = useState<{ timestamp: string; original: string; translated: string }[]>([]);
  const [isTranslating, setIsTranslating] = useState(false);
  const [detectedLanguage, setDetectedLanguage] = useState<string>('auto');

  // State cho thời gian tương đối
  const [startRecordingTime, setStartRecordingTime] = useState<Date | null>(null);

  const modelOptions = {
    ollama: models.map(model => model.name),
    claude: ['claude-3-5-sonnet-latest'],
    groq: ['llama-3.3-70b-versatile'],
  };

  useEffect(() => {
    if (models.length > 0 && modelConfig.provider === 'ollama') {
      setModelConfig(prev => ({
        ...prev,
        model: models[0].name
      }));
    }
  }, [models]);

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

  // Format thời gian tương đối từ lúc bắt đầu ghi
  const formatRelativeTime = useCallback((timestamp: string) => {
    if (!startRecordingTime) return '0:00';
    
    try {
      const absoluteTime = new Date(timestamp);
      const diffMs = absoluteTime.getTime() - startRecordingTime.getTime();
      
      // Nếu timestamp trước thời gian bắt đầu (do lỗi), trả về 0:00
      if (diffMs < 0) return '0:00';
      
      const totalSeconds = Math.floor(diffMs / 1000);
      const minutes = Math.floor(totalSeconds / 60);
      const seconds = totalSeconds % 60;
      
      return `${minutes}:${seconds.toString().padStart(2, '0')}`;
    } catch {
      return '0:00';
    }
  }, [startRecordingTime]);

  // Hàm dịch một đoạn text
  const translateSegment = useCallback(async (text: string, timestamp: string) => {
    if (!text || text.trim() === '') return null;
    
    try {
      const response = await fetch('http://localhost:5167/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text,
          target_lang: targetLanguage,
          source_lang: 'auto'
        })
      });
      
      if (!response.ok) throw new Error(`Translation API error: ${response.status}`);
      
      const data = await response.json();
      return { original: text, translated: data.translated, timestamp };
    } catch (error) {
      console.error('Translation error:', error);
      return { original: text, translated: '[Translation failed]', timestamp };
    }
  }, [targetLanguage]);

  // Dịch tất cả các đoạn transcript mới
  useEffect(() => {
    const translateAllSegments = async () => {
      if (transcripts.length === 0) {
        setTranslatedSegments([]);
        return;
      }
      
      setIsTranslating(true);
      const results = await Promise.all(
        transcripts.map(async (t) => {
          const existing = translatedSegments.find(s => s.timestamp === t.timestamp);
          if (existing) return existing;
          return await translateSegment(t.text, t.timestamp);
        })
      );
      setTranslatedSegments(results.filter(r => r !== null) as any);
      setIsTranslating(false);
    };
    
    translateAllSegments();
  }, [transcripts, targetLanguage, translateSegment]);

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
    let transcriptCounter = 0;

    const setupListener = async () => {
      try {
        unlistenFn = await listen<TranscriptUpdate>('transcript-update', (event) => {
          const newTranscript = {
            id: `${Date.now()}-${transcriptCounter++}`,
            text: event.payload.text,
            timestamp: event.payload.timestamp,
          };
          setTranscripts(prev => {
            const exists = prev.some(
              t => t.text === event.payload.text && t.timestamp === event.payload.timestamp
            );
            return exists ? prev : [...prev, newTranscript];
          });
        });
      } catch (error) {
        console.error('Failed to setup transcript listener:', error);
      }
    };
    setupListener();
    return () => { if (unlistenFn) unlistenFn(); };
  }, []);

  useEffect(() => {
    const loadModels = async () => {
      try {
        const response = await fetch('http://localhost:11434/api/tags', {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' },
        });
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
      // Lưu thời điểm bắt đầu ghi
      setStartRecordingTime(new Date());
      
      const { invoke } = await import('@tauri-apps/api/core');
      const isCurrentlyRecording = await invoke('is_recording');
      if (isCurrentlyRecording) await handleRecordingStop();
      await invoke('start_recording', { args: { whisper_model: modelConfig.whisperModel } });
      setIsRecording(true);
      setTranscripts([]);
      setTranslatedSegments([]);
      setDetectedLanguage('auto');
    } catch (error) {
      console.error('Failed to start recording:', error);
      alert('Failed to start recording. Check console for details.');
      setIsRecording(false);
      setStartRecordingTime(null);
    }
  };

  const handleRecordingStop = async () => {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const { appDataDir } = await import('@tauri-apps/api/path');
      const dataDir = await appDataDir();
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      const transcriptPath = `${dataDir}transcript-${timestamp}.txt`;
      const audioPath = `${dataDir}recording-${timestamp}.wav`;
      await invoke('stop_recording', { args: { save_path: audioPath, model_config: modelConfig } });
      
      const formattedTranscript = transcripts
        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
        .map(t => `[${formatRelativeTime(t.timestamp)}] ${t.text}`)
        .join('\n\n');
      const documentContent = `Meeting Title: ${meetingTitle}\nDate: ${new Date().toLocaleString()}\n\nTranscript:\n${formattedTranscript}`;
      await invoke('save_transcript', { filePath: transcriptPath, content: documentContent });
      setIsRecording(false);
      setStartRecordingTime(null); // Reset thời gian bắt đầu
      if (formattedTranscript.trim()) setShowSummary(true);
    } catch (error) {
      console.error('Failed to stop recording:', error);
      alert('Failed to stop recording. Check console for details.');
      setIsRecording(false);
      setStartRecordingTime(null);
    }
  };

  const handleTranscriptUpdate = (update: any) => {
    const newTranscript = {
      id: Date.now().toString(),
      text: update.text,
      timestamp: update.timestamp,
    };
    setTranscripts(prev => {
      const exists = prev.some(t => t.text === update.text && t.timestamp === update.timestamp);
      return exists ? prev : [...prev, newTranscript];
    });
  };

  const generateAISummary = useCallback(async () => {
    setSummaryStatus('processing');
    setSummaryError(null);
    try {
      const fullTranscript = transcripts.map(t => t.text).join('\n');
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
        } catch (error) {
          clearInterval(pollInterval);
          setSummaryStatus('error');
        }
      }, 5000);
      return () => clearInterval(pollInterval);
    } catch (error) {
      setSummaryStatus('error');
    }
  }, [transcripts, modelConfig]);

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
    const fullTranscript = transcripts
      .map(t => `[${formatRelativeTime(t.timestamp)}] ${t.text}`)
      .join('\n');
    navigator.clipboard.writeText(fullTranscript);
  }, [transcripts, formatRelativeTime]);

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
        } catch (error) {
          clearInterval(pollInterval);
          setSummaryStatus('error');
        }
      }, 10000);
      return () => clearInterval(pollInterval);
    } catch (error) {
      setSummaryStatus('error');
    }
  }, [originalTranscript, modelConfig]);

  const isSummaryLoading = summaryStatus === 'processing' || summaryStatus === 'summarizing' || summaryStatus === 'regenerating';

  const getLanguageName = (code: string) => {
    const lang = SUPPORTED_LANGUAGES.find(l => l.code === code);
    return lang ? lang.name : code;
  };

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

              {/* Hàng nút Copy và Generate */}
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

              {/* Translation selector - nằm dưới hàng nút */}
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
            </div>
          </div>

          {/* Transcript content - HIỂN THỊ GỐC, HOVER MỚI HIỆN DỊCH */}
          <div className="flex-1 overflow-y-auto pb-32">
            {transcripts.length > 0 ? (
              <div className="p-3 space-y-3">
                {transcripts.map((item, idx) => {
                  const translatedItem = translatedSegments.find(s => s.timestamp === item.timestamp);
                  return (
                    <div key={item.id} className="relative">
                      <div className="flex items-start gap-2">
                        <span className="text-[10px] font-mono text-gray-400 whitespace-nowrap mt-0.5">
                          {formatRelativeTime(item.timestamp)}
                        </span>
                        <div className="flex-1">
                          {/* Nội dung gốc - hover vào đây để hiện dịch */}
                          <div className="group w-full">
                            <p className="text-sm text-gray-700 leading-relaxed p-1 -m-1 rounded cursor-pointer transition-all duration-150 group-hover:bg-gray-100">
                              {item.text}
                            </p>
                            {/* Nội dung dịch - chỉ hiện khi hover vào group */}
                            {translatedItem && translatedItem.translated && (
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