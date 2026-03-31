import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchMessages, pollMessages, startConversation, streamChat } from '../api/client'
import { isManagerMode } from '../lib/authContext'

const _COLD_START = [
  'Сервер просыпается...', 'Подключаюсь...', 'Сервер разогревается...',
  'Устанавливаю соединение...', 'Запускаюсь...', 'Сервер загружается...',
  'Секунду, подключаюсь...', 'Соединяюсь с сервером...', 'Инициализация...',
  'Начинаю работу...', 'Поднимаю сервер...', 'Подключаюсь к серверу...',
  'Сервер стартует...', 'Подготавливаю систему...', 'Устанавливаю связь...',
  'Запускаю систему...', 'Загружаю сервер...', 'Подключение...',
  'Соединение устанавливается...', 'Инициализирую подключение...',
  'Сервер поднимается...', 'Разогреваю систему...', 'Подготавливаю подключение...',
  'Сервер стартует, подождите...', 'Устанавливаю подключение...',
  'Запускаю подключение...', 'Загружаю систему...', 'Секунду, загружаюсь...',
  'Соединяюсь...', 'Настраиваю подключение...', 'Сервер включается...',
  'Подготавливаю сервер...', 'Поднимаю систему...', 'Разогреваю сервер...',
  'Устанавливаю канал связи...', 'Запускаю сервис...', 'Загружаю подключение...',
  'Подключаюсь, подождите...', 'Соединение...', 'Инициализирую сервер...',
  'Сервер выходит на связь...', 'Подготавливаю связь...', 'Поднимаю подключение...',
  'Разогреваюсь...', 'Устанавливаю соединение с сервером...',
  'Запускаю связь...', 'Загружаю сервис...', 'Подключение к серверу...',
  'Соединяюсь с системой...', 'Инициализирую систему...',
]

const _COLD_START_LONG = [
  'Ещё чуть-чуть...', 'Почти готово...', 'Уже скоро...', 'Ещё немного...',
  'Почти на месте...', 'Совсем чуть-чуть...', 'Скоро начнём...',
  'Ещё мгновение...', 'Вот-вот...', 'Ещё секунду...',
  'Уже почти подключилась...', 'Почти загрузилось...', 'Ещё пару секунд...',
  'Скоро всё будет готово...', 'Уже заканчиваю загрузку...',
  'Почти запустилось...', 'Ещё совсем немного...', 'Уже на подходе...',
  'Вот-вот начнём...', 'Почти соединилось...', 'Ещё капельку...',
  'Скоро отвечу...', 'Уже почти...', 'Ещё один момент...',
  'Почти подключилось...', 'Совсем скоро...', 'Ещё чуточку...',
  'Скоро буду готова...', 'Уже загружаюсь...', 'Ещё буквально секунду...',
  'Почти-почти...', 'Вот уже скоро...', 'Ещё немножко...',
  'Скоро стартуем...', 'Уже на финишной прямой...', 'Ещё пара мгновений...',
  'Почти добралась...', 'Совсем рядом...', 'Ещё самую малость...',
  'Скоро подключусь...', 'Уже выхожу на связь...', 'Ещё миг...',
  'Почти на связи...', 'Вот-вот подключусь...', 'Ещё один миг...',
  'Скоро выйду на связь...', 'Уже совсем скоро...', 'Ещё чуть-чуть подождите...',
  'Почти всё загрузилось...', 'Совсем немного осталось...',
]

function _pick(arr) { return arr[Math.floor(Math.random() * arr.length)] }

function getStorageKey(agentRole) {
  return `eurika_conversation_id_${agentRole}`
}

// Background stream tracker — survives component unmount/remount.
// When ChatPage unmounts mid-stream, the fetch continues so the backend
// saves the full response. On re-mount, loadConversation awaits this.
let _bgStream = null // { convId: string, promise: Promise<void> } | null

