export function SuggestionChips({ chips, onSelect }) {
  if (!chips?.length) return null

  function triggerHaptic() {
    try {
      window.Telegram?.WebApp?.HapticFeedback?.impactOccurred('light')
    } catch {
      // Not in Telegram context
    }
  }

  return (
    <div className="shrink-0 px-5 max-sm:px-3 pb-1 pt-1">
      <div className="flex gap-2 overflow-x-auto no-scrollbar">
        {chips.slice(0, 4).map((chip, i) => (
          <button
            key={chip.value}
            onClick={() => {
              triggerHaptic()
              onSelect(chip.value)
            }}
            className="chip-enter shrink-0 px-3.5 py-2 text-[13px] font-medium rounded-full border border-brand/40 text-brand bg-transparent hover:bg-brand/10 active:scale-[0.96] transition-all duration-150 whitespace-nowrap cursor-pointer"
            style={{ animationDelay: `${i * 60}ms` }}
            type="button"
          >
            {chip.label}
          </button>
        ))}
      </div>
    </div>
  )
}
