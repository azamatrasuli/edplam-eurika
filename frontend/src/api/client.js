const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8009'

export async function startConversation(auth, conversationId = null) {
  const body = { auth }
  if (conversationId) body.conversation_id = conversationId
  const response = await fetch(`${API_BASE_URL}/api/v1/conversations/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(`Failed to start conversation (${response.status})`)
  }
  return response.json()
}

export async function fetchMessages(conversationId) {
  const response = await fetch(`${API_BASE_URL}/api/v1/conversations/${conversationId}/messages`)
  if (!response.ok) {
    throw new Error(`Failed to fetch messages (${response.status})`)
  }
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

    const payload = JSON.parse(dataLine)
    onEvent(event, payload)
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
    const timeout = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('SSE_TIMEOUT')), SSE_TIMEOUT_MS),
    )
    const { value, done } = await Promise.race([reader.read(), timeout])
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    buffer = parseSSE(buffer, onEvent)
  }
}

export async function streamChat({ auth, conversationId, message, onEvent }) {
  const response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auth, conversation_id: conversationId, message }),
  })

  if (!response.ok || !response.body) {
    throw new Error(`Chat stream failed (${response.status})`)
  }

  await readSSEStream(response, onEvent)
}

export async function streamVoice({ auth, conversationId, audioBlob, onEvent }) {
  const formData = new FormData()
  formData.append('audio', audioBlob, 'voice.webm')
  formData.append('auth_json', JSON.stringify(auth))
  if (conversationId) {
    formData.append('conversation_id', conversationId)
  }

  const response = await fetch(`${API_BASE_URL}/api/v1/chat/voice`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok || !response.body) {
    throw new Error(`Voice stream failed (${response.status})`)
  }

  await readSSEStream(response, onEvent)
}