export function useChat(auth, agentRole = 'sales', onboardingComplete = true, { initialConvId = null } = {}) {
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
  const typingRef = useRef(false)
  const escalatedRef = useRef(false)
  const [sseConnected, setSseConnected] = useState(true)
  const sseRetryRef = useRef(0)
  const statusTimerRef = useRef(null)
  const lastStatusTimeRef = useRef(0)

  const updateToolStatus = useCallback((newStatus) => {
    const now = Date.now()
    const elapsed = now - lastStatusTimeRef.current
    const MIN_DISPLAY_MS = 800

    if (statusTimerRef.current) {
      clearTimeout(statusTimerRef.current)
      statusTimerRef.current = null
    }

    if (!newStatus) {
      const remaining = MIN_DISPLAY_MS - elapsed
      if (remaining > 0 && lastStatusTimeRef.current > 0) {
        statusTimerRef.current = setTimeout(() => {
          setToolStatus('')
          statusTimerRef.current = null
        }, remaining)
      } else {
        setToolStatus('')
      }
      return
    }

    const remaining = MIN_DISPLAY_MS - elapsed
    if (remaining > 0 && lastStatusTimeRef.current > 0) {
      statusTimerRef.current = setTimeout(() => {
        setToolStatus(newStatus)
        lastStatusTimeRef.current = Date.now()
        statusTimerRef.current = null
      }, remaining)
    } else {
      setToolStatus(newStatus)
      lastStatusTimeRef.current = now
    }
  }, [])

  // --- Load a conversation (new or existing) ---
  const loadConversation = useCallback(async (convId = null, forceNew = false) => {
    if (!auth) return null

    // If switching to a DIFFERENT conversation, abort the in-flight stream
    if (abortRef.current && convId !== conversationIdRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      _bgStream = null
    }

    setLoading(true)
    typingRef.current = false
    setTyping(false)
    setError('')
    // Clear seen DB IDs for fresh conversation
    seenDbIdsRef.current = new Set()
    // Only reset escalation on forced new conversation
    if (forceNew) {
      setEscalated(false)
      setEscalationReason('')
    }

    // If re-loading the SAME conversation with an active background stream
    // (user navigated away and came back), wait for it to finish
    if (_bgStream && _bgStream.convId === convId) {
      try {
        await Promise.race([
          _bgStream.promise,
          new Promise((_, reject) => setTimeout(() => reject(new Error('bg_timeout')), 30_000)),
        ])
      } catch {
        // Timed out — proceed with partial data
      }
      _bgStream = null
    }

    try {
      const data = await startConversation(auth, convId, agentRole, forceNew)
      setConversationId(data.conversation_id)
      conversationIdRef.current = data.conversation_id
      const storageKey = getStorageKey(agentRole)
      try { sessionStorage.setItem(storageKey, data.conversation_id) } catch { /* quota */ }

      // Restore escalation state from backend
      if (data.status === 'escalated') {
        setEscalated(true)
        setEscalationReason(data.escalated_reason || '')
      } else {
        setEscalated(false)
        setEscalationReason('')
      }

      // Try to restore message history for existing conversations
      if (convId && data.conversation_id === convId && !forceNew) {
        try {
          const historyData = await fetchMessages(convId, auth)
          if (historyData.messages && historyData.messages.length > 0) {
            const loaded = historyData.messages
                .filter((m) => m.role !== 'system')
                .map((m) => ({
                  id: crypto.randomUUID(),
                  role: m.role,
                  content: m.content,
                  fromHistory: true,
                  type: m.metadata?.source === 'manager' ? 'manager' : undefined,
                }))
            setMessages(loaded)
            // Also check escalation from messages endpoint
            if (historyData.status === 'escalated') {
              setEscalated(true)
              setEscalationReason(historyData.escalated_reason || '')
            }
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

    // Priority: URL param > sessionStorage
    const convId = initialConvId || sessionStorage.getItem(getStorageKey(agentRole))
    loadConversation(convId)
  }, [auth, agentRole, onboardingComplete, loadConversation])

  // Keep conversationIdRef in sync
  useEffect(() => {
    conversationIdRef.current = conversationId
  }, [conversationId])

  // Keep refs in sync with state for synchronous guard checks
  useEffect(() => { typingRef.current = typing }, [typing])
  useEffect(() => { escalatedRef.current = escalated }, [escalated])

  // Cleanup on unmount — do NOT abort active stream (let it finish in background
  // so the backend saves the full response; setState calls become harmless no-ops)
  useEffect(() => {
    return () => {
      if (statusTimerRef.current) {
        clearTimeout(statusTimerRef.current)
        statusTimerRef.current = null
      }
    }
  }, [])

  // --- SSE Live Channel: real-time message delivery ---
  // Strategy: SSE only delivers "other party" messages.
  // Client view: SSE delivers manager + system messages. AI responses come via streaming.
  // Manager view: SSE delivers user + AI + system messages. Manager's own messages shown locally.
  const seenDbIdsRef = useRef(new Set()) // track DB message IDs to prevent history overlap

  useEffect(() => {
    if (!conversationId) return

    const managerMode = isManagerMode()
    const params = new URLSearchParams()
    if (auth.manager_key) params.set('key', auth.manager_key)
    if (auth.guest_id) params.set('guest_id', auth.guest_id)
    if (auth.portal_token) params.set('token', auth.portal_token)
    if (auth.telegram_init_data) params.set('telegram_init_data', auth.telegram_init_data)

    const API_BASE = import.meta.env.VITE_API_BASE_URL
      || (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
        ? 'http://127.0.0.1:8009'
        : 'https://edpalm-eurika-ws1a.onrender.com')

    const url = `${API_BASE}/api/v1/chat/listen/${conversationId}?${params.toString()}`
    const evtSource = new EventSource(url)

    evtSource.addEventListener('new_message', (e) => {
      try {
        const msg = JSON.parse(e.data)

        // Dedup by DB message ID (prevents history overlap on reconnect)
        if (msg.id && seenDbIdsRef.current.has(msg.id)) return
        if (msg.id) seenDbIdsRef.current.add(msg.id)

        const isManagerMsg = msg.metadata?.source === 'manager'
        const isSystemMsg = msg.metadata?.source === 'system'

        // --- Role-based filtering: only deliver "other party" messages ---
        if (!managerMode) {
          // Client view:
          // - Skip own user messages (shown locally by sendMessage)
          if (msg.role === 'user') return
          // - Skip AI responses (delivered via streaming channel)
          //   But allow manager and system messages
          if (msg.role === 'assistant' && !isManagerMsg && !isSystemMsg) return
        } else {
          // Manager view:
          // - Skip own manager messages (shown locally by sendMessage)
          if (isManagerMsg) return
        }

        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            dbId: msg.id,
            role: msg.role,
            content: msg.content,
            type: isManagerMsg ? 'manager' : isSystemMsg ? 'system' : undefined,
            senderName: msg.metadata?.sender_name || (isManagerMsg ? 'Менеджер' : undefined),
            fromHistory: true,
          },
        ])
      } catch {
        // ignore
      }
    })

    evtSource.onopen = () => {
      sseRetryRef.current = 0
      setSseConnected(true)
    }

    evtSource.onerror = () => {
      sseRetryRef.current += 1
      if (sseRetryRef.current >= 3) setSseConnected(false)
    }

    return () => evtSource.close()
  }, [conversationId, auth])

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
    if (!text.trim() || !auth || !currentConvId || typingRef.current || escalatedRef.current) return

    setSuggestions([])

    // Manager mode: show as manager bubble (blue, left), not as user (green, right)
    const managerMode = isManagerMode()
    const assistantId = crypto.randomUUID()

    if (managerMode) {
      const mgrMsg = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: text,
        type: 'manager',
        senderName: 'Менеджер',
      }
      setMessages((prev) => [...prev, mgrMsg])
    } else {
      const userMsg = { id: crypto.randomUUID(), role: 'user', content: text }
      setMessages((prev) => [...prev, userMsg, { id: assistantId, role: 'assistant', content: '' }])
    }
    typingRef.current = !managerMode // Synchronous guard against double-send
    setTyping(!managerMode)
    updateToolStatus('')
    setError('')

    const controller = new AbortController()
    abortRef.current = controller

    // Track stream at module level so it survives unmount
    let resolveBg
    _bgStream = { convId: currentConvId, promise: new Promise((r) => { resolveBg = r }) }

    const storageKey = getStorageKey(agentRole)

    // Show "warming up" hint if server is slow (Render cold start)
    let gotFirstToken = false
    const warmingTimer = setTimeout(() => {
      if (!gotFirstToken) updateToolStatus(_pick(_COLD_START))
    }, 8000)
    const warmingTimer2 = setTimeout(() => {
      if (!gotFirstToken) updateToolStatus(_pick(_COLD_START_LONG))
    }, 15000)

    try {
      await streamChat({
        auth,
        conversationId: currentConvId,
        message: text,
        agentRole,
        signal: controller.signal,
        onEvent: (event, payload) => {
          if (!gotFirstToken && (event === 'token' || event === 'meta' || event === 'tool_call' || event === 'status')) {
            gotFirstToken = true
            clearTimeout(warmingTimer)
            clearTimeout(warmingTimer2)
          }

          if (event === 'meta' && payload.conversation_id && payload.conversation_id !== conversationIdRef.current) {
            setConversationId(payload.conversation_id)
            conversationIdRef.current = payload.conversation_id
            try { sessionStorage.setItem(storageKey, payload.conversation_id) } catch { /* quota */ }
          }

          if (event === 'tool_call') {
            updateToolStatus(payload.label || 'Обрабатываю...')
          }

          if (event === 'token') {
            updateToolStatus('')
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

          if (event === 'manager_message') {
            setMessages((prev) => [
              ...prev,
              {
                id: crypto.randomUUID(),
                role: 'assistant',
                content: payload.text,
                type: 'manager',
                senderName: payload.sender,
              },
            ])
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

          // Manager is active OR processing status from backend
          if (event === 'status') {
            if (payload.manager_active) {
              typingRef.current = false
              setTyping(false)
              updateToolStatus('')
              // Remove empty assistant placeholder
              setMessages((prev) => prev.filter((m) => m.id !== assistantId || m.content))
            } else if (payload.label) {
              updateToolStatus(payload.label)
            }
          }

          if (event === 'done') {
            typingRef.current = false
            setTyping(false)
            updateToolStatus('')
            lastStatusTimeRef.current = 0
            // Remove empty assistant placeholder (manager mode or no-response)
            setMessages((prev) => prev.filter((m) => m.id !== assistantId || m.content))
            // Update sidebar metadata reactively
            if (bumpCallbackRef.current) {
              bumpCallbackRef.current(conversationIdRef.current, text)
            }
          }
        },
      })
    } catch (e) {
      if (e.name === 'AbortError') return
      typingRef.current = false
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
      clearTimeout(warmingTimer)
      clearTimeout(warmingTimer2)
      abortRef.current = null
      if (resolveBg) resolveBg()
      if (_bgStream?.convId === currentConvId) _bgStream = null
    }
  }, [auth, agentRole])

  const clearSuggestions = useCallback(() => setSuggestions([]), [])

  // Register callbacks (called from ChatPage)
  const onTitleUpdate = useCallback((cb) => {
    titleCallbackRef.current = cb
  }, [])

  const onBumpConversation = useCallback((cb) => {
    bumpCallbackRef.current = cb
  }, [])

  const addSystemMessage = useCallback((text) => {
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: 'assistant', content: text, type: 'system' },
    ])
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
    addSystemMessage,
    sseConnected,
  }
}
