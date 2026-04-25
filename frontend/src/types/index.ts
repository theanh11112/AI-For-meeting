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

// ============ NEW: Detailed types từ Backend ============
export interface DetailedActionItem {
  task: string;
  assignee_name: string;
  assignee_email: string;
  context: string;
  instructions: string;
  deadline: string;
  priority: 'Cao' | 'Trung bình' | 'Thấp';
}

export interface Decision {
  decision: string;
  made_by: string;
  context: string;
}

export interface PendingQuestion {
  question: string;
  asked_by: string;
  assigned_to: string;
  urgency: string;
}

export interface EnhancedSummary {
  meeting_name: string;
  meeting_date: string;
  general_summary: string;
  key_decisions: Decision[];
  action_items: DetailedActionItem[];
  pending_questions: PendingQuestion[];
  key_topics_discussed: string[];
}

// Legacy Summary (giữ cho tương thích)
export interface Summary {
  [key: string]: Section;
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

// ============ INTERFACE HIỆN CÓ ============
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

export type SummaryStatus = 'idle' | 'processing' | 'summarizing' | 'regenerating' | 'completed' | 'error';

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