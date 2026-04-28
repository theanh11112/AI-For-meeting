// components/Meeting/Transcript/TranscriptList.tsx
'use client';

import { useEffect, useRef } from 'react';
import { TranscriptWithSpeaker, TranslatedSegment } from '@/types';
import { TranscriptItem } from './TranscriptItem';

interface TranscriptListProps {
  transcripts: TranscriptWithSpeaker[];
  translatedSegments: TranslatedSegment[];
  getSpeakerDisplayName: (speakerId: string) => string;
  onSpeakerClick: (speakerId: string) => void;
}

export const TranscriptList: React.FC<TranscriptListProps> = ({
  transcripts,
  translatedSegments,
  getSpeakerDisplayName,
  onSpeakerClick
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevTranscriptsLength = useRef(0);
  const isUserScrollingRef = useRef(false);
  const scrollTimeoutRef = useRef<NodeJS.Timeout>();

  const handleScroll = () => {
    isUserScrollingRef.current = true;
    if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current);
    scrollTimeoutRef.current = setTimeout(() => {
      isUserScrollingRef.current = false;
    }, 150);
  };

  useEffect(() => {
    const scrollElement = scrollRef.current;
    if (scrollElement) {
      scrollElement.addEventListener('scroll', handleScroll);
      return () => {
        scrollElement.removeEventListener('scroll', handleScroll);
        if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current);
      };
    }
  }, []);

  useEffect(() => {
    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    const { scrollTop, scrollHeight, clientHeight } = scrollElement;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
    
    if (transcripts.length > prevTranscriptsLength.current) {
      if (!isUserScrollingRef.current || isNearBottom) {
        scrollElement.scrollTo({
          top: scrollElement.scrollHeight,
          behavior: 'smooth'
        });
      }
    }
    
    prevTranscriptsLength.current = transcripts.length;
  }, [transcripts]);

  if (transcripts.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="p-4 text-center text-gray-400 text-sm">
          Chưa có transcript. Nhấn Record để bắt đầu ghi âm.
        </div>
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto pb-32">
      <div className="p-3 space-y-3">
        {[...transcripts]
          .sort((a, b) => a.t0 - b.t0)
          .map((item) => {
            // Tìm bản dịch bằng t0 với sai số 0.2 giây
            const translatedItem = translatedSegments.find(
              s => Math.abs(s.t0 - item.t0) < 0.2
            );
            const displayName = getSpeakerDisplayName(item.speaker || 'UNKNOWN');
            
            return (
              <TranscriptItem
                key={item.id}
                item={item}
                translatedText={translatedItem?.translated}
                displayName={displayName}
                onSpeakerClick={onSpeakerClick}
              />
            );
          })}
      </div>
    </div>
  );
};