import { useEffect, useMemo, useState } from 'react'
import { fetchMessages, startConversation, streamChat, streamVoice } from '../api/client'

const STORAGE_KEY = 'eurika_conversation_id'

export function useChat(auth) {
  const [messages, setMessages] = useState([])
  const [conversationId, setConversationId] = useState('')
  const [typing, setTyping] = useState(false)
  const [error, setError] = useState('')
  const [started, setStarted] = useState(false)
  const [escalated, setEscalated] = useState(false)
  const [escalationReason, setEscalationReason] = useState('')

  useEffect(() => {
    if (!auth || started) return
    let canceled = false

    ;(async () => {
      try {
        const savedConvId = sessionStorage.getItem(STORAGE_KEY)
        const data = await startConversation(auth, savedConvId)
        if (canceled) return

        setConversationId(data.conversation_id)
        sessionStorage.setItem(STORAGE_KEY, data.conversation_id)

        // Try to restore message history if we resumed a conversation
        if (savedConvId && data.conversation_id === savedConvId) {
          try {
            const historyData = await fetchMessages(savedConvId)
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
  }, [auth, started])

  async function sendMessage(text) {
    if (!text.trim() || !auth || !conversationId || typing || escalated) return

    const userMsg = { id: crypto.randomUUID(), role: 'user', content: text }
    const assistantId = crypto.randomUUID()

    setMessages((prev) => [...prev, userMsg, { id: assistantId, role: 'assistant', content: '' }])
    setTyping(true)
    setError('')

    try {
      await streamChat({
        auth,
        conversationId,
        message: text,
        onEvent: (event, payload) => {
          if (event === 'meta' && payload.conversation_id && payload.conversation_id !== conversationId) {
            setConversationId(payload.conversation_id)
            sessionStorage.setItem(STORAGE_KEY, payload.conversation_id)
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
    }
  }

  async function sendVoiceMessage(audioBlob) {
    if (!auth || !conversationId || typing || escalated) return

    const assistantId = crypto.randomUUID()

    setMessages((prev) => [...prev, { id: assistantId, role: 'assistant', content: '' }])
    setTyping(true)
    setError('')

    try {
      let userMsgAdded = false
      await streamVoice({
        auth,
        conversationId,
        audioBlob,
        onEvent: (event, payload) => {
          if (event === 'meta') {
            if (payload.conversation_id && payload.conversation_id !== conversationId) {
              setConversationId(payload.conversation_id)
              sessionStorage.setItem(STORAGE_KEY, payload.conversation_id)
            }
            if (payload.transcript && !userMsgAdded) {
              userMsgAdded = true
              const userMsg = { id: crypto.randomUUID(), role: 'user', content: payload.transcript }
              setMessages((prev) => {
                const idx = prev.findIndex((m) => m.id === assistantId)
                if (idx === -1) return [...prev, userMsg]
                const copy = [...prev]
                copy.splice(idx, 0, userMsg)
                return copy
              })
            }
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
      setTyping(false)
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
    }
  }

  return useMemo(
    () => ({ messages, sendMessage, sendVoiceMessage, typing, error, started, escalated, escalationReason }),
    [messages, typing, error, started, escalated, escalationReason],
  )
}
