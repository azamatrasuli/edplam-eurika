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

// --- Mutable auth state for postMessage updates ---
let _portalToken = null
let _agentRoleOverride = null
let _onAuthRevoked = null
let _onRoleChanged = null

/**
 * Register callbacks for portal postMessage events.
 * Called from ChatPage or App on mount.
 */
export function registerPortalBridge({ onAuthRevoked, onRoleChanged } = {}) {
  _onAuthRevoked = onAuthRevoked || null
  _onRoleChanged = onRoleChanged || null
}

/**
 * Get the current portal token (may be updated via postMessage).
 */
export function getPortalToken() {
  return _portalToken
}

/**
 * Get role override set by postMessage, or null.
 */
export function getAgentRoleOverride() {
  return _agentRoleOverride
}

// Listen for postMessage from portal parent (iframe embedding)
if (typeof window !== 'undefined' && window.parent !== window) {
  window.addEventListener('message', (event) => {
    const data = event.data
    if (!data || typeof data.type !== 'string' || !data.type.startsWith('eurika:')) return

    switch (data.type) {
      case 'eurika:token-refresh':
        if (data.payload?.token) {
          _portalToken = data.payload.token
        }
        break

      case 'eurika:auth-revoked':
        _portalToken = null
        if (_onAuthRevoked) _onAuthRevoked()
        break

      case 'eurika:role-change':
        if (data.payload?.role) {
          _agentRoleOverride = data.payload.role
          if (_onRoleChanged) _onRoleChanged(data.payload.role)
        }
        break
    }
  })
}

export function buildAuthPayload() {
  // Use refreshed token if available (from postMessage)
  const portalToken = _portalToken || getQueryParam('token')
  const externalToken = getQueryParam('t')

  if (portalToken) {
    _portalToken = portalToken // store for future refreshes
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
