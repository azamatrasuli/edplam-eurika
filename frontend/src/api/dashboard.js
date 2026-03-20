const API_BASE_URL = import.meta.env.VITE_API_BASE_URL
  || (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://127.0.0.1:8009'
    : 'https://edplam-eurika.onrender.com')

function getDashboardKey() {
  const params = new URLSearchParams(window.location.search)
  return params.get('key') || sessionStorage.getItem('dashboard_key') || ''
}

async function dashboardFetch(endpoint, params = {}) {
  const key = getDashboardKey()
  if (!key) throw new Error('API-ключ не указан. Добавьте ?key=... в URL')

  // Store key in session for page navigation
  sessionStorage.setItem('dashboard_key', key)

  const url = new URL(`${API_BASE_URL}/api/v1/dashboard/${endpoint}`)
  Object.entries(params).forEach(([k, v]) => {
    if (v != null && v !== '') url.searchParams.set(k, v)
  })

  let response
  try {
    response = await fetch(url.toString(), {
    headers: { Authorization: `Bearer ${key}` },
    })
  } catch {
    throw new Error('Нет подключения к серверу. Проверьте интернет')
  }

  if (!response.ok) {
    if (response.status === 401) throw new Error('Неверный API-ключ')
    throw new Error('Ошибка загрузки данных. Попробуйте обновить страницу')
  }

  return response.json()
}

export function fetchMetrics(params) {
  return dashboardFetch('metrics', params)
}

export function fetchConversations(params) {
  return dashboardFetch('conversations', params)
}

export function fetchEscalations(params) {
  return dashboardFetch('escalations', params)
}

export function fetchUnanswered(params) {
  return dashboardFetch('unanswered', params)
}
