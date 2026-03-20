export function FilterBar({ dateFrom, dateTo, channel, onDateFrom, onDateTo, onChannel, onPreset }) {
  const presets = [
    { label: 'Сегодня', days: 0 },
    { label: '7 дней', days: 7 },
    { label: '30 дней', days: 30 },
  ]

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex gap-1.5">
        {presets.map((p) => (
          <button
            key={p.days}
            onClick={() => onPreset(p.days)}
            className="px-3 py-1.5 text-[13px] rounded-lg border border-border-subtle bg-elevated text-fg hover:bg-brand-subtle hover:text-brand hover:border-brand/30 transition-colors cursor-pointer"
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1.5 text-[13px]">
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => onDateFrom(e.target.value)}
          className="px-2 py-1.5 rounded-lg border border-border-subtle bg-elevated text-fg text-[13px]"
        />
        <span className="text-fg-muted">—</span>
        <input
          type="date"
          value={dateTo}
          onChange={(e) => onDateTo(e.target.value)}
          className="px-2 py-1.5 rounded-lg border border-border-subtle bg-elevated text-fg text-[13px]"
        />
      </div>

      <select
        value={channel}
        onChange={(e) => onChannel(e.target.value)}
        className="px-3 py-1.5 rounded-lg border border-border-subtle bg-elevated text-fg text-[13px]"
      >
        <option value="">Все каналы</option>
        <option value="portal">Портал</option>
        <option value="telegram">Telegram</option>
        <option value="external">Внешняя ссылка</option>
      </select>
    </div>
  )
}
