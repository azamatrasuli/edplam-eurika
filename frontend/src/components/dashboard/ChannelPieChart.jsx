import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'

const CHANNEL_LABELS = {
  portal: 'Портал',
  telegram: 'Telegram',
  external: 'Внешняя ссылка',
}

const COLORS = ['#2d8f73', '#5bb89a', '#f59e0b', '#6b7280']

export function ChannelPieChart({ channels }) {
  if (!channels || Object.keys(channels).length === 0) {
    return <p className="text-[13px] text-fg-muted py-4">Нет данных</p>
  }

  const data = Object.entries(channels).map(([name, value]) => ({
    name: CHANNEL_LABELS[name] || name,
    value,
  }))

  return (
    <div className="rounded-xl border border-border-subtle bg-elevated p-4">
      <h3 className="text-sm font-medium text-fg mb-3">Каналы</h3>
      <div className="flex items-center gap-4">
        <ResponsiveContainer width={160} height={160}>
          <PieChart>
            <Pie data={data} dataKey="value" cx="50%" cy="50%" outerRadius={70} innerRadius={40}>
              {data.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{ fontSize: 13, borderRadius: 8, border: '1px solid var(--border-default, rgba(0,0,0,0.10))' }}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="flex flex-col gap-2">
          {data.map((d, i) => (
            <div key={d.name} className="flex items-center gap-2 text-[13px]">
              <span className="w-3 h-3 rounded-full shrink-0" style={{ background: COLORS[i % COLORS.length] }} />
              <span className="text-fg">{d.name}: {d.value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
