export function PaymentCard({ data }) {
  const { product_name, amount_rub, payment_url } = data || {}
  const formatted = amount_rub != null ? new Intl.NumberFormat('ru-RU').format(amount_rub) : '—'

  return (
    <div className="rounded-xl border border-brand/20 bg-surface p-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-lg">&#128179;</span>
        <span className="font-medium text-sm">Oплата обучения</span>
      </div>
      <div>
        <p className="text-[15px] font-medium">{product_name || 'Продукт'}</p>
        <p className="text-xl font-bold text-brand mt-1">{formatted} &#8381;</p>
      </div>
      {payment_url ? (
        <a
          href={payment_url}
          target="_blank"
          rel="noreferrer"
          className="block w-full text-center py-2.5 rounded-lg bg-brand !text-white font-medium no-underline hover:opacity-90 transition"
        >
          Оплатить
        </a>
      ) : (
        <button
          disabled
          className="w-full py-2.5 rounded-lg bg-gray-200 text-gray-400 font-medium cursor-not-allowed"
        >
          Ссылка недоступна
        </button>
      )}
    </div>
  )
}
