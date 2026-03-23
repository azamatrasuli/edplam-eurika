import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArchiveToast } from '../components/ArchiveToast'
import { ChatWindow } from '../components/ChatWindow'
import { ConversationSidebar } from '../components/ConversationSidebar'
import { EscalationBanner } from '../components/EscalationBanner'
import { MessageInput } from '../components/MessageInput'
import { WelcomeScreen } from '../components/WelcomeScreen'
import { useChat } from '../hooks/useChat'
import { useConversationList } from '../hooks/useConversationList'
import { useOnboarding } from '../hooks/useOnboarding'
import { useTTS } from '../hooks/useTTS'
import { API_BASE_URL } from '../api/client'
import { buildAuthPayload, getAgentRole, getConvFromURL, isManagerMode } from '../lib/authContext'

const EUREKA_AVATAR = '/avatar.webp'

function useTelegramTheme() {
  useEffect(() => {
    try {
      const tg = window.Telegram?.WebApp
      if (!tg) return

      if (tg.colorScheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark')
      }

      const tp = tg.themeParams
      if (tp) {
        const root = document.documentElement.style
        if (tp.bg_color) root.setProperty('--bg-primary', tp.bg_color)
        if (tp.secondary_bg_color) root.setProperty('--bg-secondary', tp.secondary_bg_color)
        if (tp.text_color) root.setProperty('--text-primary', tp.text_color)
        if (tp.hint_color) root.setProperty('--text-secondary', tp.hint_color)
        if (tp.button_color) root.setProperty('--btn-primary', tp.button_color)
        if (tp.button_text_color) root.setProperty('--btn-primary-color', tp.button_text_color)
      }
    } catch {
      // Not in Telegram context — ignore
    }
  }, [])
}

function useTelegramControls() {
  useEffect(() => {
    try {
      const tg = window.Telegram?.WebApp
      if (!tg) return

      // BackButton → close Mini App
      if (tg.BackButton) {
        tg.BackButton.show()
        const handler = () => tg.close()
        tg.BackButton.onClick(handler)
        return () => {
          tg.BackButton.offClick(handler)
          tg.BackButton.hide()
        }
      }
    } catch {
      // ignore
    }
  }, [])
}

function avatarProps(size) {
  return {
    src: EUREKA_AVATAR,
    width: String(size),
    height: String(size),
  }
}

function getActorHints(auth) {
  if (!auth) return { actorId: null, actorPhone: null }

  if (auth.portal_token) {
    try {
      const payload = JSON.parse(atob(auth.portal_token.split('.')[1]))
      return {
        actorId: payload.user_id ? `portal:${payload.user_id}` : null,
        actorPhone: payload.phone || null,
      }
    } catch {
      return { actorId: null, actorPhone: null }
    }
  }

  if (auth.telegram_init_data) {
    try {
      const params = new URLSearchParams(auth.telegram_init_data)
      const user = JSON.parse(params.get('user') || '{}')
      return {
        actorId: user.id ? `telegram:${user.id}` : null,
        actorPhone: null,
      }
    } catch {
      return { actorId: null, actorPhone: null }
    }
  }

  return { actorId: null, actorPhone: null }
}

function triggerHaptic() {
  try {
    window.Telegram?.WebApp?.HapticFeedback?.impactOccurred('light')
  } catch {
    // ignore
  }
}

