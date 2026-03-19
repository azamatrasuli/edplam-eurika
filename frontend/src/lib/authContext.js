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

export function getAgentRole() {
  const role = getQueryParam('role')
  return role === 'support' ? 'support' : 'sales'
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

  // Guest mode — anonymous access, agent qualifies in conversation
  let guestId = sessionStorage.getItem('eurika_guest_id')
  if (!guestId) {
    guestId = crypto.randomUUID()
    sessionStorage.setItem('eurika_guest_id', guestId)
  }
  return { guest_id: guestId }
}
