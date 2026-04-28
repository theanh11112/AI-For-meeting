// components/CompanyContextManager.tsx
'use client';

import { useState, useEffect } from 'react';

interface CompanyContextManagerProps {
  onClose?: () => void;
}

export default function CompanyContextManager({ onClose }: CompanyContextManagerProps) {
  const [context, setContext] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState<'success' | 'error'>('success');

  useEffect(() => {
    loadContext();
  }, []);

  const loadContext = async () => {
    try {
      const res = await fetch('http://localhost:5167/company-context');
      const data = await res.json();
      if (data.success) {
        setContext(data.content);
      } else {
        setMessageType('error');
        setMessage('❌ Không thể tải cấu hình công ty');
      }
    } catch (err) {
      console.error('Lỗi tải context:', err);
      setMessageType('error');
      setMessage('❌ Không thể kết nối đến server');
    } finally {
      setIsLoading(false);
    }
  };

  const saveContext = async () => {
    if (!context.trim()) {
      setMessageType('error');
      setMessage('❌ Vui lòng nhập thông tin công ty');
      return;
    }

    try {
      const res = await fetch('http://localhost:5167/company-context', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: context }),
      });
      const data = await res.json();
      if (data.success) {
        setMessageType('success');
        setMessage('✅ Đã lưu thành công!');
        setTimeout(() => {
          setMessage('');
          if (onClose) onClose();
        }, 1500);
      } else {
        setMessageType('error');
        setMessage('❌ Lỗi khi lưu: ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      setMessageType('error');
      setMessage('❌ Không thể kết nối đến server để lưu');
      console.error(err);
    }
  };

  const downloadContext = () => {
    window.open('http://localhost:5167/company-context/download', '_blank');
  };

  const resetToDefault = () => {
    const defaultContext = `Tên công ty: Meetily Corporation
Người gửi: Thế Anh
Chức danh: Giám đốc Điều hành (CEO)
Email người gửi: ceo@meetily.com
Giọng văn: Chuyên nghiệp, thân thiện, rõ ràng, dễ hiểu
Lĩnh vực: Cung cấp giải pháp phần mềm AI và tự động hóa doanh nghiệp
Thông điệp: Đồng hành cùng sự phát triển của đối tác
Chữ ký mặc định: Trân trọng,`;
    setContext(defaultContext);
    setMessageType('success');
    setMessage('✅ Đã khôi phục cài đặt mặc định');
    setTimeout(() => setMessage(''), 3000);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-blue-500 mb-2"></div>
          <p className="text-gray-600">Đang tải cấu hình...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          📝 Thông tin công ty
        </label>
        <p className="text-xs text-gray-500 mb-2">
          Nội dung này sẽ được AI sử dụng để viết email với đúng ngữ cảnh công ty của bạn
        </p>
        <textarea
          value={context}
          onChange={(e) => setContext(e.target.value)}
          rows={12}
          className="w-full p-3 border border-gray-300 rounded-lg font-mono text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition"
          placeholder="Nhập thông tin công ty..."
        />
      </div>

      <div className="flex justify-end gap-3">
        <button
          onClick={resetToDefault}
          className="px-4 py-2 text-sm bg-yellow-500 text-white rounded-lg hover:bg-yellow-600 transition flex items-center gap-2"
        >
          🔄 Khôi phục mặc định
        </button>
        <button
          onClick={downloadContext}
          className="px-4 py-2 text-sm bg-gray-500 text-white rounded-lg hover:bg-gray-600 transition flex items-center gap-2"
        >
          📥 Tải xuống
        </button>
        <button
          onClick={saveContext}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition flex items-center gap-2"
        >
          💾 Lưu thay đổi
        </button>
      </div>

      {message && (
        <div
          className={`mt-3 p-3 rounded-lg text-center text-sm font-medium ${
            messageType === 'success'
              ? 'bg-green-100 text-green-700'
              : 'bg-red-100 text-red-700'
          }`}
        >
          {message}
        </div>
      )}

      <div className="mt-4 pt-4 border-t border-gray-200">
        <p className="text-xs text-gray-400 text-center">
          💡 Gợi ý: Bạn có thể nhập tên công ty, chức danh người gửi, giọng văn mong muốn...
        </p>
      </div>
    </div>
  );
}