import { useDashboard } from '../hooks/useDashboard'
import { MetricCard } from '../components/dashboard/MetricCard'
import { FilterBar } from '../components/dashboard/FilterBar'
import { ConversationsChart } from '../components/dashboard/ConversationsChart'
import { GmvChart } from '../components/dashboard/GmvChart'
import { ChannelPieChart } from '../components/dashboard/ChannelPieChart'
import { EscalationsTable } from '../components/dashboard/EscalationsTable'
import { UnansweredTable } from '../components/dashboard/UnansweredTable'

function formatNumber(n) {
  if (n == null) return '—'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}

export function DashboardPage() {
  const {
    dateFrom, setDateFrom,
    dateTo, setDateTo,
    channel, setChannel,
    setPreset,
    metrics, conversations, escalations, unanswered,
    loading, error,
  } = useDashboard()

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-alt">
        <div className="text-center p-6">
          <p className="text-lg font-medium text-fg mb-2">Ошибка</p>
          <p className="text-fg-muted text-sm">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-surface-alt">
      <header className="bg-elevated border-b border-border-subtle px-6 py-4">
        <div className="max-w-[1200px] mx-auto flex flex-col gap-3">
          <h1 className="text-lg font-semibold text-fg tracking-tight">Эврика — Дашборд</h1>
          <FilterBar
            dateFrom={dateFrom}
            dateTo={dateTo}
            channel={channel}
            onDateFrom={setDateFrom}
            onDateTo={setDateTo}
            onChannel={setChannel}
            onPreset={setPreset}
          />
        </div>
      </header>

      <main className="max-w-[1200px] mx-auto px-6 py-5 space-y-5">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <span className="text-fg-muted">Загрузка...</span>
          </div>
        ) : (
          <>
            {/* KPI Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <MetricCard label="Диалоги" value={metrics?.conversations?.total ?? 0} />
              <MetricCard label="Конверсия" value={metrics?.conversion?.rate_percent ?? 0} suffix="%" />
              <MetricCard
                label="GMV"
                value={formatNumber(metrics?.gmv?.total_rub)}
                suffix="₽"
              />
              <MetricCard label="Эскалации" value={metrics?.escalations?.total ?? 0} />
            </div>

            {/* Charts Row */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <ConversationsChart data={metrics?.daily} />
              <GmvChart data={metrics?.daily} />
            </div>

            {/* Channel Pie */}
            <ChannelPieChart channels={metrics?.channels} />

            {/* Tables */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <EscalationsTable data={escalations} />
              <UnansweredTable data={unanswered} />
            </div>
          </>
        )}
      </main>
    </div>
  )
}
