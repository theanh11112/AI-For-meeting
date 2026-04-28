// components/Meeting/Transcript/TranscriptItem.tsx
'use client';

import { TranscriptWithSpeaker } from '@/types';
import { formatTimeFromSeconds, getSpeakerColor } from '@/utils/transcriptUtils';

interface TranscriptItemProps {
  item: TranscriptWithSpeaker;
  translatedText?: string;
  displayName: string;
  onSpeakerClick: (speakerId: string) => void;
}

export const TranscriptItem: React.FC<TranscriptItemProps> = ({
  item,
  translatedText,
  displayName,
  onSpeakerClick
}) => {
  const speakerColor = getSpeakerColor(item.speaker || '');

  return (
    <div className="relative group transition-colors duration-200 hover:bg-gray-50 rounded-lg p-1 -mx-1">
      <div className="flex items-start gap-2">
        <span className="text-[10px] font-mono text-gray-400 whitespace-nowrap mt-0.5">
          {formatTimeFromSeconds(item.t0)}
        </span>
        <div className="flex-1">
          <div className="w-full">
            <div className="flex items-center gap-2 mb-0.5">
              <button
                onClick={() => onSpeakerClick(item.speaker || 'UNKNOWN')}
                className={`text-[10px] font-semibold px-2 py-0.5 rounded-full cursor-pointer hover:opacity-80 transition-all border border-transparent hover:border-current ${speakerColor} ${!item.speaker ? 'bg-gray-100 text-gray-400' : ''}`}
                title="Nhấn để định danh người này"
              >
                {displayName}
              </button>
              
              {item.isVerified && (
                <span className="animate-in fade-in zoom-in duration-500 text-blue-500" title="Đã tinh chỉnh bởi WhisperX">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.64.304 1.24.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                </span>
              )}
            </div>
            
            <p className={`text-sm leading-relaxed transition-all duration-500 ${
              item.isVerified ? 'text-gray-900' : 'text-gray-500 italic'
            }`}>
              {item.text}
            </p>
            
            {/* PHẦN DỊCH - HIỂN THỊ NGAY BÊN DƯỚI, CÓ HIỆU ỨNG HOVER MƯỢT */}
            {translatedText && translatedText !== '[Translation failed]' && (
              <div className="overflow-hidden transition-all duration-300 max-h-0 group-hover:max-h-32 group-hover:mt-2">
                <p className="text-sm text-green-600 leading-relaxed border-l-2 border-green-400 pl-2 py-0.5 italic">
                  {translatedText}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};