export function ChatPage() {
  useTelegramTheme()
  useTelegramControls()
  const auth = useMemo(() => buildAuthPayload(), [])
  const agentRole = useMemo(() => getAgentRole(), [])
  const { actorId, actorPhone } = useMemo(() => getActorHints(auth), [auth])
  const convFromURL = useMemo(() => getConvFromURL(), [])
  const managerMode = useMemo(() => isManagerMode(), [])

  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [handbackLoading, setHandbackLoading] = useState(false)
  const [managerActive, setManagerActive] = useState(managerMode) // true = manager controls chat

  // Error toast for sidebar operations
  const [errorToast, setErrorToast] = useState('')
  const errorToastTimerRef = useRef(null)
  const showErrorToast = useCallback((msg) => {
    setErrorToast(msg)
    clearTimeout(errorToastTimerRef.current)
    errorToastTimerRef.current = setTimeout(() => setErrorToast(''), 5000)
  }, [])

  const onboarding = useOnboarding(auth, actorId, actorPhone)
  const chat = useChat(auth, agentRole, onboarding.isComplete, { initialConvId: convFromURL })
  const convList = useConversationList(auth, agentRole, { onError: showErrorToast })
  const tts = useTTS(auth, { onError: showErrorToast })

  // Wire SSE callbacks → sidebar (stable refs, runs once)
  useEffect(() => {
    chat.onTitleUpdate((conversationId, title) => {
      convList.updateTitle(conversationId, title)
    })
    chat.onBumpConversation((conversationId, userText) => {
      convList.bumpConversation(conversationId, userText)
    })
  }, [chat.onTitleUpdate, chat.onBumpConversation, convList.updateTitle, convList.bumpConversation])

  // Sync active conversation in sidebar
  const setActiveIdRef = useRef(convList.setActiveId)
  setActiveIdRef.current = convList.setActiveId
  useEffect(() => {
    if (chat.conversationId) {
      setActiveIdRef.current(chat.conversationId)
    }
  }, [chat.conversationId])

  const handleSelectConversation = useCallback((convId) => {
    tts.stop()
    chat.switchConversation(convId)
    convList.setActiveId(convId)
    setSidebarOpen(false)
  }, [chat, convList, tts])

  const newChatCooldownRef = useRef(0)
  const handleNewChat = useCallback(async () => {
    if (isCreating) return
    // Cooldown: prevent rapid-fire chat creation (3 sec)
    const now = Date.now()
    if (now - newChatCooldownRef.current < 3000) return
    newChatCooldownRef.current = now

    setIsCreating(true)
    try {
      const data = await chat.startNewChat()
      if (data) {
        // Only add to sidebar if not already there (backend may reuse empty chat)
        const exists = convList.conversations.some((c) => c.id === data.conversation_id)
        if (!exists) {
          convList.addConversation({
            id: data.conversation_id,
            title: null,
            agent_role: agentRole,
            message_count: 0,
            last_user_message: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          })
        }
        convList.setActiveId(data.conversation_id)
        setSidebarOpen(false)
      }
    } finally {
      setIsCreating(false)
    }
  }, [chat, convList, agentRole, isCreating])

  // Auto-switch to next conversation when active one is archived/deleted
  const switchToNext = useCallback((removedId) => {
    const remaining = convList.conversations.filter((c) => c.id !== removedId)
    if (remaining.length > 0) {
      chat.switchConversation(remaining[0].id)
      convList.setActiveId(remaining[0].id)
    } else {
      handleNewChat()
    }
  }, [chat, convList, handleNewChat])

  const handleArchive = useCallback(async (convId) => {
    const isActive = convId === convList.activeId
    await convList.archive(convId)
    if (isActive) switchToNext(convId)
  }, [convList, switchToNext])

  const handleDelete = useCallback(async (convId) => {
    const isActive = convId === convList.activeId
    await convList.deleteConversation(convId)
    if (isActive) switchToNext(convId)
  }, [convList, switchToNext])

  const handleUndoArchive = useCallback(async () => {
    const toast = convList.archiveToast
    await convList.undoArchive()
    if (toast?.wasActive) {
      chat.switchConversation(toast.id)
      convList.setActiveId(toast.id)
    }
  }, [chat, convList])

  const isSupport = agentRole === 'support'
  const isTeacher = agentRole === 'teacher'
  const headerSubtitle = isTeacher
    ? 'Виртуальный учитель EdPalm'
    : isSupport
      ? 'Служба поддержки EdPalm'
      : 'AI менеджер EdPalm'
  const welcomeText = isTeacher
    ? 'Виртуальный учитель EdPalm. Помогу разобраться в любом предмете и подготовиться к аттестации.'
    : isSupport
      ? 'Служба поддержки EdPalm. Помогу с вопросами по платформе, документам и оплате.'
      : 'Виртуальный менеджер EdPalm. Помогу подобрать обучение и отвечу по программам.'

  // Phase 1: Loading
  if (onboarding.isChecking) {
    return <WelcomeScreen subtitle={welcomeText} avatarProps={avatarProps(88)} error={onboarding.error} />
  }

  // Phase 2: Chat not started
  if (!chat.started) {
    return <WelcomeScreen subtitle={welcomeText} avatarProps={avatarProps(88)} error={chat.error} />
  }

  function handleSend(text) {
    triggerHaptic()
    chat.sendMessage(text)
  }

  return (
    <main className="w-full h-dvh flex overflow-hidden">
      {/* Conversation Sidebar — hidden in manager mode */}
      {!managerMode && <ConversationSidebar
        conversations={convList.conversations}
        activeId={convList.activeId}
        loading={convList.loading}
        searchQuery={convList.searchQuery}
        hasMore={convList.hasMore}
        isOpen={sidebarOpen}
        isCreating={isCreating}
        newChatDisabled={(() => {
          const ac = convList.conversations.find((c) => c.id === convList.activeId)
          return !!(ac && (!ac.message_count || ac.message_count <= 1))
        })()}
        onClose={() => setSidebarOpen(false)}
        onSelect={handleSelectConversation}
        onNewChat={handleNewChat}
        onArchive={handleArchive}
        onDelete={handleDelete}
        onRename={convList.rename}
        onSearch={convList.search}
        onLoadMore={convList.loadMore}
        archivedConvs={convList.archivedConvs}
        archivedLoading={convList.archivedLoading}
        onLoadArchived={convList.loadArchived}
        onUnarchive={convList.unarchiveFromList}
      />}

      {/* Chat area */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <header className="flex items-center gap-3 px-5 py-2.5 pt-[calc(10px+env(safe-area-inset-top,0px))] bg-header backdrop-blur-[16px] border-b border-header-border shrink-0 z-10 max-sm:px-4">
          {/* Hamburger menu for mobile */}
          <button
            onClick={() => setSidebarOpen(true)}
            className="sm:hidden p-2 -ml-1 rounded-lg hover:bg-inset transition-colors"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="5" x2="17" y2="5" />
              <line x1="3" y1="10" x2="17" y2="10" />
              <line x1="3" y1="15" x2="17" y2="15" />
            </svg>
          </button>

          <img className="w-10 h-10 rounded-full object-cover shrink-0 bg-surface-alt ring-1 ring-border-subtle" alt="Эврика" {...avatarProps(40)} />
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold leading-tight text-fg tracking-tight">Эврика</span>
              <span className="w-1.5 h-1.5 rounded-full bg-status shrink-0 animate-[status-pulse_2s_infinite_ease-in-out]" />
              {managerMode && <span className="text-[11px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 font-medium">Менеджер</span>}
            </div>
            <span className="text-[13px] text-fg-tertiary leading-tight">{managerMode ? 'Просмотр диалога клиента' : headerSubtitle}</span>
          </div>
          {managerMode && convFromURL && (
            <button
              onClick={() => {
                if (handbackLoading) return
                setHandbackLoading(true)
                const key = new URLSearchParams(window.location.hash.split('?')[1] || '').get('manager_key')
                const action = managerActive ? 'handback' : 'connect'
                fetch(`${API_BASE_URL}/api/v1/manager/${action}/${convFromURL}?key=${key}`)
                  .then(() => setManagerActive(!managerActive))
                  .catch(() => {})
                  .finally(() => {
                    setTimeout(() => setHandbackLoading(false), 2000)
                  })
              }}
              disabled={handbackLoading}
              className={`ml-auto px-3 py-1.5 text-xs font-medium rounded-lg transition-colors shrink-0 ${
                handbackLoading
                  ? 'bg-gray-600/20 text-gray-500 cursor-not-allowed'
                  : managerActive
                    ? 'bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 cursor-pointer'
                    : 'bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600/30 cursor-pointer'
              }`}
            >
              {handbackLoading
                ? (managerActive ? '⏳ Возвращаю...' : '⏳ Подключаюсь...')
                : (managerActive ? '🤖 Вернуть ИИ' : '💬 Подключиться')
              }
            </button>
          )}
        </header>

        <EscalationBanner active={chat.escalated} reason={chat.escalationReason} />

        <ChatWindow
          messages={chat.messages}
          avatarProps={avatarProps(28)}
          typing={chat.typing}
          toolStatus={chat.toolStatus}
          loading={chat.loading}
          onButtonClick={(value) => handleSend(value)}
          onTTSPlay={tts.play}
          ttsPlayingId={tts.playingId}
          ttsState={tts.ttsState}
          isManagerView={managerMode}
        />

        {chat.error && (
          <div className="error-enter px-4 py-3 mx-5 rounded-xl bg-error-bg text-error border border-error-border text-sm leading-normal shrink-0 max-sm:mx-3">
            {chat.error}
          </div>
        )}

        <div className="shrink-0 px-5 pt-3 pb-[calc(16px+env(safe-area-inset-bottom,0px))] bg-input-area backdrop-blur-[16px] border-t border-input-area-border max-sm:px-3 max-sm:pt-2.5">
          <MessageInput disabled={chat.typing || chat.escalated || chat.loading} onSend={handleSend} auth={auth} onTypingStart={chat.clearSuggestions} isManagerView={managerMode} />
        </div>
      </div>

      {/* Archive undo toast */}
      <ArchiveToast
        visible={!!convList.archiveToast}
        title={convList.archiveToast?.title}
        onUndo={handleUndoArchive}
        onDismiss={convList.dismissArchiveToast}
      />

      {/* Error toast for sidebar operations */}
      {errorToast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 error-enter px-4 py-2.5 rounded-xl bg-error-bg text-error border border-error-border text-sm shadow-lg max-w-[90vw]">
          <div className="flex items-center gap-2">
            <span>{errorToast}</span>
            <button
              onClick={() => setErrorToast('')}
              className="shrink-0 p-0.5 rounded hover:bg-error/10 transition-colors border-none bg-transparent text-error cursor-pointer text-base leading-none"
            >
              &times;
            </button>
          </div>
        </div>
      )}
    </main>
  )
}
