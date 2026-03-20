export function EscalationsTable({ data }) {
  const items = data?.items || []

  return (
    <div className="rounded-xl border border-border-subtle bg-elevated p-4">
      <h3 className="text-sm font-medium text-fg mb-3">Эскалации</h3>
      {items.length === 0 ? (
        <p className="text-[13px] text-fg-muted">Нет эскалаций за период</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border-subtle">
                <th className="text-left py-2 pr-3 font-medium text-fg-muted">Причина</th>
                <th className="text-left py-2 pr-3 font-medium text-fg-muted">Канал</th>
                <th className="text-left py-2 font-medium text-fg-muted">Дата</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr key={e.id} className="border-b border-border-subtle last:border-0">
                  <td className="py-2 pr-3 text-fg">{e.reason || '—'}</td>
                  <td className="py-2 pr-3 text-fg-muted">{e.channel || '—'}</td>
                  <td className="py-2 text-fg-muted">
                    {e.created_at ? new Date(e.created_at).toLocaleString('ru-RU') : '—'}
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
