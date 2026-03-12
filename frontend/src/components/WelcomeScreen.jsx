export function WelcomeScreen({ subtitle, avatarProps, error }) {
  return (
    <div className="w-full h-dvh flex flex-col items-center justify-center px-5 sm:px-6 pt-[calc(32px+env(safe-area-inset-top,0px))] pb-8 text-center">
      <img
        className="w-22 h-22 rounded-full object-cover mb-6 shadow-avatar opacity-0 animate-[welcome-avatar-in_0.6s_0.1s_ease_forwards]"
        alt="Эврика"
        {...avatarProps}
      />
      <h1 className="text-2xl sm:text-[28px] font-bold text-fg mb-2 opacity-0 animate-[welcome-slide-in_0.5s_0.25s_ease_forwards]">
        Эврика
      </h1>
      <p className="text-[15px] text-fg-muted max-w-[360px] leading-relaxed mb-8 opacity-0 animate-[welcome-slide-in_0.5s_0.35s_ease_forwards]">
        {subtitle || 'Виртуальный менеджер EdPalm. Помогу подобрать обучение и отвечу по программам.'}
      </p>
      {error ? (
        <div className="px-4 py-3 rounded-xl bg-error-bg text-error border border-error-border text-sm leading-normal max-w-sm opacity-0 animate-[welcome-slide-in_0.5s_0.45s_ease_forwards]">
          {error}
        </div>
      ) : (
        <div className="flex gap-2 opacity-0 animate-[welcome-slide-in_0.5s_0.45s_ease_forwards]">
          <span className="w-2.5 h-2.5 rounded-full bg-brand animate-[loader-bounce_1.4s_infinite_ease-in-out_both]" />
          <span className="w-2.5 h-2.5 rounded-full bg-brand animate-[loader-bounce_1.4s_infinite_ease-in-out_both] [animation-delay:0.16s]" />
          <span className="w-2.5 h-2.5 rounded-full bg-brand animate-[loader-bounce_1.4s_infinite_ease-in-out_both] [animation-delay:0.32s]" />
        </div>
      )}
    </div>
  )
}
