export function ProfileCard({ data }) {
  if (!data) return null

  const students = data.students || []
  const fullName = [data.surname, data.name, data.patronymic].filter(Boolean).join(' ')

  return (
    <div className="mt-2 rounded-2xl border border-brand/15 bg-gradient-to-br from-elevated to-brand/5 p-3.5 max-w-[320px]">
      {fullName && (
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[13px] text-fg-muted">Контакт:</span>
          <span className="text-[14px] font-medium text-fg">{fullName}</span>
        </div>
      )}
      {data.phone && (
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[13px] text-fg-muted">Телефон:</span>
          <span className="text-[14px] text-fg">{formatPhone(data.phone)}</span>
        </div>
      )}
      {students.length > 0 && (
        <div className="space-y-1.5 mt-2 pt-2 border-t border-brand/10">
          {students.map((s, i) => (
            <div key={i} className="flex flex-col">
              <span className="text-[14px] font-medium text-fg">{s.fio}</span>
              <span className="text-[13px] text-fg-muted">
                {s.grade ? `${s.grade} класс` : ''}
                {s.product_name ? ` — ${s.product_name}` : ''}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function formatPhone(phone) {
  if (!phone) return ''
  const digits = phone.replace(/\D/g, '')
  if (digits.length === 11 && digits.startsWith('7')) {
    return `+7 ${digits.slice(1, 4)} ${digits.slice(4, 7)}-${digits.slice(7, 9)}-${digits.slice(9)}`
  }
  return phone.startsWith('+') ? phone : `+${phone}`
}
