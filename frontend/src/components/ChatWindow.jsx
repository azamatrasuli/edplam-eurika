import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { OnboardingMessage } from './OnboardingMessage'

function LoadingSpinner() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <span className="w-7 h-7 border-[2.5px] border-brand/20 border-t-brand rounded-full animate-spin" />
        <span className="text-xs text-fg-muted">Загрузка...</span>
      </div>
    </div>
  )
}

function TTSButton({ messageId, ttsPlayingId, ttsState, onPlay }) {
  const isThis = ttsPlayingId === messageId
  const isLoading = isThis && ttsState === 'loading'
  const isPlaying = isThis && ttsState === 'playing'
  const isPaused = isThis && ttsState === 'paused'

  return (
    <button
      onClick={onPlay}
      className={`w-7 h-7 flex items-center justify-center rounded-full border-none cursor-pointer shrink-0 transition-all duration-200 ${
        isThis
          ? 'bg-brand/10 text-brand opacity-100'
          : 'bg-transparent text-fg-muted opacity-40 sm:opacity-0 sm:group-hover:opacity-100 focus:opacity-100 hover:text-fg hover:bg-black/[0.06] dark:hover:bg-white/[0.08]'
      }`}
      title={isPlaying ? 'Пауза' : isPaused ? 'Продолжить' : 'Озвучить'}
      type="button"
    >
      {isLoading ? (
        <span className="w-3.5 h-3.5 border-2 border-brand border-t-transparent rounded-full animate-spin" />
      ) : isPlaying ? (
        <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
      ) : (
        <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
      )}
    </button>
  )
}

export function ChatWindow({ messages, avatarProps, typing, toolStatus, loading, onButtonClick, onFormSubmit, onTTSPlay, ttsPlayingId, ttsState }) {
  const containerRef = useRef(null)
  const bottomRef = useRef(null)
  const userScrolledUp = useRef(false)

  function handleScroll() {
    const el = containerRef.current
    if (!el) return
    userScrolledUp.current = el.scrollTop + el.clientHeight < el.scrollHeight - 100
  }

  useEffect(() => {
    if (!userScrolledUp.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, typing])

  const visibleMessages = messages.filter((m) => m.content !== '' || m.toolStatus || m.type === 'buttons' || m.type === 'form' || m.type === 'card' || m.type === 'payment')

  return (
    <div
      className="flex-1 overflow-y-auto overflow-x-hidden flex flex-col gap-1 px-3 py-4 sm:px-5 scroll-smooth"
      ref={containerRef}
      onScroll={handleScroll}
    >
      {loading ? (
        <LoadingSpinner />
      ) : (
      <div className="flex flex-col gap-1">
        {visibleMessages.map((message) => {
          const isSpecial = message.type && message.type !== 'text'
          const isPayment = message.type === 'payment'
          const shouldAnimate = !message.fromHistory

          const showTTS = onTTSPlay && message.role === 'assistant' && message.content && !isSpecial

          return (
            <div
              key={message.id}
              className={`group flex items-end gap-2 mt-1 ${
                shouldAnimate ? 'opacity-0 animate-[message-in_0.3s_ease_forwards]' : ''
              } ${
                isPayment ? 'payment-enter' : ''
              } ${
                message.role === 'user' ? 'justify-end' : 'justify-start'
              }`}
            >
              {message.role === 'assistant' && avatarProps && (
                <img
                  className="w-7 h-7 rounded-full object-cover shrink-0 self-end bg-surface-alt"
                  alt=""
                  {...avatarProps}
                />
              )}
              <div
                className={`max-w-[85%] sm:max-w-[75%] px-3.5 py-2.5 text-[15px] leading-normal shadow-card break-words ${
                  message.role === 'user'
                    ? 'bg-card-user text-on-card-user whitespace-pre-wrap rounded-2xl rounded-br-[2px]'
                    : 'bg-card rounded-2xl rounded-tl-[2px] prose-chat'
                }`}
              >
                {isSpecial ? (
                  <OnboardingMessage
                    message={message}
                    onButtonClick={onButtonClick}
                    onFormSubmit={onFormSubmit}
                  />
                ) : message.toolStatus && !message.content ? (
                  <div className="flex items-center gap-2 text-secondary text-sm">
                    <span className="w-2 h-2 rounded-full bg-brand animate-[status-pulse_1.5s_infinite]" />
                    {message.toolStatus}
                  </div>
                ) : message.role === 'assistant' ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {message.content}
                  </ReactMarkdown>
                ) : (
                  message.content
                )}
              </div>
              {showTTS && (
                <TTSButton
                  messageId={message.id}
                  ttsPlayingId={ttsPlayingId}
                  ttsState={ttsState}
                  onPlay={() => onTTSPlay(message.id, message.content)}
                />
              )}
            </div>
          )
        })}
      </div>
      )}

      {typing && (
        <div className="flex items-end gap-2 mt-1 opacity-0 animate-[message-in_0.3s_ease_forwards] justify-start">
          {avatarProps && (
            <img
              className="w-7 h-7 rounded-full object-cover shrink-0 self-end bg-surface-alt"
              alt=""
              {...avatarProps}
            />
          )}
          <div className="bg-card px-4 py-3 rounded-2xl rounded-tl-[2px] shadow-card">
            {toolStatus ? (
              <div className="flex items-center gap-2 text-secondary text-sm">
                <span className="w-2 h-2 rounded-full bg-brand animate-[status-pulse_1.5s_infinite]" />
                {toolStatus}
              </div>
            ) : (
              <div className="flex items-center gap-[5px]">
                <span className="w-[7px] h-[7px] rounded-full bg-dot animate-[typing-bounce_1.2s_infinite_ease-in-out]" />
                <span className="w-[7px] h-[7px] rounded-full bg-dot animate-[typing-bounce_1.2s_infinite_ease-in-out] [animation-delay:0.15s]" />
                <span className="w-[7px] h-[7px] rounded-full bg-dot animate-[typing-bounce_1.2s_infinite_ease-in-out] [animation-delay:0.3s]" />
              </div>
            )}
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
