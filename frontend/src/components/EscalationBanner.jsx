export function EscalationBanner({ active = false, reason = '' }) {
  if (!active) return null
  return (
    <div className="escalation-banner">
      <strong>Диалог передан менеджеру.</strong>
      {reason && <p>Причина: {reason}</p>}
      <p>Менеджер свяжется с вами в ближайшее время. Новые сообщения от Эврики временно отключены.</p>
    </div>
  )
}
