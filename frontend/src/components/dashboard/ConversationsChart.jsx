import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'

export function ConversationsChart({ data }) {
  if (!data || data.length === 0) {
    return <p className="text-[13px] text-fg-muted py-4">Нет данных за выбранный период</p>
  }

  const formatted = data.map((d) => ({
    ...d,
    label: d.date.slice(5), // MM-DD
  }))

  return (
    <div className="rounded-xl border border-border-subtle bg-elevated p-4">
      <h3 className="text-sm font-medium text-fg mb-3">Диалоги по дням</h3>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={formatted}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default, rgba(0,0,0,0.10))" />
          <XAxis dataKey="label" tick={{ fontSize: 12, fill: 'var(--text-secondary, #6b7280)' }} />
          <YAxis tick={{ fontSize: 12, fill: 'var(--text-secondary, #6b7280)' }} allowDecimals={false} />
          <Tooltip
            contentStyle={{ fontSize: 13, borderRadius: 8, border: '1px solid var(--border-default, rgba(0,0,0,0.10))' }}
            formatter={(val) => [val, 'Диалоги']}
          />
          <Bar dataKey="conversations" fill="#2d8f73" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
