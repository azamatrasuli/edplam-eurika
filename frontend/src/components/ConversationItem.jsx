import { useCallback, useEffect, useRef, useState } from 'react'

function timeAgo(dateStr) {
  if (!dateStr) return ''
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'только что'
  if (mins < 60) return `${mins} мин`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} ч`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} д`
  return new Date(dateStr).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

const SWIPE_THRESHOLD = 80
const SWIPE_AUTO_ARCHIVE = 160

function ArchiveIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="21 8 21 21 3 21 3 8" />
      <rect x="1" y="3" width="22" height="5" />
      <line x1="10" y1="12" x2="14" y2="12" />
    </svg>
  )
}

export function ConversationItem({ conversation, isActive, onSelect, onArchive, onDelete, onRename, archiveLabel }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [titleFlash, setTitleFlash] = useState(false)
  const [swipeX, setSwipeX] = useState(0)
  const [swiping, setSwiping] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const inputRef = useRef(null)
  const menuRef = useRef(null)
  const prevTitleRef = useRef(conversation.title)
  const touchRef = useRef({ startX: 0, startY: 0, started: false, locked: false })

  const title = conversation.title || conversation.last_user_message || 'Новый чат'
  const time = timeAgo(conversation.archived_at ? conversation.created_at : conversation.updated_at)

  // Flash animation when title changes reactively
  useEffect(() => {
    if (prevTitleRef.current !== conversation.title && conversation.title) {
      setTitleFlash(true)
      const timer = setTimeout(() => setTitleFlash(false), 600)
      prevTitleRef.current = conversation.title
      return () => clearTimeout(timer)
    }
    prevTitleRef.current = conversation.title
  }, [conversation.title])

  // Close menu on click outside
  useEffect(() => {
    if (!menuOpen) return
    function handleClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [menuOpen])

  // --- Swipe gesture (mobile) ---
  const handleTouchStart = useCallback((e) => {
    if (editing || menuOpen) return
    const touch = e.touches[0]
    touchRef.current = { startX: touch.clientX, startY: touch.clientY, started: true, locked: false }
  }, [editing, menuOpen])

  const handleTouchMove = useCallback((e) => {
    const t = touchRef.current
    if (!t.started) return
    const touch = e.touches[0]
    const dx = touch.clientX - t.startX
    const dy = touch.clientY - t.startY

    if (!t.locked) {
      if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return
      t.locked = true
      if (Math.abs(dy) > Math.abs(dx)) {
        t.started = false
        return
      }
    }

    if (dx >= 0) {
      setSwipeX(0)
      setSwiping(false)
      return
    }

    e.preventDefault()
    setSwipeX(Math.max(dx, -SWIPE_AUTO_ARCHIVE - 20))
    setSwiping(true)
  }, [])

  const handleTouchEnd = useCallback(() => {
    touchRef.current.started = false

    if (Math.abs(swipeX) >= SWIPE_AUTO_ARCHIVE) {
      setSwipeX(-300)
      setTimeout(() => onArchive(conversation.id), 200)
    } else if (Math.abs(swipeX) >= SWIPE_THRESHOLD) {
      setSwipeX(-SWIPE_THRESHOLD)
    } else {
      setSwipeX(0)
    }
    setSwiping(false)
  }, [swipeX, conversation.id, onArchive])

  function handleSwipeArchive(e) {
    e.stopPropagation()
    setSwipeX(-300)
    setTimeout(() => onArchive(conversation.id), 200)
  }

  function handleSelect() {
    if (Math.abs(swipeX) > 10) { setSwipeX(0); return }
    onSelect(conversation.id)
  }

  function handleMenuToggle(e) {
    e.stopPropagation()
    setMenuOpen(!menuOpen)
  }

  function handleArchive(e) {
    e.stopPropagation()
    setMenuOpen(false)
    onArchive(conversation.id)
  }

  function handleDeleteClick(e) {
    e.stopPropagation()
    setMenuOpen(false)
    setConfirmDelete(true)
  }

  function handleConfirmDelete(e) {
    e.stopPropagation()
    setConfirmDelete(false)
    onDelete(conversation.id)
  }

  function handleCancelDelete(e) {
    e.stopPropagation()
    setConfirmDelete(false)
  }

  function handleStartRename(e) {
    e.stopPropagation()
    setMenuOpen(false)
    setEditTitle(title)
    setEditing(true)
    setTimeout(() => inputRef.current?.focus(), 50)
  }

  function handleRenameSubmit(e) {
    e.preventDefault()
    e.stopPropagation()
    if (editTitle.trim()) onRename(conversation.id, editTitle.trim())
    setEditing(false)
  }

  function handleRenameBlur() {
    setTimeout(() => {
      setEditing((prev) => {
        if (prev && editTitle.trim()) onRename(conversation.id, editTitle.trim())
        return false
      })
    }, 150)
  }

  const pastThreshold = Math.abs(swipeX) >= SWIPE_THRESHOLD

  return (
    <div className="relative rounded-lg">
      {/* Swipe layer — overflow-hidden isolates only the slide */}
      <div className="relative overflow-hidden rounded-lg">
        {/* Green archive strip behind */}
        {swipeX < 0 && (
          <div
            className={`absolute inset-y-0 right-0 flex items-center justify-center transition-colors duration-150 ${
              pastThreshold ? 'bg-brand' : 'bg-brand/60'
            }`}
            style={{ width: Math.abs(swipeX) }}
          >
            <button onClick={handleSwipeArchive} className="flex flex-col items-center gap-0.5 px-3 text-white">
              <ArchiveIcon size={18} />
              <span className="text-[10px] font-medium">Архив</span>
            </button>
          </div>
        )}

        {/* Foreground item */}
        <div
          onClick={handleSelect}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
          className={`group relative flex items-center gap-3 px-3 py-2.5 cursor-pointer rounded-lg ${
            isActive
              ? 'bg-brand/10 text-brand'
              : 'bg-white dark:bg-[#1a1a1a] hover:bg-black/[0.04] dark:hover:bg-white/[0.06] text-fg'
          }`}
          style={{
            transform: swipeX ? `translateX(${swipeX}px)` : undefined,
            transition: swiping ? 'none' : 'transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
          }}
        >
          <div className="flex-1 min-w-0">
            {editing ? (
              <form onSubmit={handleRenameSubmit} className="flex gap-1">
                <input
                  ref={inputRef}
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  onBlur={handleRenameBlur}
                  onKeyDown={(e) => e.key === 'Escape' && setEditing(false)}
                  className="w-full text-sm bg-transparent border-b border-brand outline-none py-0.5"
                  maxLength={100}
                />
              </form>
            ) : (
              <>
                <div className={`text-sm font-medium truncate leading-tight transition-all duration-300 ${
                  titleFlash ? 'text-brand scale-[1.01]' : ''
                }`}>
                  {title}
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xs text-fg-muted truncate">
                    {conversation.message_count > 0 ? `${conversation.message_count} сообщ.` : ''}
                  </span>
                  {time && <span className="text-xs text-fg-muted shrink-0">{time}</span>}
                </div>
              </>
            )}
          </div>

          {/* Three-dot trigger — inside the sliding item */}
          {!editing && (
            <button
              onClick={handleMenuToggle}
              className="shrink-0 p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-black/[0.06] dark:hover:bg-white/[0.08] transition-all"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" className="text-fg-muted">
                <circle cx="8" cy="3" r="1.5" />
                <circle cx="8" cy="8" r="1.5" />
                <circle cx="8" cy="13" r="1.5" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Dropdown menu — OUTSIDE overflow-hidden so it's never clipped */}
      {menuOpen && (
        <div
          ref={menuRef}
          className="absolute right-2 top-full z-50 mt-1 w-44 rounded-lg border border-black/10 dark:border-white/10 bg-white dark:bg-[#2a2a2a] shadow-lg py-1 animate-[fade-in_0.12s_ease]"
        >
          <button
            onClick={handleStartRename}
            className="flex items-center gap-2.5 w-full text-left px-3 py-2 text-sm hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition-colors"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-fg-muted shrink-0">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
            Переименовать
          </button>
          <button
            onClick={handleArchive}
            className="flex items-center gap-2.5 w-full text-left px-3 py-2 text-sm hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition-colors"
          >
            <ArchiveIcon size={14} />
            {archiveLabel || 'Архивировать'}
          </button>
          <div className="my-0.5 mx-2 border-t border-black/[0.06] dark:border-white/[0.06]" />
          <button
            onClick={handleDeleteClick}
            className="flex items-center gap-2.5 w-full text-left px-3 py-2 text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
            Удалить
          </button>
        </div>
      )}

      {/* Delete confirmation — also outside overflow-hidden */}
      {confirmDelete && (
        <div
          className="absolute inset-0 z-40 flex items-center justify-center rounded-lg bg-white/95 dark:bg-[#1a1a1a]/95 backdrop-blur-sm animate-[fade-in_0.15s_ease]"
          onClick={handleCancelDelete}
        >
          <div className="flex flex-col items-center gap-2 px-3" onClick={(e) => e.stopPropagation()}>
            <span className="text-xs text-fg-muted text-center">Удалить навсегда?</span>
            <div className="flex gap-2">
              <button
                onClick={handleCancelDelete}
                className="px-3 py-1 text-xs font-medium rounded-lg bg-black/[0.05] dark:bg-white/[0.08] hover:bg-black/[0.08] dark:hover:bg-white/[0.12] transition-colors"
              >
                Отмена
              </button>
              <button
                onClick={handleConfirmDelete}
                className="px-3 py-1 text-xs font-medium text-white bg-red-500 rounded-lg hover:bg-red-600 transition-colors active:scale-95"
              >
                Удалить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
