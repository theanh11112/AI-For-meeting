'use client';

import { useEffect, useState } from 'react';

interface SpeakerContribution {
  name: string;
  contribution: number;
  talk_time: number;
  sentence_count: number;
}

interface ContributionChartProps {
  processId: string;
}

const COLORS = [
  '#3b82f6', // blue
  '#10b981', // green
  '#f59e0b', // amber
  '#ef4444', // red
  '#8b5cf6', // purple
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#84cc16', // lime
  '#f97316', // orange
  '#6366f1', // indigo
];

export function ContributionChart({ processId }: ContributionChartProps) {
  const [contributions, setContributions] = useState<SpeakerContribution[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadContributions = async () => {
      if (!processId) return;
      
      setLoading(true);
      setError(null);
      
      try {
        const response = await fetch(`http://localhost:5167/analyze-contributions/${processId}`);
        
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.status === 'success' && data.contributions) {
          setContributions(data.contributions);
        } else {
          setError(data.error || 'Không thể tải dữ liệu đóng góp');
        }
      } catch (err) {
        console.error('Failed to load contributions:', err);
        setError('Lỗi kết nối đến server');
      } finally {
        setLoading(false);
      }
    };
    
    loadContributions();
  }, [processId]);

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const totalTalkTime = contributions.reduce((sum, s) => sum + s.talk_time, 0);
  const totalSentences = contributions.reduce((sum, s) => sum + s.sentence_count, 0);

  if (loading) {
    return (
      <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
        <h3 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
          📊 Mức độ đóng góp của thành viên
        </h3>
        <div className="flex justify-center py-8">
          <div className="animate-pulse text-gray-400">Đang phân tích...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
        <h3 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
          📊 Mức độ đóng góp của thành viên
        </h3>
        <div className="text-center py-8 text-red-500">{error}</div>
      </div>
    );
  }

  if (contributions.length === 0) {
    return (
      <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
        <h3 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
          📊 Mức độ đóng góp của thành viên
        </h3>
        <div className="text-center py-8 text-gray-400">Chưa có dữ liệu đóng góp</div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
      <h3 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
        📊 Mức độ đóng góp của thành viên
      </h3>
      
      <div className="space-y-4">
        {contributions.map((speaker, index) => (
          <div key={speaker.name} className="space-y-1">
            <div className="flex justify-between items-center text-sm">
              <div className="flex items-center gap-2">
                <div 
                  className="w-3 h-3 rounded-full" 
                  style={{ backgroundColor: COLORS[index % COLORS.length] }}
                />
                <span className="font-medium text-gray-700">{speaker.name}</span>
              </div>
              <div className="flex gap-3 text-gray-500">
                <span>🎤 {speaker.sentence_count} câu</span>
                <span>⏱️ {formatTime(speaker.talk_time)}</span>
                <span className="font-bold text-gray-900">{speaker.contribution}%</span>
              </div>
            </div>
            
            <div className="relative w-full h-8 bg-gray-100 rounded-full overflow-hidden">
              <div 
                className="absolute left-0 top-0 h-full rounded-full transition-all duration-500 flex items-center justify-end px-3"
                style={{ 
                  width: `${speaker.contribution}%`,
                  backgroundColor: COLORS[index % COLORS.length]
                }}
              >
                <span className="text-xs text-white font-medium">
                  {speaker.contribution}%
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
      
      <div className="mt-6 pt-4 border-t border-gray-100">
        <div className="flex justify-between text-sm text-gray-500">
          <span>📝 Tổng số câu: {totalSentences}</span>
          <span>⏱️ Tổng thời gian: {formatTime(totalTalkTime)}</span>
        </div>
      </div>
    </div>
  );
}