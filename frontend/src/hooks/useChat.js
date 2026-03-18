import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchMessages, startConversation, streamChat } from '../api/client'

function getStorageKey(agentRole) {
  return `eurika_conversation_id_${agentRole}`
}

// Quick reply buttons shown after the greeting
const QUICK_REPLIES = {
  sales: [
    { id: 'programs', label: 'Подобрать программу', value: 'Хочу подобрать программу обучения' },
    { id: 'prices', label: 'Узнать стоимость', value: 'Сколько стоит обучение?' },
    { id: 'question', label: 'У меня вопрос', value: 'У меня есть вопрос об EdPalm' },
  ],
  support: [
    { id: 'platform', label: 'Вопрос по платформе', value: 'У меня вопрос по учебной платформе' },
    { id: 'docs', label: 'Документы', value: 'Мне нужна справка или документ' },
    { id: 'payment', label: 'Вопрос по оплате', value: 'У меня вопрос по оплате' },
  ],
}

export function useChat(auth, agentRole = 'sales', onboardingComplete = true) {
  const [messages, setMessages] = useState([])
  const [conversationId, setConversationId] = useState('')
  const [typing, setTyping] = useState(false)
  const [error, setError] = useState('')
  const [started, setStarted] = useState(false)
  const [escalated, setEscalated] = useState(false)
  const [escalationReason, setEscalationReason] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const abortRef = useRef(null)
  const initRef = useRef(false)
  const conversationIdRef = useRef(conversationId)

  // --- Load a conversation (new or existing) ---
  const loadConversation = useCallback(async (convId = null, forceNew = false) => {
    if (!auth) return null

    // Abort any in-flight stream
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }

    setTyping(false)
    setError('')
    setEscalated(false)
    setEscalationReason('')

    try {
      const data = await startConversation(auth, convId, agentRole, forceNew)
      setConversationId(data.conversation_id)
      conversationIdRef.current = data.conversation_id
      const storageKey = getStorageKey(agentRole)
      sessionStorage.setItem(storageKey, data.conversation_id)

      // Try to restore message history for existing conversations
      if (convId && data.conversation_id === convId && !forceNew) {
        try {
          const historyData = await fetchMessages(convId, auth)
          if (historyData.messages && historyData.messages.length > 0) {
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
            return data
          }
        } catch {
          // History fetch failed — fall through to new greeting
        }
      }

      // Build greeting
      const greeting = data?.greeting || 'Привет! Я Эврика из EdPalm. Чем могу помочь?'
      const initMessages = [
        { id: crypto.randomUUID(), role: 'assistant', content: greeting },
      ]

      setMessages(initMessages)

      // Suggestion chips disabled — pure live conversation
      // const replies = QUICK_REPLIES[agentRole] || QUICK_REPLIES.sales
      // setSuggestions(replies.map(r => ({ label: r.label, value: r.value })))
      setStarted(true)
      return data
    } catch (e) {
      setError(e.message)
      return null
    }
  }, [auth, agentRole])

  // --- Initial load on mount ---
  useEffect(() => {
    if (!auth || initRef.current || !onboardingComplete) return
    initRef.current = true

    const storageKey = getStorageKey(agentRole)
    const savedConvId = sessionStorage.getItem(storageKey)
    loadConversation(savedConvId)
  }, [auth, agentRole, onboardingComplete, loadConversation])

  // Keep conversationIdRef in sync
  useEffect(() => {
    conversationIdRef.current = conversationId
  }, [conversationId])

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort()
        abortRef.current = null
      }
    }
  }, [])

  // --- Switch to an existing conversation ---
  const switchConversation = useCallback(async (convId) => {
    if (convId === conversationIdRef.current) return
    await loadConversation(convId)
  }, [loadConversation])

  // --- Start a completely new conversation ---
  const startNewChat = useCallback(async () => {
    const data = await loadConversation(null, true)
    return data
  }, [loadConversation])

  const sendMessage = useCallback(async (text) => {
    const currentConvId = conversationIdRef.current
    if (!text.trim() || !auth || !currentConvId || typing || escalated) return

    setSuggestions([])

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
        conversationId: currentConvId,
        message: text,
        agentRole,
        signal: controller.signal,
        onEvent: (event, payload) => {
          if (event === 'meta' && payload.conversation_id && payload.conversation_id !== conversationIdRef.current) {
            setConversationId(payload.conversation_id)
            conversationIdRef.current = payload.conversation_id
            sessionStorage.setItem(storageKey, payload.conversation_id)
          }

          if (event === 'token') {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content: `${m.content}${payload.text || ''}` } : m,
              ),
            )
          }

          if (event === 'payment_card') {
            setMessages((prev) => [
              ...prev,
              {
                id: crypto.randomUUID(),
                role: 'assistant',
                content: '',
                type: 'payment',
                paymentData: payload,
              },
            ])
          }

          if (event === 'escalation') {
            setEscalated(true)
            setEscalationReason(payload.reason || '')
          }

          // Suggestion chips disabled — pure live conversation
          // if (event === 'suggestions') {
          //   setSuggestions(
          //     (payload.chips || []).slice(0, 4).map(c => ({ label: c.label, value: c.value }))
          //   )
          // }

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
      const errMsg = e.message === 'SSE_TIMEOUT'
        ? 'Сервер не ответил вовремя. Попробуйте ещё раз.'
        : e.message
      setError(errMsg)
    } finally {
      abortRef.current = null
    }
  }, [auth, agentRole, typing, escalated])

  const clearSuggestions = useCallback(() => setSuggestions([]), [])

  return {
    messages,
    conversationId,
    sendMessage,
    typing,
    error,
    started,
    escalated,
    escalationReason,
    switchConversation,
    startNewChat,
    suggestions,
    clearSuggestions,
  }
}
