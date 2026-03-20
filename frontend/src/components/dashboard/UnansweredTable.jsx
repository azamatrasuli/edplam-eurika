export function UnansweredTable({ data }) {
  const items = data || []

  return (
    <div className="rounded-xl border border-border-subtle bg-elevated p-4">
      <h3 className="text-sm font-medium text-fg mb-3">Незакрытые вопросы</h3>
      {items.length === 0 ? (
        <p className="text-[13px] text-fg-muted">Все вопросы покрыты базой знаний</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border-subtle">
                <th className="text-left py-2 pr-3 font-medium text-fg-muted">Вопрос</th>
                <th className="text-right py-2 pr-3 font-medium text-fg-muted">Раз</th>
                <th className="text-left py-2 font-medium text-fg-muted">Последний</th>
              </tr>
            </thead>
            <tbody>
              {items.map((q, i) => (
                <tr key={i} className="border-b border-border-subtle last:border-0">
                  <td className="py-2 pr-3 text-fg max-w-[300px] truncate">{q.query}</td>
                  <td className="py-2 pr-3 text-right font-medium text-fg">{q.count}</td>
                  <td className="py-2 text-fg-muted">
                    {q.last_seen ? new Date(q.last_seen).toLocaleDateString('ru-RU') : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
