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
      <div
        className="flex gap-2 overflow-x-auto no-scrollbar"
        style={{ maskImage: 'linear-gradient(to right, black 90%, transparent)', WebkitMaskImage: 'linear-gradient(to right, black 90%, transparent)' }}
      >
        {chips.slice(0, 4).map((chip, i) => (
          <button
            key={chip.value}
            onClick={() => {
              triggerHaptic()
              onSelect(chip.value)
            }}
            className="chip-enter shrink-0 px-3.5 py-2 text-[13px] font-medium rounded-full border border-border-default text-fg bg-transparent hover:border-brand/50 hover:text-brand hover:bg-brand-subtle active:scale-[0.97] transition-all duration-150 whitespace-nowrap cursor-pointer"
            style={{ animationDelay: `${i * 50}ms` }}
            type="button"
          >
            {chip.label}
          </button>
        ))}
      </div>
    </div>
  )
}
