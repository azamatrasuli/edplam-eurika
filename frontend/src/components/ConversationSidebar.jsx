import { useEffect, useRef, useState } from 'react'
import { ConversationItem } from './ConversationItem'

function SidebarSpinner() {
  return (
    <div className="flex justify-center py-6">
      <span className="w-5 h-5 border-2 border-brand/20 border-t-brand rounded-full animate-spin" />
    </div>
  )
}

const COLLAPSED_KEY = 'eurika_sidebar_collapsed'

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
  archivedConvs,
  archivedLoading,
  onLoadArchived,
  onUnarchive,
}) {
  const [localQuery, setLocalQuery] = useState(searchQuery || '')
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSED_KEY) === '1')
  const [showArchived, setShowArchived] = useState(false)
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

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev
      localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0')
      return next
    })
  }

  function toggleArchived() {
    if (!showArchived && onLoadArchived) {
      onLoadArchived()
    }
    setShowArchived((prev) => !prev)
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

  // Collapsed sidebar (desktop only)
  const collapsedBar = (
    <div data-sidebar className="flex flex-col items-center h-full py-3 gap-3 bg-white dark:bg-[#1a1a1a] border-r border-black/[0.06] dark:border-white/[0.06]">
      <button
        onClick={toggleCollapsed}
        className="p-2 rounded-lg hover:bg-black/[0.06] dark:hover:bg-white/[0.08] transition-colors"
        title="Развернуть панель"
      >
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <polyline points="6 4 12 9 6 14" />
        </svg>
      </button>
      <button
        onClick={onNewChat}
        disabled={isCreating}
        className="p-2 rounded-lg bg-brand text-white hover:bg-brand-hover transition-colors active:scale-95 disabled:opacity-50"
        title="Новый чат"
      >
        {isCreating ? (
          <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin block" />
        ) : (
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="9" y1="3" x2="9" y2="15" />
            <line x1="3" y1="9" x2="15" y2="9" />
          </svg>
        )}
      </button>
    </div>
  )

  const sidebarContent = (
    <div data-sidebar className="flex flex-col h-full bg-white dark:bg-[#1a1a1a] border-r border-black/[0.06] dark:border-white/[0.06]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-black/[0.06] dark:border-white/[0.06]">
        <span className="text-sm font-semibold text-fg">Чаты</span>
        <div className="flex items-center gap-1.5">
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
          {/* Collapse (desktop) */}
          <button
            onClick={toggleCollapsed}
            className="hidden sm:flex p-1.5 rounded-lg hover:bg-black/[0.06] dark:hover:bg-white/[0.08] transition-colors"
            title="Свернуть панель"
          >
            <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <polyline points="12 4 6 9 12 14" />
            </svg>
          </button>
          {/* Close (mobile) */}
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
        {loading && conversations.length === 0 && (
          <SidebarSpinner />
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

        {loading && conversations.length > 0 && (
          <SidebarSpinner />
        )}

        {/* Archived section */}
        {!localQuery && (
          <div className="mt-2 pt-2 border-t border-black/[0.06] dark:border-white/[0.06]">
            <button
              onClick={toggleArchived}
              className="flex items-center gap-2 w-full px-3 py-2 text-xs font-medium text-fg-muted hover:text-fg rounded-lg hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
                <polyline points="21 8 21 21 3 21 3 8" />
                <rect x="1" y="3" width="22" height="5" />
                <line x1="10" y1="12" x2="14" y2="12" />
              </svg>
              Архив
              <svg
                width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                className={`ml-auto transition-transform duration-200 ${showArchived ? 'rotate-180' : ''}`}
              >
                <polyline points="3 4 6 7 9 4" />
              </svg>
            </button>

            {showArchived && (
              <div className="mt-1">
                {archivedLoading && <SidebarSpinner />}
                {!archivedLoading && archivedConvs.length === 0 && (
                  <div className="text-center text-xs text-fg-muted py-4">Нет архивных чатов</div>
                )}
                {(archivedConvs || []).map((conv) => (
                  <div key={conv.id} className="opacity-60">
                    <ConversationItem
                      conversation={conv}
                      isActive={false}
                      onSelect={onSelect}
                      onArchive={onUnarchive || onArchive}
                      onDelete={onDelete}
                      onRename={onRename}
                      archiveLabel="Восстановить"
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )

  return (
    <>
      {/* Desktop: collapsible sidebar */}
      <div
        className="hidden sm:block h-full shrink-0 transition-[width] duration-200 ease-out"
        style={{ width: collapsed ? 52 : 280 }}
      >
        {collapsed ? collapsedBar : sidebarContent}
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
