import { useRef, useState } from 'react'

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

export function ConversationItem({ conversation, isActive, onSelect, onArchive, onRename }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const inputRef = useRef(null)

  const title = conversation.title || conversation.last_user_message || 'Новый чат'
  const time = timeAgo(conversation.updated_at)

  function handleMenuToggle(e) {
    e.stopPropagation()
    setMenuOpen(!menuOpen)
  }

  function handleArchive(e) {
    e.stopPropagation()
    setMenuOpen(false)
    onArchive(conversation.id)
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
    if (editTitle.trim()) {
      onRename(conversation.id, editTitle.trim())
    }
    setEditing(false)
  }

  function handleRenameBlur() {
    // Delay so form submit can fire first on mobile
    setTimeout(() => {
      setEditing((prev) => {
        if (prev && editTitle.trim()) {
          onRename(conversation.id, editTitle.trim())
        }
        return false
      })
    }, 150)
  }

  return (
    <div
      onClick={() => onSelect(conversation.id)}
      className={`group relative flex items-center gap-3 px-3 py-2.5 cursor-pointer rounded-lg transition-colors ${
        isActive
          ? 'bg-brand/10 text-brand'
          : 'hover:bg-black/[0.04] dark:hover:bg-white/[0.06] text-fg'
      }`}
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
              onKeyDown={(e) => e.key === 'Escape' && handleRenameCancel(e)}
              className="w-full text-sm bg-transparent border-b border-brand outline-none py-0.5"
              maxLength={100}
            />
          </form>
        ) : (
          <>
            <div className="text-sm font-medium truncate leading-tight">{title}</div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-xs text-fg-muted truncate">
                {conversation.message_count > 0 ? `${conversation.message_count} сообщ.` : ''}
              </span>
              {time && <span className="text-xs text-fg-muted shrink-0">{time}</span>}
            </div>
          </>
        )}
      </div>

      {!editing && (
        <div className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={handleMenuToggle}
            className="p-1 rounded hover:bg-black/[0.06] dark:hover:bg-white/[0.08]"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" className="text-fg-muted">
              <circle cx="8" cy="3" r="1.5" />
              <circle cx="8" cy="8" r="1.5" />
              <circle cx="8" cy="13" r="1.5" />
            </svg>
          </button>

          {menuOpen && (
            <div className="absolute right-2 top-full z-20 mt-1 w-36 rounded-lg border border-black/10 bg-white dark:bg-[#2a2a2a] shadow-lg py-1">
              <button
                onClick={handleStartRename}
                className="w-full text-left px-3 py-1.5 text-sm hover:bg-black/[0.04] dark:hover:bg-white/[0.06]"
              >
                Переименовать
              </button>
              <button
                onClick={handleArchive}
                className="w-full text-left px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
              >
                Удалить
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
