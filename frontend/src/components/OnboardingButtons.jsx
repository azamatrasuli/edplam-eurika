export function OnboardingButtons({ buttons, disabled, onSelect }) {
  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {buttons.map((btn) => (
        <button
          key={btn.id}
          onClick={() => !disabled && onSelect(btn.value)}
          disabled={disabled}
          className={`
            px-4 py-2.5 rounded-xl text-[14px] font-medium leading-tight
            transition-all duration-200 ease-out
            ${
              disabled
                ? 'bg-inset text-fg-tertiary cursor-default opacity-60'
                : 'bg-brand text-white cursor-pointer hover:bg-brand-hover active:scale-[0.97] shadow-sm hover:shadow-md'
            }
          `}
        >
          {btn.label}
        </button>
      ))}
    </div>
  )
}
