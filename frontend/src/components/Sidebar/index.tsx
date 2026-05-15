'use client';

import React, { useState } from 'react';
import { ChevronDown, ChevronRight, File, Settings, ChevronLeftCircle, ChevronRightCircle, Calendar, Plus, Trash2, Loader2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useSidebar } from './SidebarProvider';

interface SidebarItem {
  id: string;
  title: string;
  type: 'folder' | 'file';
  date?: string;
  status?: string;
  children?: SidebarItem[];
}

const Sidebar: React.FC = () => {
  const router = useRouter();
  const { 
    sidebarItems, 
    isCollapsed, 
    toggleCollapse, 
    deleteMeeting, 
    currentMeeting, 
    refreshMeetings,
    hasMore,
    isLoadingMore
  } = useSidebar();
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set(['meetings']));

  const toggleFolder = (folderId: string) => {
    const newExpanded = new Set(expandedFolders);
    if (newExpanded.has(folderId)) {
      newExpanded.delete(folderId);
    } else {
      newExpanded.add(folderId);
    }
    setExpandedFolders(newExpanded);
  };

  const handleDelete = async (e: React.MouseEvent, id: string, title: string) => {
    e.stopPropagation();
    if (confirm(`Bạn có chắc muốn xóa vĩnh viễn cuộc họp "${title}" không?`)) {
      await deleteMeeting(id);
    }
  };

  const handleNewMeeting = () => {
    window.location.href = '/';
  };

  const handleLoadMore = async () => {
    await refreshMeetings(true);
  };

  const renderCollapsedIcons = () => {
    if (!isCollapsed) return null;

    return (
      <div className="flex flex-col items-center space-y-4 mt-4">
        <button 
          onClick={handleNewMeeting} 
          className="p-2 bg-blue-100 hover:bg-blue-200 rounded-md transition-colors" 
          title="Cuộc họp mới"
        >
          <Plus className="w-5 h-5 text-blue-600" />
        </button>
        <button
          onClick={() => { toggleCollapse(); toggleFolder('meetings'); }}
          className="p-2 hover:bg-gray-100 rounded-md transition-colors"
          title="Lịch sử"
        >
          <Calendar className="w-5 h-5 text-gray-600" />
        </button>
      </div>
    );
  };

  const renderItem = (item: SidebarItem, depth = 0) => {
    const isExpanded = expandedFolders.has(item.id);
    const paddingLeft = `${depth * 12 + 12}px`;
    const isActive = currentMeeting?.id === item.id;

    if (isCollapsed) return null;

    return (
      <div key={item.id}>
        <div
          className={`group flex items-center justify-between px-2 py-2 cursor-pointer text-sm transition-colors ${
            isActive ? 'bg-blue-50 text-blue-700 font-medium border-r-2 border-blue-600' : 'hover:bg-gray-100 text-gray-700'
          }`}
          style={{ paddingLeft }}
          onClick={() => {
            if (item.type === 'folder') {
              toggleFolder(item.id);
            } else {
              if (item.id === 'intro-call') {
                window.location.href = '/';
              } else {
                console.log(`🔍 Chuyển đến cuộc họp: ${item.id}`);
                router.push(`/?id=${item.id}`);
              }
            }
          }}
        >
          <div className="flex items-center flex-1 overflow-hidden">
            {item.type === 'folder' ? (
              <>
                <Calendar className="w-4 h-4 mr-2 text-gray-500" />
                {isExpanded ? <ChevronDown className="w-4 h-4 mr-1" /> : <ChevronRight className="w-4 h-4 mr-1" />}
                <span className="truncate">{item.title}</span>
              </>
            ) : (
              <>
                <File className={`w-4 h-4 mr-2 ${isActive ? 'text-blue-500' : 'text-gray-400'}`} />
                <div className="flex flex-col truncate">
                  <span className="truncate">{item.title}</span>
                  {item.date && (
                    <span className="text-[10px] text-gray-400 font-normal truncate">
                      {new Date(item.date).toLocaleDateString('vi-VN', { 
                        month: 'short', 
                        day: 'numeric', 
                        hour: '2-digit', 
                        minute: '2-digit' 
                      })}
                    </span>
                  )}
                </div>
              </>
            )}
          </div>

          {/* Nút xóa - Chỉ hiện cho các cuộc họp từ database */}
          {item.type === 'file' && item.id !== 'intro-call' && (
            <button 
              onClick={(e) => handleDelete(e, item.id, item.title)}
              className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-100 rounded text-red-500 transition-opacity"
              title="Xóa cuộc họp"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {item.type === 'folder' && isExpanded && item.children && (
          <div>
            {item.children.map(child => renderItem(child, depth + 1))}
            
            {/* Nút "Tải thêm" - Chỉ hiển thị ở folder meetings */}
            {item.id === 'meetings' && hasMore && (
              <button
                onClick={handleLoadMore}
                disabled={isLoadingMore}
                className="w-full text-center py-2 mt-1 text-xs text-blue-600 hover:text-blue-800 hover:bg-blue-50 rounded transition-colors"
              >
                {isLoadingMore ? (
                  <span className="flex items-center justify-center gap-1">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    Đang tải...
                  </span>
                ) : (
                  '📥 Tải thêm cuộc họp cũ'
                )}
              </button>
            )}
            
            {/* Hiển thị thông báo nếu không còn dữ liệu */}
            {item.id === 'meetings' && !hasMore && sidebarItems.find(i => i.id === 'meetings')?.children?.length ? (
              <p className="text-center text-xs text-gray-400 py-2">
                Đã hiển thị tất cả {sidebarItems.find(i => i.id === 'meetings')?.children?.length} cuộc họp
              </p>
            ) : null}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="fixed top-0 left-0 h-screen z-40">
      {/* Floating collapse button */}
      <button
        onClick={toggleCollapse}
        className="absolute -right-6 top-20 z-50 p-1 bg-white hover:bg-gray-100 rounded-full shadow-lg border"
        style={{ transform: 'translateX(50%)' }}
      >
        {isCollapsed ? <ChevronRightCircle className="w-6 h-6 text-gray-500" /> : <ChevronLeftCircle className="w-6 h-6 text-gray-500" />}
      </button>

      <div className={`h-screen bg-[#F9FAFB] border-r border-gray-200 flex flex-col transition-all duration-300 ${isCollapsed ? 'w-16' : 'w-64'}`}>
        {/* Header */}
        <div className="h-16 flex items-center px-4 border-b border-gray-200 bg-white">
          {!isCollapsed && (
            <div className="flex justify-between items-center w-full">
              <h1 className="font-bold text-sm text-gray-800">Meetily AI</h1>
              <button 
                onClick={handleNewMeeting} 
                className="p-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 transition" 
                title="Cuộc họp mới"
              >
                <Plus className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>

        {/* Main content */}
        <div className="flex-1 overflow-y-auto py-2">
          {renderCollapsedIcons()}
          {sidebarItems.map(item => renderItem(item))}
        </div>

        {/* Footer */}
        {!isCollapsed && (
          <div className="p-3 border-t border-gray-200 bg-white">
            <button 
              onClick={() => router.push('/settings')} 
              className="w-full flex items-center px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
            >
              <Settings className="w-4 h-4 mr-3" />
              <span>Cấu hình</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default Sidebar;