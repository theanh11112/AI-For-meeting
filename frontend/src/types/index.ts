// frontend/src/types/index.ts
export interface Message {
  id: string;
  content: string;
  timestamp: string;
}

export interface Transcript {
  id: string;
  text: string;
  timestamp: string;
}

export interface Block {
  id: string;
  type: string;
  content: string;
  color: string;
}

export interface Section {
  title: string;
  blocks: Block[];
}

// ✅ SỬA: Summary linh hoạt với index signature
export interface Summary {
  MeetingName?: string;
  [key: string]: any; // Cho phép bất kỳ key nào khác (SectionSummary, KeyItemsDecisions, IndividualTasks, v.v.)
}

export interface ApiResponse {
  message: string;
  num_chunks: number;
  data: any[];
}

export interface SummaryResponse {
  status: string;
  summary: Summary;
  raw_summary?: string;
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

// ============ CÁC INTERFACE KHÁC ============

export interface TranscriptWithSpeaker extends Transcript {
  t0: number;
  t1: number;
  speaker?: string;
  seq?: number;
  isVerified?: boolean;
}

export interface TranslatedSegment {
  timestamp: string;
  original: string;
  translated: string;
  t0: number;
  t1: number;
  speaker?: string;
}

export interface SpeakerMap {
  speaker_id: string;
  name: string;
  email: string;
}

export interface ModelConfig {
  provider: 'ollama' | 'groq' | 'claude';
  model: string;
  whisperModel: string;
}

export type SummaryStatus = 'idle' | 'processing' | 'summarizing' | 'regenerating' | 'completed' | 'error' | 'loading';

export interface TranscriptUpdate {
  text: string;
  timestamp: string;
  source: string;
  t0?: number;
  t1?: number;
  seq?: number;
}

export interface OllamaModel {
  name: string;
  id: string;
  size: string;
  modified: string;
}

export interface SummaryBlock {
  title: string;
  content: string;
  type?: 'bullet' | 'number' | 'text';
  color?: string;
}

export interface SummarySection {
  title: string;
  blocks: SummaryBlock[];
}

export interface AsyncSummaryResponse {
  status: 'processing' | 'completed' | 'error';
  data?: Summary;
  error?: string;
}

// ❌ XÓA các interface Summary cũ bị trùng (đã comment hoặc xóa)
// export interface Summary {
//     key_points: string[];
//     action_items: string[];
//     decisions: string[];
//     main_topics: string[];
//     participants?: string[];
// }

// export interface SummaryResponse {
//     summary: Summary;
//     raw_summary?: string;
// }

export interface ProcessRequest {
    transcript: string;
    metadata?: {
        meeting_title?: string;
        date?: string;
        duration?: number;
    };
}