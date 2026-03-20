export function MetricCard({ label, value, suffix = '' }) {
  return (
    <div className="rounded-xl border border-border-subtle bg-elevated p-4 min-w-[140px] hover:shadow-sm hover:-translate-y-px transition-all duration-200">
      <p className="text-[13px] text-fg-muted mb-1">{label}</p>
      <p className="text-2xl font-bold text-fg">
        {value}{suffix && <span className="text-sm font-normal ml-0.5">{suffix}</span>}
      </p>
    </div>
  )
}
