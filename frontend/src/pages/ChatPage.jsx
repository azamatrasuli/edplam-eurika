import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChatWindow } from '../components/ChatWindow'
import { ConversationSidebar } from '../components/ConversationSidebar'
import { EscalationBanner } from '../components/EscalationBanner'
import { MessageInput } from '../components/MessageInput'
// SuggestionChips disabled — pure live conversation
// import { SuggestionChips } from '../components/SuggestionChips'
import { WelcomeScreen } from '../components/WelcomeScreen'
import { useChat } from '../hooks/useChat'
import { useConversationList } from '../hooks/useConversationList'
import { useOnboarding } from '../hooks/useOnboarding'
import { buildAuthPayload, getAgentRole } from '../lib/authContext'

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

  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [isCreating, setIsCreating] = useState(false)

  const onboarding = useOnboarding(auth, actorId, actorPhone)
  const chat = useChat(auth, agentRole, onboarding.isComplete)
  const convList = useConversationList(auth, agentRole)

  // Sync active conversation in sidebar
  const setActiveIdRef = useRef(convList.setActiveId)
  setActiveIdRef.current = convList.setActiveId
  useEffect(() => {
    if (chat.conversationId) {
      setActiveIdRef.current(chat.conversationId)
    }
  }, [chat.conversationId])

  const handleSelectConversation = useCallback((convId) => {
    chat.switchConversation(convId)
    convList.setActiveId(convId)
    setSidebarOpen(false)
  }, [chat, convList])

  const handleNewChat = useCallback(async () => {
    if (isCreating) return
    setIsCreating(true)
    try {
      const data = await chat.startNewChat()
      if (data) {
        convList.addConversation({
          id: data.conversation_id,
          title: null,
          agent_role: agentRole,
          message_count: 0,
          last_user_message: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        })
        setSidebarOpen(false)
      }
    } finally {
      setIsCreating(false)
    }
  }, [chat, convList, agentRole, isCreating])

  if (!auth) {
    return (
      <div className="px-4 py-3 mx-5 rounded-xl bg-error-bg text-error border border-error-border text-sm leading-normal shrink-0">
        Не найден токен входа. Откройте чат из портала, Telegram или внешней ссылки.
      </div>
    )
  }

  const isSupport = agentRole === 'support'
  const headerSubtitle = isSupport ? 'Служба поддержки EdPalm' : 'AI менеджер EdPalm'
  const welcomeText = isSupport
    ? 'Служба поддержки EdPalm. Помогу с вопросами по платформе, документам и оплате.'
    : 'Виртуальный менеджер EdPalm. Помогу подобрать обучение и отвечу по программам.'

  // Phase 1: Loading
  if (onboarding.isChecking) {
    return <WelcomeScreen subtitle={welcomeText} avatarProps={avatarProps(88)} error={onboarding.error} />
  }

  // Phase 2: Chat
  if (!chat.started) {
    return <WelcomeScreen subtitle={welcomeText} avatarProps={avatarProps(88)} error={chat.error} />
  }

  function handleSend(text) {
    triggerHaptic()
    chat.sendMessage(text)
  }

  return (
    <main className="w-full h-dvh flex overflow-hidden">
      {/* Conversation Sidebar */}
      <ConversationSidebar
        conversations={convList.conversations}
        activeId={convList.activeId}
        loading={convList.loading}
        searchQuery={convList.searchQuery}
        hasMore={convList.hasMore}
        isOpen={sidebarOpen}
        isCreating={isCreating}
        onClose={() => setSidebarOpen(false)}
        onSelect={handleSelectConversation}
        onNewChat={handleNewChat}
        onArchive={convList.archive}
        onRename={convList.rename}
        onSearch={convList.search}
        onLoadMore={convList.loadMore}
      />

      {/* Chat area */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <header className="flex items-center gap-3 px-5 py-3 pt-[calc(12px+env(safe-area-inset-top,0px))] bg-header backdrop-blur-[16px] border-b border-header-border shrink-0 z-10 max-sm:px-4">
          {/* Hamburger menu for mobile */}
          <button
            onClick={() => setSidebarOpen(true)}
            className="sm:hidden p-1.5 -ml-1 rounded-lg hover:bg-black/[0.06] dark:hover:bg-white/[0.08]"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="5" x2="17" y2="5" />
              <line x1="3" y1="10" x2="17" y2="10" />
              <line x1="3" y1="15" x2="17" y2="15" />
            </svg>
          </button>

          <img className="w-10 h-10 rounded-full object-cover shrink-0 bg-surface-alt" alt="Эврика" {...avatarProps(40)} />
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold leading-tight text-fg">Эврика</span>
              <span className="w-2 h-2 rounded-full bg-status shrink-0 animate-[status-pulse_2s_infinite_ease-in-out]" />
            </div>
            <span className="text-[13px] text-fg-muted leading-tight">{headerSubtitle}</span>
          </div>
        </header>

        <EscalationBanner active={chat.escalated} reason={chat.escalationReason} />

        <ChatWindow
          messages={chat.messages}
          avatarProps={avatarProps(28)}
          typing={chat.typing}
          onButtonClick={(value) => handleSend(value)}
        />

        {/* SuggestionChips disabled — pure live conversation */}

        {chat.error && (
          <div className="px-4 py-3 mx-5 rounded-xl bg-error-bg text-error border border-error-border text-sm leading-normal shrink-0 max-sm:mx-3">
            {chat.error}
          </div>
        )}

        <div className="shrink-0 px-5 pt-3 pb-[calc(16px+env(safe-area-inset-bottom,0px))] bg-input-area backdrop-blur-[16px] border-t border-input-area-border max-sm:px-3 max-sm:pt-2.5">
          <MessageInput disabled={chat.typing || chat.escalated} onSend={handleSend} auth={auth} onTypingStart={chat.clearSuggestions} />
        </div>
      </div>
    </main>
  )
}
