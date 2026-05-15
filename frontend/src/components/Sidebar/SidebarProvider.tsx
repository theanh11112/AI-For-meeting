'use client';

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { usePathname } from 'next/navigation';

interface SidebarItem {
  id: string;
  title: string;
  type: 'folder' | 'file';
  date?: string;
  status?: string;
  children?: SidebarItem[];
}

interface CurrentMeeting {
  id: string;
  title: string;
}

interface SidebarContextType {
  currentMeeting: CurrentMeeting | null;
  setCurrentMeeting: (meeting: CurrentMeeting | null) => void;
  sidebarItems: SidebarItem[];
  isCollapsed: boolean;
  toggleCollapse: () => void;
  refreshMeetings: (isLoadMore?: boolean) => Promise<void>;
  deleteMeeting: (id: string) => Promise<boolean>;
  hasMore: boolean;
  isLoadingMore: boolean;
}

const SidebarContext = createContext<SidebarContextType | null>(null);

export const useSidebar = () => {
  const context = useContext(SidebarContext);
  if (!context) {
    throw new Error('useSidebar must be used within a SidebarProvider');
  }
  return context;
};

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [currentMeeting, setCurrentMeeting] = useState<CurrentMeeting | null>(null);
  const [isCollapsed, setIsCollapsed] = useState(true);
  const [meetingHistory, setMeetingHistory] = useState<SidebarItem[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const LIMIT = 5;
  const pathname = usePathname();

  // Hàm gọi API lấy danh sách cuộc họp từ Backend
  const refreshMeetings = useCallback(async (isLoadMore: boolean = false) => {
    try {
      if (isLoadMore) {
        setIsLoadingMore(true);
      }
      
      const currentOffset = isLoadMore ? offset : 0;
      console.log(`🔄 Đang tải cuộc họp: offset=${currentOffset}, limit=${LIMIT}, isLoadMore=${isLoadMore}`);
      
      const response = await fetch(`http://localhost:5167/meetings?limit=${LIMIT}&offset=${currentOffset}`);
      const data = await response.json();
      console.log("Dữ liệu thô từ API:", data);
      
      if (data.status === 'success') {
        const newMeetings: SidebarItem[] = data.meetings.map((m: any) => ({
          id: m.process_id,
          title: m.meeting_name || 'Cuộc họp không tên',
          type: 'file',
          date: m.created_at,
          status: m.status
        }));
        
        console.log(`✅ Đã tải ${newMeetings.length} cuộc họp`);
        
        setHasMore(newMeetings.length === LIMIT);
        
        if (isLoadMore) {
          setMeetingHistory(prev => [...prev, ...newMeetings]);
          setOffset(prevOffset => prevOffset + LIMIT);
        } else {
          setMeetingHistory(newMeetings);
          setOffset(LIMIT);
        }
      } else {
        console.error('❌ API trả về status error:', data);
        setHasMore(false);
      }
    } catch (error) {
      console.error('❌ Lỗi khi tải lịch sử cuộc họp:', error);
      setHasMore(false);
    } finally {
      if (isLoadMore) {
        setIsLoadingMore(false);
      }
    }
  }, [offset]);

  // Hàm gọi API xóa cuộc họp
  const deleteMeeting = useCallback(async (id: string) => {
    try {
      console.log(`🗑️ Đang xóa cuộc họp: ${id}`);
      const response = await fetch(`http://localhost:5167/meetings/${id}`, {
        method: 'DELETE'
      });
      if (response.ok) {
        setOffset(0);
        setHasMore(true);
        await refreshMeetings(false);
        
        if (currentMeeting?.id === id) {
          // ✅ Chuyển hướng về trang chủ thay vì set state
          window.location.href = '/';
        }
        console.log('✅ Xóa thành công');
        return true;
      }
      console.error('❌ Xóa thất bại, status:', response.status);
      return false;
    } catch (error) {
      console.error('❌ Lỗi khi xóa cuộc họp:', error);
      return false;
    }
  }, [refreshMeetings, currentMeeting]);

  // Load 5 cuộc họp đầu tiên khi mở app
  useEffect(() => {
    refreshMeetings(false);
  }, []);

  // Cấu trúc Sidebar
  const baseItems: SidebarItem[] = [
    {
      id: 'meetings',
      title: 'Lịch sử cuộc họp',
      type: 'folder' as const,
      children: meetingHistory
    }
  ];

  // Thêm "New Call" vào đầu danh sách nếu đang tạo cuộc họp mới
  const sidebarItems: SidebarItem[] = baseItems.map(item => {
    if (item.id === 'meetings' && currentMeeting && currentMeeting.id === 'intro-call') {
      const hasNewCall = item.children?.some(child => child.id === 'intro-call');
      if (!hasNewCall) {
        return {
          ...item,
          children: [
            { 
              id: 'intro-call', 
              title: currentMeeting.title, 
              type: 'file' as const, 
              date: new Date().toISOString(),
              status: 'pending'
            },
            ...(item.children || [])
          ]
        };
      }
    }
    return item;
  });

  const toggleCollapse = () => {
    setIsCollapsed(!isCollapsed);
  };

  // ✅ COMMENT LẠI - ĐÂY LÀ NGUYÊN NHÂN GÂY RE-RENDER
  // useEffect(() => {
  //   if (pathname === '/') {
  //     setCurrentMeeting({ id: 'intro-call', title: 'New Call' });
  //   }
  // }, [pathname]);

  return (
    <SidebarContext.Provider value={{ 
      currentMeeting, 
      setCurrentMeeting, 
      sidebarItems, 
      isCollapsed, 
      toggleCollapse,
      refreshMeetings,
      deleteMeeting,
      hasMore,
      isLoadingMore
    }}>
      {children}
    </SidebarContext.Provider>
  );
}