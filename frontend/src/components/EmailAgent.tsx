'use client';

import { useState } from 'react';

interface EmailDraft {
  to_email: string;
  to_name: string;
  subject: string;
  body: string;
}

interface EmailAgentProps {
  meetingSummary: string;
  tasks: Array<{
    name: string;
    email: string;
    tasks: Array<{ task_name: string; deadline: string }>;
  }>;
  contextFileText?: string;
  onEmailsSent?: () => void;
}

export default function EmailAgent({
  meetingSummary,
  tasks,
  contextFileText,
  onEmailsSent
}: EmailAgentProps) {
  const [drafts, setDrafts] = useState<EmailDraft[]>([]);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    if (!meetingSummary || tasks.length === 0) {
      setError('Chưa có dữ liệu cuộc họp hoặc tasks để tạo email');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await fetch('http://localhost:5167/generate-email-drafts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          meeting_summary: meetingSummary,
          users_tasks: tasks,
          context_text: contextFileText || 'Đại diện Ban Giám Đốc công ty Meetily'
        })
      });

      const data = await res.json();

      if (data.success) {
        setDrafts(data.drafts);
        if (data.drafts.length === 0) {
          setError('Không thể tạo email. Vui lòng kiểm tra lại dữ liệu tasks.');
        }
      } else {
        setError(data.error || 'Lỗi khi tạo email');
      }
    } catch (err) {
      console.error(err);
      setError('Không thể kết nối đến server. Vui lòng kiểm tra backend.');
    } finally {
      setLoading(false);
    }
  };

  const handleSendAll = async () => {
    if (drafts.length === 0) return;

    setSending(true);
    setError(null);

    try {
      const res = await fetch('http://localhost:5167/send-emails', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ drafts })
      });

      const data = await res.json();

      if (data.success) {
        alert('✅ Email đang được gửi trong nền! Kiểm tra console (terminal) backend.');
        setDrafts([]);
        if (onEmailsSent) onEmailsSent();
      } else {
        setError(data.error || 'Lỗi khi gửi email');
      }
    } catch (err) {
      console.error(err);
      setError('Không thể kết nối đến server để gửi email.');
    } finally {
      setSending(false);
    }
  };

  const updateDraft = (index: number, field: keyof EmailDraft, value: string) => {
    const newDrafts = [...drafts];
    newDrafts[index][field] = value;
    setDrafts(newDrafts);
  };

  const removeDraft = (index: number) => {
    if (confirm(`Xóa email gửi cho ${drafts[index].to_name}?`)) {
      setDrafts(drafts.filter((_, i) => i !== index));
    }
  };

  if (tasks.length === 0 && drafts.length === 0) {
    return null;
  }

  return (
    <div className="mt-8 p-6 bg-blue-50/50 border border-blue-100 rounded-xl">
      <div className="flex justify-between items-center mb-4">
        <div>
          <h3 className="text-lg font-bold flex items-center gap-2">
            📧 AI Email Agent
          </h3>
          <p className="text-sm text-gray-500">
            {drafts.length > 0
              ? `${drafts.length} bản nháp đã sẵn sàng, bạn có thể chỉnh sửa trước khi gửi`
              : `Đã tìm thấy task của ${tasks.length} người. AI có thể viết mail ngay.`}
          </p>
        </div>

        {drafts.length === 0 ? (
          <button
            onClick={handleGenerate}
            disabled={loading || tasks.length === 0}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center gap-2"
          >
            {loading ? (
              <>
                <svg
                  className="animate-spin h-4 w-4 text-white"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                Đang soạn...
              </>
            ) : (
              '✨ Soạn Email Tự Động'
            )}
          </button>
        ) : (
          <button
            onClick={handleSendAll}
            disabled={sending}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center gap-2"
          >
            {sending ? (
              <>
                <svg
                  className="animate-spin h-4 w-4 text-white"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                Đang gửi...
              </>
            ) : (
              `📤 Gửi ${drafts.length} Email`
            )}
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-100 border border-red-400 text-red-700 rounded-lg text-sm">
          ❌ {error}
        </div>
      )}

      {drafts.length > 0 && (
        <div className="space-y-4 max-h-96 overflow-y-auto">
          {drafts.map((draft, idx) => (
            <div
              key={idx}
              className="p-4 bg-white border rounded-lg shadow-sm hover:shadow-md transition"
            >
              <div className="flex justify-between items-start mb-2">
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">
                    📬 Đến: {draft.to_name} ({draft.to_email})
                  </label>
                  <input
                    type="text"
                    value={draft.subject}
                    onChange={(e) => updateDraft(idx, 'subject', e.target.value)}
                    className="w-full font-bold text-lg border-b border-transparent hover:border-gray-300 focus:outline-none focus:border-blue-500 py-1"
                    placeholder="Tiêu đề email"
                  />
                </div>
                <button
                  onClick={() => removeDraft(idx)}
                  className="ml-2 text-red-500 hover:text-red-700 p-1 transition"
                  title="Xóa email này"
                >
                  🗑️
                </button>
              </div>

              <textarea
                value={draft.body}
                onChange={(e) => updateDraft(idx, 'body', e.target.value)}
                rows={5}
                className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-mono"
                placeholder="Nội dung email..."
              />
            </div>
          ))}
        </div>
      )}

      {/* Chế độ test mode indicator */}
      {process.env.NODE_ENV === 'development' && !drafts.length && tasks.length > 0 && (
        <div className="mt-3 text-xs text-gray-400 text-center">
          💡 Tip: Để gửi email thật, cấu hình RESEND_API_KEY trong file .env của backend
        </div>
      )}
    </div>
  );
}