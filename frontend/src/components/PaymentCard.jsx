export function PaymentCard({ title = 'Оплата', amount = '', url = '' }) {
  return (
    <div className="payment-card" aria-hidden>
      <div>{title}</div>
      <div>{amount}</div>
      {url ? (
        <a href={url} target="_blank" rel="noreferrer">
          Оплатить
        </a>
      ) : (
        <button disabled>Оплатить</button>
      )}
    </div>
  )
}
