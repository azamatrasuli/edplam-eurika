import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchMessages, startConversation, streamChat } from '../api/client'

function getStorageKey(agentRole) {
  return `eurika_conversation_id_${agentRole}`
}

export function useChat(auth, agentRole = 'sales', onboardingComplete = true) {
  const [messages, setMessages] = useState([])
  const [conversationId, setConversationId] = useState('')
  const [typing, setTyping] = useState(false)
  const [toolStatus, setToolStatus] = useState('')
  const [error, setError] = useState('')
  const [started, setStarted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [escalated, setEscalated] = useState(false)
  const [escalationReason, setEscalationReason] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const abortRef = useRef(null)
  const initRef = useRef(false)
  const conversationIdRef = useRef(conversationId)
  const titleCallbackRef = useRef(null)
  const bumpCallbackRef = useRef(null)

  // --- Load a conversation (new or existing) ---
  const loadConversation = useCallback(async (convId = null, forceNew = false) => {
    if (!auth) return null

    // Abort any in-flight stream
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }

    setLoading(true)
    setTyping(false)
    setError('')
    setEscalated(false)
    setEscalationReason('')

    try {
      const data = await startConversation(auth, convId, agentRole, forceNew)
      setConversationId(data.conversation_id)
      conversationIdRef.current = data.conversation_id
      const storageKey = getStorageKey(agentRole)
      try { sessionStorage.setItem(storageKey, data.conversation_id) } catch { /* quota */ }

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
                  fromHistory: true,
                })),
            )
            setStarted(true)
            setLoading(false)
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
      setStarted(true)
      setLoading(false)
      return data
    } catch (e) {
      let errMsg
      if (e instanceof TypeError && e.message.includes('fetch')) {
        errMsg = 'Нет подключения к серверу. Проверьте интернет и попробуйте снова.'
      } else if (e.code === 'auth_expired' || e.code === 'auth_invalid') {
        errMsg = 'Сессия истекла. Обновите страницу.'
      } else {
        errMsg = e.message || 'Не удалось загрузить чат. Попробуйте обновить страницу.'
      }
      setError(errMsg)
      setLoading(false)
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
    setToolStatus('')
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
            try { sessionStorage.setItem(storageKey, payload.conversation_id) } catch { /* quota */ }
          }

          if (event === 'tool_call') {
            setToolStatus(payload.label || 'Обрабатываю...')
          }

          if (event === 'token') {
            setToolStatus('')
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

          // Title update from backend — push to sidebar
          if (event === 'title' && payload.title) {
            if (titleCallbackRef.current) {
              titleCallbackRef.current(payload.conversation_id, payload.title)
            }
          }

          if (event === 'suggestions' && payload.chips) {
            setSuggestions(payload.chips)
          }

          if (event === 'done') {
            setTyping(false)
            setToolStatus('')
            // Update sidebar metadata reactively
            if (bumpCallbackRef.current) {
              bumpCallbackRef.current(conversationIdRef.current, text)
            }
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
      let errMsg
      if (e.message === 'SSE_TIMEOUT') {
        errMsg = 'Сервер не ответил вовремя. Попробуйте ещё раз.'
      } else if (e.code === 'offline' || (e instanceof TypeError && e.message.includes('fetch'))) {
        errMsg = 'Нет подключения к интернету. Проверьте соединение и попробуйте снова.'
      } else if (e.code === 'rate_limit') {
        errMsg = 'Слишком много сообщений. Подождите минуту.'
      } else if (e.code === 'auth_expired' || e.code === 'auth_invalid') {
        errMsg = 'Сессия истекла. Обновите страницу.'
      } else if (e.code === 'message_too_long') {
        errMsg = 'Сообщение слишком длинное (максимум 4000 символов).'
      } else if (e.code === 'stt_unavailable') {
        errMsg = 'Распознавание речи временно недоступно. Напишите текстом.'
      } else if (e.code === 'internal_error') {
        errMsg = 'Ошибка сервера. Попробуйте через пару минут.'
      } else {
        errMsg = e.message || 'Что-то пошло не так. Попробуйте ещё раз.'
      }
      setError(errMsg)
    } finally {
      abortRef.current = null
    }
  }, [auth, agentRole, typing, escalated])

  const clearSuggestions = useCallback(() => setSuggestions([]), [])

  // Register callbacks (called from ChatPage)
  const onTitleUpdate = useCallback((cb) => {
    titleCallbackRef.current = cb
  }, [])

  const onBumpConversation = useCallback((cb) => {
    bumpCallbackRef.current = cb
  }, [])

  return {
    messages,
    conversationId,
    sendMessage,
    typing,
    toolStatus,
    error,
    started,
    loading,
    escalated,
    escalationReason,
    switchConversation,
    startNewChat,
    suggestions,
    clearSuggestions,
    onTitleUpdate,
    onBumpConversation,
  }
}
