export function EscalationBanner({ active = false, reason = '' }) {
  if (!active) return null
  return (
    <div className="escalation-enter flex items-start gap-3 px-4 py-3 mx-3 sm:mx-5 mt-1 rounded-xl bg-gradient-to-r from-accent-warm-subtle to-transparent border-l-[3px] border-accent-warm text-escalation-fg text-sm leading-normal shrink-0">
      <div className="w-8 h-8 rounded-lg bg-accent-warm/10 flex items-center justify-center shrink-0 text-accent-warm">
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M15.05 5A5 5 0 0 1 19 8.95M15.05 1A9 9 0 0 1 23 8.94m-1 7.98v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
        </svg>
      </div>
      <div>
        <span className="block font-semibold mb-0.5">Диалог передан менеджеру</span>
        {reason && <p className="mt-1 opacity-85">Причина: {reason}</p>}
        <p className="mt-1 opacity-85">Менеджер свяжется с вами в ближайшее время.</p>
      </div>
    </div>
  )
}
