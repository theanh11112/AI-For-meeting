// frontend/src/components/Meeting/Summary/TaskCard.tsx
'use client';

import { DetailedActionItem } from '@/types';
import { useState } from 'react';

interface TaskCardProps {
  task: DetailedActionItem;
  onSendEmail?: (task: DetailedActionItem) => void;
}

export const TaskCard = ({ task, onSendEmail }: TaskCardProps) => {
  const [isSending, setIsSending] = useState(false);
  
  const priorityColor = {
    'Cao': 'bg-red-100 text-red-700 border-red-200',
    'Trung bình': 'bg-yellow-100 text-yellow-700 border-yellow-200',
    'Thấp': 'bg-blue-100 text-blue-700 border-blue-200'
  }[task.priority] || 'bg-gray-100';

  const handleSendEmail = async () => {
    if (!task.assignee_email || task.assignee_email === 'Chưa có email') {
      alert(`Không thể gửi email vì ${task.assignee_name} chưa có email. Vui lòng cập nhật email trong danh bạ.`);
      return;
    }
    
    setIsSending(true);
    try {
      const response = await fetch('http://localhost:5167/send-task-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: task.task,
          assignee_email: task.assignee_email,
          assignee_name: task.assignee_name,
          instructions: task.instructions,
          deadline: task.deadline,
          context: task.context
        })
      });
      
      const result = await response.json();
      if (result.status === 'success') {
        alert(`✅ Đã gửi email nhắc việc đến ${task.assignee_email}`);
        if (onSendEmail) onSendEmail(task);
      } else {
        alert(`❌ Gửi email thất bại: ${result.error}`);
      }
    } catch (error) {
      console.error('Error sending email:', error);
      alert('❌ Lỗi kết nối, không thể gửi email');
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm mb-4 hover:border-indigo-300 hover:shadow-md transition-all group">
      <div className="flex justify-between items-start mb-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center text-white font-bold shadow-sm group-hover:scale-110 transition-transform">
            {task.assignee_name.charAt(0).toUpperCase()}
          </div>
          <div>
            <h4 className="font-bold text-sm text-gray-900">{task.assignee_name}</h4>
            <p className="text-[10px] text-gray-500 font-mono">
              {task.assignee_email || 'Chưa có email'}
            </p>
          </div>
        </div>
        <span className={`text-[10px] font-bold px-2 py-1 rounded-full border ${priorityColor}`}>
          {task.priority.toUpperCase()}
        </span>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-bold text-gray-800 flex items-start gap-2">
          <span>📌</span>
          <span>{task.task}</span>
        </h3>
        
        <div className="bg-amber-50 p-3 rounded-lg border-l-4 border-amber-400">
          <p className="text-xs text-gray-700 leading-relaxed">
            <span className="font-bold text-amber-700">💡 Ngữ cảnh:</span> "{task.context}"
          </p>
        </div>

        <div className="bg-indigo-50/30 p-3 rounded-lg border border-indigo-100/50">
          <p className="text-xs font-bold mb-2 text-indigo-700 flex items-center gap-1">
            <span>📋</span> Hướng dẫn thực hiện:
          </p>
          <p className="text-xs text-gray-700 leading-relaxed whitespace-pre-line">
            {task.instructions}
          </p>
        </div>

        <div className="mt-3 pt-3 border-t border-gray-100 flex justify-between items-center">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">📅 Hạn:</span>
            <span className="text-xs font-medium text-gray-700">{task.deadline}</span>
          </div>
          
          <button 
            onClick={handleSendEmail}
            disabled={isSending}
            className="flex items-center gap-1.5 text-xs font-medium text-white bg-indigo-600 px-3 py-1.5 rounded-lg hover:bg-indigo-700 disabled:bg-indigo-400 transition-all shadow-sm"
          >
            {isSending ? (
              <>
                <svg className="animate-spin h-3 w-3 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Đang gửi...
              </>
            ) : (
              <>
                <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M2.003 5.884L10 9.882l7.997-3.998A2 2 0 0016 4H4a2 2 0 00-1.997 1.884z" />
                  <path d="M18 8.118l-8 4-8-4V14a2 2 0 002 2h12a2 2 0 002-2V8.118z" />
                </svg>
                Gửi nhắc việc
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};