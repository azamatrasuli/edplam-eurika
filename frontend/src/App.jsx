import { useEffect, useMemo } from 'react'
import { ChatWindow } from './components/ChatWindow'
import { EscalationBanner } from './components/EscalationBanner'
import { MessageInput } from './components/MessageInput'
import { WelcomeScreen } from './components/WelcomeScreen'
import { useChat } from './hooks/useChat'
import { useOnboarding } from './hooks/useOnboarding'
import { buildAuthPayload, getAgentRole } from './lib/authContext'

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

function avatarProps(size) {
  return {
    src: EUREKA_AVATAR,
    width: String(size),
    height: String(size),
  }
}

// Extract actor_id and phone from auth payload for onboarding
function getActorHints(auth) {
  if (!auth) return { actorId: null, actorPhone: null }

  // For portal JWT: parse to get user_id and phone
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

  // For Telegram: parse initData to get user.id
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

  // External: no hints available
  return { actorId: null, actorPhone: null }
}

export function App() {
  useTelegramTheme()
  const auth = useMemo(() => buildAuthPayload(), [])
  const agentRole = useMemo(() => getAgentRole(), [])
  const { actorId, actorPhone } = useMemo(() => getActorHints(auth), [auth])

  const onboarding = useOnboarding(auth, actorId, actorPhone)
  const chat = useChat(auth, agentRole, onboarding.isComplete)

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

  // Phase 1: Loading (checking profile)
  if (onboarding.isChecking) {
    return <WelcomeScreen subtitle={welcomeText} avatarProps={avatarProps(88)} error={onboarding.error} />
  }

  // Phase 2: Onboarding (not complete yet)
  if (!onboarding.isComplete) {
    return (
      <main className="w-full h-dvh flex flex-col overflow-hidden">
        <header className="flex items-center gap-3 px-5 py-3 pt-[calc(12px+env(safe-area-inset-top,0px))] bg-header backdrop-blur-[16px] border-b border-header-border shrink-0 z-10 max-sm:px-4">
          <img
            className="w-10 h-10 rounded-full object-cover shrink-0 bg-surface-alt"
            alt="Эврика"
            {...avatarProps(40)}
          />
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold leading-tight text-fg">Эврика</span>
              <span className="w-2 h-2 rounded-full bg-status shrink-0 animate-[status-pulse_2s_infinite_ease-in-out]" />
            </div>
            <span className="text-[13px] text-fg-muted leading-tight">{headerSubtitle}</span>
          </div>
        </header>

        <ChatWindow
          messages={onboarding.messages}
          avatarProps={avatarProps(28)}
          typing={false}
          onButtonClick={onboarding.handleButtonClick}
          onFormSubmit={onboarding.handleFormSubmit}
        />

        {onboarding.error && (
          <div className="px-4 py-3 mx-5 rounded-xl bg-error-bg text-error border border-error-border text-sm leading-normal shrink-0 max-sm:mx-3">
            {onboarding.error}
          </div>
        )}

        {/* No MessageInput during onboarding — interaction through buttons/forms */}
        <div className="shrink-0 px-5 pt-3 pb-4 bg-input-area backdrop-blur-[16px] border-t border-input-area-border max-sm:px-3 max-sm:pt-2.5 max-sm:pb-3.5">
          <div className="text-center text-[13px] text-fg-muted py-1">
            Заполните данные выше для продолжения
          </div>
        </div>
      </main>
    )
  }

  // Phase 3: Chat (onboarding complete)
  if (!chat.started) {
    return <WelcomeScreen subtitle={welcomeText} avatarProps={avatarProps(88)} error={chat.error} />
  }

  return (
    <main className="w-full h-dvh flex flex-col overflow-hidden">
      <header className="flex items-center gap-3 px-5 py-3 pt-[calc(12px+env(safe-area-inset-top,0px))] bg-header backdrop-blur-[16px] border-b border-header-border shrink-0 z-10 max-sm:px-4">
        <img
          className="w-10 h-10 rounded-full object-cover shrink-0 bg-surface-alt"
          alt="Эврика"
          {...avatarProps(40)}
        />
        <div className="flex flex-col min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-base font-semibold leading-tight text-fg">Эврика</span>
            <span className="w-2 h-2 rounded-full bg-status shrink-0 animate-[status-pulse_2s_infinite_ease-in-out]" />
          </div>
          <span className="text-[13px] text-fg-muted leading-tight">{headerSubtitle}</span>
        </div>
      </header>

      <EscalationBanner active={chat.escalated} reason={chat.escalationReason} />

      <ChatWindow messages={chat.messages} avatarProps={avatarProps(28)} typing={chat.typing} />

      {chat.error && (
        <div className="px-4 py-3 mx-5 rounded-xl bg-error-bg text-error border border-error-border text-sm leading-normal shrink-0 max-sm:mx-3">
          {chat.error}
        </div>
      )}

      <div className="shrink-0 px-5 pt-3 pb-4 bg-input-area backdrop-blur-[16px] border-t border-input-area-border max-sm:px-3 max-sm:pt-2.5 max-sm:pb-3.5">
        <MessageInput disabled={chat.typing || chat.escalated} onSend={chat.sendMessage} />
      </div>
    </main>
  )
}
