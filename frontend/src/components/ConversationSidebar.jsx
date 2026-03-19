import { useEffect, useRef, useState } from 'react'
import { ConversationItem } from './ConversationItem'

function SidebarSkeleton({ count = 4 }) {
  return Array.from({ length: count }, (_, i) => (
    <div key={i} className="flex items-center gap-3 px-3 py-2.5 animate-[fade-in_0.2s_ease]">
      <div className="flex-1 min-w-0 space-y-2">
        <div className="skeleton h-3.5 rounded" style={{ width: `${60 + Math.random() * 30}%` }} />
        <div className="skeleton h-2.5 rounded" style={{ width: `${30 + Math.random() * 20}%` }} />
      </div>
    </div>
  ))
}

export function ConversationSidebar({
  conversations,
  activeId,
  loading,
  searchQuery,
  onSelect,
  onNewChat,
  onArchive,
  onDelete,
  onRename,
  onSearch,
  onLoadMore,
  hasMore,
  isOpen,
  isCreating,
  onClose,
}) {
  const [localQuery, setLocalQuery] = useState(searchQuery || '')
  const searchTimerRef = useRef(null)
  const listRef = useRef(null)

  useEffect(() => {
    setLocalQuery(searchQuery || '')
  }, [searchQuery])

  function handleSearchChange(e) {
    const q = e.target.value
    setLocalQuery(q)
    clearTimeout(searchTimerRef.current)
    searchTimerRef.current = setTimeout(() => onSearch(q), 400)
  }

  function handleScroll() {
    if (!listRef.current || !hasMore) return
    const { scrollTop, scrollHeight, clientHeight } = listRef.current
    if (scrollHeight - scrollTop - clientHeight < 100) {
      onLoadMore()
    }
  }

  // Close menu when clicking outside on mobile
  useEffect(() => {
    if (!isOpen) return
    function handleClickOutside(e) {
      if (e.target.closest('[data-sidebar]')) return
      onClose()
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen, onClose])

  const sidebarContent = (
    <div data-sidebar className="flex flex-col h-full bg-white dark:bg-[#1a1a1a] border-r border-black/[0.06] dark:border-white/[0.06]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-black/[0.06] dark:border-white/[0.06]">
        <span className="text-sm font-semibold text-fg">Чаты</span>
        <div className="flex items-center gap-2">
          <button
            onClick={onNewChat}
            disabled={isCreating}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-brand rounded-lg hover:bg-brand-hover transition-all active:scale-95 disabled:opacity-50 disabled:cursor-default"
          >
            {isCreating ? (
              <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="7" y1="2" x2="7" y2="12" />
                <line x1="2" y1="7" x2="12" y2="7" />
              </svg>
            )}
            Новый
          </button>
          {/* Close button (mobile only) */}
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-black/[0.06] sm:hidden transition-colors"
          >
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="4" y1="4" x2="14" y2="14" />
              <line x1="14" y1="4" x2="4" y2="14" />
            </svg>
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="px-3 py-2">
        <input
          type="text"
          value={localQuery}
          onChange={handleSearchChange}
          placeholder="Поиск чатов..."
          className="w-full px-3 py-1.5 text-sm bg-black/[0.03] dark:bg-white/[0.06] rounded-lg border-0 outline-none focus:ring-1 focus:ring-brand placeholder:text-fg-muted transition-shadow"
        />
      </div>

      {/* Conversation list */}
      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-2 pb-2"
      >
        {/* Initial loading — show skeletons */}
        {loading && conversations.length === 0 && (
          <SidebarSkeleton count={5} />
        )}

        {conversations.length === 0 && !loading && (
          <div className="text-center text-sm text-fg-muted py-8 animate-[fade-in_0.3s_ease]">
            {localQuery ? 'Ничего не найдено' : 'Нет чатов'}
          </div>
        )}

        {conversations.map((conv) => (
          <ConversationItem
            key={conv.id}
            conversation={conv}
            isActive={conv.id === activeId}
            onSelect={onSelect}
            onArchive={onArchive}
            onDelete={onDelete}
            onRename={onRename}
          />
        ))}

        {/* Load more — inline skeleton */}
        {loading && conversations.length > 0 && (
          <SidebarSkeleton count={2} />
        )}
      </div>
    </div>
  )

  return (
    <>
      {/* Desktop: fixed sidebar */}
      <div className="hidden sm:block w-[280px] h-full shrink-0">
        {sidebarContent}
      </div>

      {/* Mobile: slide-out drawer */}
      {isOpen && (
        <div className="sm:hidden fixed inset-0 z-50 flex">
          <div className="absolute inset-0 bg-black/30 animate-[fade-in_0.15s_ease]" onClick={onClose} />
          <div className="relative w-[280px] h-full animate-slide-in">
            {sidebarContent}
          </div>
        </div>
      )}
    </>
  )
}
