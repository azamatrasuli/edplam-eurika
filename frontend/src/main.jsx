import React from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './styles.css'

// Telegram Mini App passes params in the hash (#tgWebAppData=...).
// HashRouter also uses the hash for routing (#/).
// The Telegram WebApp SDK (telegram-web-app.js loaded in index.html)
// has already read and stored these params by this point.
// Reset the hash to a valid route so HashRouter can work.
if (window.location.hash && !window.location.hash.startsWith('#/')) {
  history.replaceState(null, '', window.location.pathname + window.location.search + '#/')
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
