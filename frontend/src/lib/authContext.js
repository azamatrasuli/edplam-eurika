function getQueryParam(name) {
  // Check regular query string first (?token=...), then hash query (/#/?role=...)
  const params = new URLSearchParams(window.location.search)
  const value = params.get(name)
  if (value) return value

  // HashRouter: params are inside the hash (e.g. /#/?role=support&t=...)
  const hash = window.location.hash
  const hashQuery = hash.includes('?') ? hash.split('?')[1] : ''
  if (hashQuery) {
    const hashParams = new URLSearchParams(hashQuery)
    return hashParams.get(name)
  }
  return null
}

function getTelegramWebApp() {
  try {
    return window.Telegram?.WebApp || null
  } catch {
    return null
  }
}

export function getConvFromURL() {
  return getQueryParam('conv')
}

export function isManagerMode() {
  return !!getQueryParam('manager_key')
}

export function getAgentRole() {
  const role = getQueryParam('role')
  if (role === 'support') return 'support'
  if (role === 'teacher') return 'teacher'
  return 'sales'
}

export function buildAuthPayload() {
  const portalToken = getQueryParam('token')
  const externalToken = getQueryParam('t')

  if (portalToken) {
    return { portal_token: portalToken }
  }

  const tgWebApp = getTelegramWebApp()
  if (tgWebApp && tgWebApp.initData) {
    try {
      tgWebApp.ready()
      tgWebApp.expand()
      if (tgWebApp.colorScheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark')
      }
    } catch {
      // no-op
    }
    return { telegram_init_data: tgWebApp.initData }
  }

  if (externalToken) {
    return { external_token: externalToken }
  }

  // Manager mode — dashboard API key from URL
  const managerKey = getQueryParam('manager_key')
  if (managerKey) {
    return { manager_key: managerKey }
  }

  // Guest mode — use guest_id from URL if provided, otherwise localStorage (persists across tabs)
  const urlGuestId = getQueryParam('guest_id')
  if (urlGuestId) {
    localStorage.setItem('eurika_guest_id', urlGuestId)
    return { guest_id: urlGuestId }
  }
  let guestId = localStorage.getItem('eurika_guest_id') || sessionStorage.getItem('eurika_guest_id')
  if (!guestId) {
    guestId = crypto.randomUUID()
  }
  localStorage.setItem('eurika_guest_id', guestId)
  return { guest_id: guestId }
}
