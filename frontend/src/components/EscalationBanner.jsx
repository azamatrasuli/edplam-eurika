export function EscalationBanner({ active = false, reason = '' }) {
  if (!active) return null
  return (
    <div className="flex items-start gap-3 px-4 py-3 mx-3 sm:mx-5 rounded-xl bg-escalation text-escalation-fg border border-escalation-border text-sm leading-normal shrink-0">
      <div className="w-8 h-8 rounded-lg bg-escalation-icon flex items-center justify-center shrink-0 text-base">
        👋
      </div>
      <div>
        <strong className="block mb-0.5">Диалог передан менеджеру</strong>
        {reason && <p className="mt-1 opacity-85">Причина: {reason}</p>}
        <p className="mt-1 opacity-85">Менеджер свяжется с вами в ближайшее время.</p>
      </div>
    </div>
  )
}
