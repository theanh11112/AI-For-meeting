// frontend/src/components/AISummary/index.tsx
'use client';

import { useState } from 'react';
import { EnhancedSummary, SummaryStatus } from '@/types';
import { TaskCard } from '@/components/Meeting/Summary/TaskCard';
import { CheckCircleIcon, ListBulletIcon, ChatBubbleBottomCenterTextIcon, QuestionMarkCircleIcon, LightBulbIcon } from '@heroicons/react/24/outline';

interface Props {
  summary: EnhancedSummary | null;
  status: SummaryStatus;
  error: string | null;
  onRegenerateSummary?: () => void;
  onSummaryChange?: (summary: EnhancedSummary) => void;
}

export const AISummary = ({ summary, status, error, onRegenerateSummary }: Props) => {
  const [activeTab, setActiveTab] = useState<'overview' | 'tasks' | 'decisions' | 'questions'>('overview');

  if (error) {
    return (
      <div className="p-6 text-center">
        <div className="bg-red-50 border border-red-200 rounded-xl p-4">
          <p className="text-red-600 text-sm">{error}</p>
          {onRegenerateSummary && (
            <button
              onClick={onRegenerateSummary}
              className="mt-3 text-sm text-red-600 hover:text-red-700 underline"
            >
              Thử lại
            </button>
          )}
        </div>
      </div>
    );
  }

  if (status === 'processing' || status === 'summarizing' || status === 'regenerating') {
    return (
      <div className="flex flex-col items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-indigo-500 mb-4"></div>
        <p className="text-gray-500 text-sm">AI đang phân tích nội dung cuộc họp...</p>
        <p className="text-gray-400 text-xs mt-1">Quá trình này có thể mất vài giây</p>
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-center">
        <ChatBubbleBottomCenterTextIcon className="h-12 w-12 text-gray-300 mb-3" />
        <p className="text-gray-400 text-sm">Chưa có tóm tắt nào</p>
        <p className="text-gray-300 text-xs">Hãy ghi âm và nhấn "Generate Note"</p>
      </div>
    );
  }

  const tabs = [
    { id: 'overview', label: 'Toàn cảnh', icon: ChatBubbleBottomCenterTextIcon, count: null },
    { id: 'tasks', label: 'Công việc', icon: ListBulletIcon, count: summary.action_items?.length || 0 },
    { id: 'decisions', label: 'Quyết định', icon: CheckCircleIcon, count: summary.key_decisions?.length || 0 },
    { id: 'questions', label: 'Câu hỏi', icon: QuestionMarkCircleIcon, count: summary.pending_questions?.length || 0 },
  ];

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1 border-b border-gray-100 mb-6 sticky top-0 bg-white z-10 pb-0">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className={`px-4 py-2.5 text-sm font-medium transition-all flex items-center gap-2 rounded-t-lg ${
                isActive
                  ? 'bg-indigo-50 text-indigo-700 border-b-2 border-indigo-600'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              }`}
            >
              <Icon className="h-4 w-4" />
              {tab.label}
              {tab.count !== null && tab.count > 0 && (
                <span className={`ml-1 px-1.5 py-0.5 text-xs rounded-full ${
                  isActive ? 'bg-indigo-100 text-indigo-600' : 'bg-gray-100 text-gray-500'
                }`}>
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="flex-1 overflow-y-auto pr-2 pb-4">
        {activeTab === 'overview' && (
          <div className="space-y-6 animate-in fade-in slide-in-from-left duration-300">
            <div className="bg-gradient-to-r from-indigo-50 to-blue-50 rounded-xl p-4 border border-indigo-100">
              <h2 className="text-xl font-bold text-gray-800">{summary.meeting_name}</h2>
              <p className="text-xs text-gray-500 mt-1">📅 {summary.meeting_date}</p>
            </div>

            <section>
              <h3 className="text-md font-bold text-gray-800 mb-3 flex items-center gap-2">
                <LightBulbIcon className="h-5 w-5 text-amber-500" />
                Tóm tắt nội dung
              </h3>
              <p className="text-sm text-gray-700 leading-relaxed bg-gray-50 p-4 rounded-xl border border-gray-100 italic">
                {summary.general_summary}
              </p>
            </section>

            {summary.key_topics_discussed && summary.key_topics_discussed.length > 0 && (
              <section>
                <h3 className="text-md font-bold text-gray-800 mb-3">🏷️ Chủ đề chính</h3>
                <div className="flex flex-wrap gap-2">
                  {summary.key_topics_discussed.map((topic, idx) => (
                    <span key={idx} className="px-3 py-1 bg-gray-100 text-gray-600 text-xs rounded-full">
                      {topic}
                    </span>
                  ))}
                </div>
              </section>
            )}

            <div className="grid grid-cols-3 gap-3 pt-2">
              <div className="bg-green-50 rounded-lg p-3 text-center border border-green-100">
                <div className="text-2xl font-bold text-green-600">{summary.action_items?.length || 0}</div>
                <div className="text-xs text-gray-500">Công việc</div>
              </div>
              <div className="bg-purple-50 rounded-lg p-3 text-center border border-purple-100">
                <div className="text-2xl font-bold text-purple-600">{summary.key_decisions?.length || 0}</div>
                <div className="text-xs text-gray-500">Quyết định</div>
              </div>
              <div className="bg-amber-50 rounded-lg p-3 text-center border border-amber-100">
                <div className="text-2xl font-bold text-amber-600">{summary.pending_questions?.length || 0}</div>
                <div className="text-xs text-gray-500">Câu hỏi</div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'tasks' && (
          <div className="animate-in fade-in slide-in-from-right duration-300">
            {summary.action_items && summary.action_items.length > 0 ? (
              <div>
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-md font-bold text-gray-800">🚀 Nhiệm vụ cần thực hiện</h3>
                  <span className="text-xs text-gray-400">{summary.action_items.length} công việc</span>
                </div>
                {summary.action_items.map((task, index) => (
                  <TaskCard key={index} task={task} />
                ))}
              </div>
            ) : (
              <div className="text-center py-12">
                <ListBulletIcon className="h-12 w-12 text-gray-300 mx-auto mb-3" />
                <p className="text-gray-400 text-sm">Không tìm thấy công việc nào cần làm</p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'decisions' && (
          <div className="space-y-3 animate-in fade-in duration-300">
            {summary.key_decisions && summary.key_decisions.length > 0 ? (
              summary.key_decisions.map((decision, idx) => (
                <div key={idx} className="flex gap-3 p-4 bg-green-50 rounded-xl border border-green-100">
                  <CheckCircleIcon className="h-5 w-5 text-green-600 shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-semibold text-gray-800">{decision.decision}</p>
                    <p className="text-xs text-gray-500 mt-1">
                      Quyết định bởi: <span className="font-medium text-gray-700">{decision.made_by}</span>
                    </p>
                    {decision.context && (
                      <p className="text-xs text-gray-400 mt-1 italic">"{decision.context}"</p>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-12">
                <CheckCircleIcon className="h-12 w-12 text-gray-300 mx-auto mb-3" />
                <p className="text-gray-400 text-sm">Chưa có quyết định nào được ghi nhận</p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'questions' && (
          <div className="space-y-3 animate-in fade-in duration-300">
            {summary.pending_questions && summary.pending_questions.length > 0 ? (
              summary.pending_questions.map((question, idx) => (
                <div key={idx} className="flex gap-3 p-4 bg-amber-50 rounded-xl border border-amber-100">
                  <QuestionMarkCircleIcon className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-gray-800">{question.question}</p>
                    <div className="flex gap-3 mt-2 text-xs text-gray-500">
                      <span>❓ Hỏi bởi: {question.asked_by}</span>
                      {question.assigned_to && (
                        <span>📌 Trả lời: {question.assigned_to}</span>
                      )}
                      {question.urgency && (
                        <span className={`px-1.5 py-0.5 rounded-full ${
                          question.urgency === 'Cao' ? 'bg-red-100 text-red-600' : 'bg-gray-100 text-gray-500'
                        }`}>
                          {question.urgency}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-12">
                <QuestionMarkCircleIcon className="h-12 w-12 text-gray-300 mx-auto mb-3" />
                <p className="text-gray-400 text-sm">Không có câu hỏi nào cần theo dõi</p>
              </div>
            )}
          </div>
        )}
      </div>

      {onRegenerateSummary && (
        <div className="border-t border-gray-100 pt-4 mt-2">
          <button
            onClick={onRegenerateSummary}
            className="w-full py-2 text-sm text-gray-500 hover:text-indigo-600 transition-colors flex items-center justify-center gap-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clipRule="evenodd" />
            </svg>
            Tạo lại tóm tắt
          </button>
        </div>
      )}
    </div>
  );
};

export default AISummary;