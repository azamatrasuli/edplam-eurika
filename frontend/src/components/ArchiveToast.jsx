import { useEffect, useRef, useState } from 'react'

const TOAST_DURATION = 5000

export function ArchiveToast({ visible, title, onUndo, onDismiss }) {
  const [progress, setProgress] = useState(100)
  const [exiting, setExiting] = useState(false)
  const timerRef = useRef(null)
  const startRef = useRef(null)
  const rafRef = useRef(null)

  useEffect(() => {
    if (!visible) {
      setProgress(100)
      setExiting(false)
      return
    }

    startRef.current = Date.now()

    // Animate progress bar
    function tick() {
      const elapsed = Date.now() - startRef.current
      const remaining = Math.max(0, 100 - (elapsed / TOAST_DURATION) * 100)
      setProgress(remaining)
      if (remaining > 0) {
        rafRef.current = requestAnimationFrame(tick)
      }
    }
    rafRef.current = requestAnimationFrame(tick)

    // Auto-dismiss
    timerRef.current = setTimeout(() => {
      setExiting(true)
      setTimeout(() => onDismiss(), 300)
    }, TOAST_DURATION)

    return () => {
      clearTimeout(timerRef.current)
      cancelAnimationFrame(rafRef.current)
    }
  }, [visible, onDismiss])

  function handleUndo() {
    clearTimeout(timerRef.current)
    cancelAnimationFrame(rafRef.current)
    setExiting(true)
    setTimeout(() => onUndo(), 150)
  }

  if (!visible) return null

  return (
    <div
      className={`fixed bottom-[calc(80px+env(safe-area-inset-bottom,0px))] left-1/2 -translate-x-1/2 z-50 w-[calc(100%-32px)] max-w-sm ${
        exiting ? 'toast-exit' : 'toast-enter'
      }`}
    >
      <div className="relative overflow-hidden rounded-2xl bg-[#1f1f23] shadow-lg backdrop-blur-md border border-white/[0.08]">
        {/* Progress bar */}
        <div className="absolute top-0 left-0 h-[2px] bg-brand/80 transition-none"
          style={{ width: `${progress}%` }}
        />

        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#62ba99" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
              <polyline points="21 8 21 21 3 21 3 8" />
              <rect x="1" y="3" width="22" height="5" />
              <line x1="10" y1="12" x2="14" y2="12" />
            </svg>
            <span className="text-sm text-white/90 truncate">
              {title ? `"${title}" ` : 'Чат '}архивирован
            </span>
          </div>

          <button
            onClick={handleUndo}
            className="shrink-0 px-3 py-1 text-sm font-semibold text-brand hover:text-brand-light rounded-lg hover:bg-white/[0.06] transition-colors active:scale-95"
          >
            Отменить
          </button>
        </div>
      </div>
    </div>
  )
}
