import WebApp from '@twa-dev/sdk'

function getQueryParam(name) {
  const params = new URLSearchParams(window.location.search)
  return params.get(name)
}

export function buildAuthPayload() {
  const portalToken = getQueryParam('token')
  const externalToken = getQueryParam('t')

  if (portalToken) {
    return { portal_token: portalToken }
  }

  if (window.Telegram?.WebApp && WebApp.initData) {
    try {
      WebApp.ready()
      WebApp.expand()
      if (WebApp.colorScheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark')
      }
    } catch {
      // no-op
    }
    return { telegram_init_data: WebApp.initData }
  }

  if (externalToken) {
    return { external_token: externalToken }
  }

  return null
}
