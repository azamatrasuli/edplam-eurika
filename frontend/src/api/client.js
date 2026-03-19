export const MESSAGE_MAX_LENGTH = 4000

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL
  || (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://127.0.0.1:8009'
    : 'https://edplam-eurika.onrender.com')

// ---------------------------------------------------------------------------
// ApiError — structured error with code, message, hint, status
// ---------------------------------------------------------------------------

const STATUS_FALLBACKS = {
  401: { code: 'auth_expired', message: 'Сессия истекла. Обновите страницу' },
  403: { code: 'access_denied', message: 'Нет доступа к этому ресурсу' },
  413: { code: 'audio_too_large', message: 'Файл слишком большой' },
  422: { code: 'validation_error', message: 'Ошибка валидации данных' },
  429: { code: 'rate_limit', message: 'Слишком много запросов. Подождите минуту' },
  500: { code: 'internal_error', message: 'Ошибка сервера. Попробуйте позже' },
  502: { code: 'service_unavailable', message: 'Сервис временно недоступен. Попробуйте через пару минут' },
  503: { code: 'service_unavailable', message: 'Сервис временно недоступен. Попробуйте через пару минут' },
}

export class ApiError extends Error {
  constructor(code, message, { status = 0, hint = '' } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.hint = hint
  }
}

async function throwApiError(response) {
  let code, detail, hint
  try {
    const body = await response.json()
    code = body.error
    detail = body.detail
    hint = body.hint
  } catch {
    // response body is not JSON — use fallback
  }

  if (!code || !detail) {
    const fallback = STATUS_FALLBACKS[response.status] || {
      code: 'unknown',
      message: 'Что-то пошло не так. Попробуйте ещё раз',
    }
    code = code || fallback.code
    detail = detail || fallback.message
  }

  throw new ApiError(code, detail, { status: response.status, hint: hint || '' })
}

function checkOnline() {
  if (typeof navigator !== 'undefined' && !navigator.onLine) {
    throw new ApiError('offline', 'Нет подключения к интернету. Проверьте соединение')
  }
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function startConversation(auth, conversationId = null, agentRole = 'sales', forceNew = false) {
  const body = { auth, agent_role: agentRole }
  if (conversationId && !forceNew) body.conversation_id = conversationId
  if (forceNew) body.force_new = true
  const response = await fetch(`${API_BASE_URL}/api/v1/conversations/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) await throwApiError(response)
  return response.json()
}

export async function fetchMessages(conversationId, auth) {
  const response = await fetch(`${API_BASE_URL}/api/v1/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(auth),
  })
  if (!response.ok) await throwApiError(response)
  return response.json()
}

function parseSSE(buffer, onEvent) {
  let boundary = buffer.indexOf('\n\n')
  while (boundary !== -1) {
    const rawEvent = buffer.slice(0, boundary)
    buffer = buffer.slice(boundary + 2)
    const lines = rawEvent.split('\n')

    let event = 'message'
    let dataLine = '{}'
    for (const line of lines) {
      if (line.startsWith('event: ')) event = line.slice(7)
      if (line.startsWith('data: ')) dataLine = line.slice(6)
    }

    try {
      const payload = JSON.parse(dataLine)
      onEvent(event, payload)
    } catch {
      // Malformed SSE data — skip this event
      console.warn('Failed to parse SSE data:', dataLine)
    }
    boundary = buffer.indexOf('\n\n')
  }
  return buffer
}

const SSE_TIMEOUT_MS = 45_000

async function readSSEStream(response, onEvent) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    let timerId
    const timeout = new Promise((_, reject) => {
      timerId = setTimeout(() => reject(new Error('SSE_TIMEOUT')), SSE_TIMEOUT_MS)
    })
    try {
      const { value, done } = await Promise.race([reader.read(), timeout])
      clearTimeout(timerId)
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      buffer = parseSSE(buffer, onEvent)
    } catch (e) {
      clearTimeout(timerId)
      throw e
    }
  }
}

export async function streamChat({ auth, conversationId, message, agentRole = 'sales', onEvent, signal }) {
  checkOnline()

  const response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auth, conversation_id: conversationId, message, agent_role: agentRole }),
    signal,
  })

  if (!response.ok || !response.body) {
    await throwApiError(response)
  }

  await readSSEStream(response, onEvent)
}

export async function transcribeAudio(audioBlob, auth) {
  const formData = new FormData()
  formData.append('audio', audioBlob, 'voice.webm')
  if (auth) formData.append('auth_json', JSON.stringify(auth))
  const response = await fetch(`${API_BASE_URL}/api/v1/chat/transcribe`, {
    method: 'POST',
    body: formData,
  })
  if (!response.ok) await throwApiError(response)
  return (await response.json()).transcript
}

export async function checkProfile(auth) {
  const response = await fetch(`${API_BASE_URL}/api/v1/profile/check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auth }),
  })
  if (!response.ok) await throwApiError(response)
  return response.json()
}

export async function verifyOnboarding(auth, data) {
  const response = await fetch(`${API_BASE_URL}/api/v1/onboarding/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auth, ...data }),
  })
  if (!response.ok) await throwApiError(response)
  return response.json()
}

export async function streamVoice({ auth, conversationId, audioBlob, agentRole = 'sales', onEvent, signal }) {
  checkOnline()

  const formData = new FormData()
  formData.append('audio', audioBlob, 'voice.webm')
  formData.append('auth_json', JSON.stringify(auth))
  if (conversationId) {
    formData.append('conversation_id', conversationId)
  }
  formData.append('agent_role', agentRole)

  const response = await fetch(`${API_BASE_URL}/api/v1/chat/voice`, {
    method: 'POST',
    body: formData,
    signal,
  })

  if (!response.ok || !response.body) {
    await throwApiError(response)
  }

  await readSSEStream(response, onEvent)
}

// ---- Conversation History API -------------------------------------------

export async function listConversations(auth, agentRole = null, { offset = 0, limit = 20, includeArchived = false } = {}) {
  const body = { auth, offset, limit, include_archived: includeArchived }
  if (agentRole) body.agent_role = agentRole
  const response = await fetch(`${API_BASE_URL}/api/v1/conversations/list`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) await throwApiError(response)
  return response.json()
}

export async function archiveConversation(conversationId, auth) {
  const response = await fetch(`${API_BASE_URL}/api/v1/conversations/${conversationId}/archive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(auth),
  })
  if (!response.ok) await throwApiError(response)
  return response.json()
}

export async function renameConversation(conversationId, title, auth) {
  const response = await fetch(`${API_BASE_URL}/api/v1/conversations/${conversationId}/rename`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auth, title }),
  })
  if (!response.ok) await throwApiError(response)
  return response.json()
}

export async function deleteConversation(conversationId, auth) {
  const response = await fetch(`${API_BASE_URL}/api/v1/conversations/${conversationId}/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(auth),
  })
  if (!response.ok) await throwApiError(response)
  return response.json()
}

export async function unarchiveConversation(conversationId, auth) {
  const response = await fetch(`${API_BASE_URL}/api/v1/conversations/${conversationId}/unarchive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(auth),
  })
  if (!response.ok) await throwApiError(response)
  return response.json()
}

export async function searchConversations(auth, query, agentRole = null) {
  const body = { auth, query }
  if (agentRole) body.agent_role = agentRole
  const response = await fetch(`${API_BASE_URL}/api/v1/conversations/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) await throwApiError(response)
  return response.json()
}
