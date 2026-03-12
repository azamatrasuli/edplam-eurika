import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchMessages, startConversation, streamChat } from '../api/client'

function getStorageKey(agentRole) {
  return `eurika_conversation_id_${agentRole}`
}

export function useChat(auth, agentRole = 'sales', onboardingComplete = true) {
  const [messages, setMessages] = useState([])
  const [conversationId, setConversationId] = useState('')
  const [typing, setTyping] = useState(false)
  const [error, setError] = useState('')
  const [started, setStarted] = useState(false)
  const [escalated, setEscalated] = useState(false)
  const [escalationReason, setEscalationReason] = useState('')
  const abortRef = useRef(null)

  useEffect(() => {
    if (!auth || started || !onboardingComplete) return
    let canceled = false

    ;(async () => {
      try {
        const storageKey = getStorageKey(agentRole)
        const savedConvId = sessionStorage.getItem(storageKey)
        const data = await startConversation(auth, savedConvId, agentRole)
        if (canceled) return

        setConversationId(data.conversation_id)
        sessionStorage.setItem(storageKey, data.conversation_id)

        // Try to restore message history if we resumed a conversation
        if (savedConvId && data.conversation_id === savedConvId) {
          try {
            const historyData = await fetchMessages(savedConvId, auth)
            if (!canceled && historyData.messages && historyData.messages.length > 0) {
              setMessages(
                historyData.messages
                  .filter((m) => m.role !== 'system')
                  .map((m) => ({
                    id: crypto.randomUUID(),
                    role: m.role,
                    content: m.content,
                  })),
              )
              setStarted(true)
              return
            }
          } catch {
            // History fetch failed — fall through to new greeting
          }
        }

        if (canceled) return

        // Use greeting from backend (personalized, saved in DB)
        const greeting = data?.greeting || 'Здравствуйте! Я Эврика, виртуальный менеджер EdPalm.'
        setMessages([
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: greeting,
          },
        ])
        setStarted(true)
      } catch (e) {
        if (!canceled) setError(e.message)
      }
    })()

    return () => {
      canceled = true
    }
  }, [auth, started, agentRole, onboardingComplete])

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort()
        abortRef.current = null
      }
    }
  }, [])

  async function sendMessage(text) {
    if (!text.trim() || !auth || !conversationId || typing || escalated) return

    const userMsg = { id: crypto.randomUUID(), role: 'user', content: text }
    const assistantId = crypto.randomUUID()

    setMessages((prev) => [...prev, userMsg, { id: assistantId, role: 'assistant', content: '' }])
    setTyping(true)
    setError('')

    const controller = new AbortController()
    abortRef.current = controller

    const storageKey = getStorageKey(agentRole)

    try {
      await streamChat({
        auth,
        conversationId,
        message: text,
        agentRole,
        signal: controller.signal,
        onEvent: (event, payload) => {
          if (event === 'meta' && payload.conversation_id && payload.conversation_id !== conversationId) {
            setConversationId(payload.conversation_id)
            sessionStorage.setItem(storageKey, payload.conversation_id)
          }

          if (event === 'token') {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content: `${m.content}${payload.text || ''}` } : m,
              ),
            )
          }

          if (event === 'escalation') {
            setEscalated(true)
            setEscalationReason(payload.reason || '')
          }

          if (event === 'done') {
            setTyping(false)
          }
        },
      })
    } catch (e) {
      if (e.name === 'AbortError') return
      setTyping(false)
      // Mark partial response if tokens were received before error
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId && m.content
            ? { ...m, content: `${m.content}\n\n_(ответ неполный)_` }
            : m,
        ),
      )
      const userMsg = e.message === 'SSE_TIMEOUT'
        ? 'Сервер не ответил вовремя. Попробуйте ещё раз.'
        : e.message
      setError(userMsg)
    } finally {
      abortRef.current = null
    }
  }

  return useMemo(
    () => ({ messages, sendMessage, typing, error, started, escalated, escalationReason }),
    [messages, typing, error, started, escalated, escalationReason],
  )
}
