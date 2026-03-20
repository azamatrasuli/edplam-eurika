export function PaymentCard({ data }) {
  const { product_name, amount_rub, payment_url } = data || {}
  const formatted = amount_rub != null ? new Intl.NumberFormat('ru-RU').format(amount_rub) : '—'

  return (
    <div className="rounded-2xl border border-brand/20 bg-gradient-to-br from-elevated to-brand/3 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <svg className="w-5 h-5 text-brand" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
          <line x1="1" y1="10" x2="23" y2="10" />
        </svg>
        <span className="font-medium text-sm">Оплата обучения</span>
      </div>
      <div>
        <p className="text-[15px] font-medium">{product_name || 'Продукт'}</p>
        <p className="text-xl font-bold text-brand mt-1">{formatted} <span className="text-lg font-normal">&#8381;</span></p>
      </div>
      <div className="border-t border-brand/10 pt-3">
        {payment_url ? (
          <a
            href={payment_url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-center gap-2 w-full text-center py-2.5 rounded-xl bg-brand !text-white font-medium no-underline shadow-sm hover:bg-brand-hover hover:shadow-md transition-all"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            Оплатить
          </a>
        ) : (
          <button
            disabled
            className="w-full py-2.5 rounded-xl bg-inset text-fg-tertiary font-medium cursor-not-allowed"
          >
            Ссылка недоступна
          </button>
        )}
      </div>
    </div>
  )
}
