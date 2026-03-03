import { useEffect, useMemo, useState } from 'react'
import { ChatWindow } from './components/ChatWindow'
import { EscalationBanner } from './components/EscalationBanner'
import { MessageInput } from './components/MessageInput'
import { TypingIndicator } from './components/TypingIndicator'
import { WelcomeScreen } from './components/WelcomeScreen'
import { useChat } from './hooks/useChat'
import { buildAuthPayload } from './lib/authContext'

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

export function App() {
  useTelegramTheme()
  const auth = useMemo(() => buildAuthPayload(), [])
  const [startedByUser, setStartedByUser] = useState(false)

  const activeAuth = startedByUser ? auth : null
  const { messages, sendMessage, sendVoiceMessage, typing, error, started, escalated, escalationReason } = useChat(activeAuth)

  if (!auth) {
    return <div className="app-error">Не найден токен входа. Откройте чат из портала, Telegram или внешней ссылки.</div>
  }

  if (!startedByUser) {
    return <WelcomeScreen onStart={() => setStartedByUser(true)} />
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <h1>Эврика</h1>
        <p>AI менеджер EdPalm</p>
      </header>

      <EscalationBanner active={escalated} reason={escalationReason} />

      {!started ? <div className="loading">Инициализация диалога...</div> : <ChatWindow messages={messages} />}
      {typing && <TypingIndicator />}
      {error && <div className="app-error">{error}</div>}

      <MessageInput disabled={!started || typing || escalated} onSend={sendMessage} onSendVoice={sendVoiceMessage} />
    </main>
  )
}
