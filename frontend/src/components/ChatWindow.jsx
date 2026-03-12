import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { OnboardingMessage } from './OnboardingMessage'

export function ChatWindow({ messages, avatarProps, typing, onButtonClick, onFormSubmit }) {
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

  const visibleMessages = messages.filter((m) => m.content !== '' || m.type === 'buttons' || m.type === 'form' || m.type === 'card')

  return (
    <div
      className="flex-1 overflow-y-auto overflow-x-hidden flex flex-col gap-1 px-3 py-4 sm:px-5 scroll-smooth"
      ref={containerRef}
      onScroll={handleScroll}
    >
      {visibleMessages.map((message) => {
        const isSpecial = message.type && message.type !== 'text'

        return (
          <div
            key={message.id}
            className={`flex items-end gap-2 mt-1 opacity-0 animate-[message-in_0.3s_ease_forwards] ${
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
              ) : message.role === 'assistant' ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              ) : (
                message.content
              )}
            </div>
          </div>
        )
      })}

      {typing && (
        <div className="flex items-end gap-2 mt-1 opacity-0 animate-[message-in_0.3s_ease_forwards] justify-start">
          {avatarProps && (
            <img
              className="w-7 h-7 rounded-full object-cover shrink-0 self-end bg-surface-alt"
              alt=""
              {...avatarProps}
            />
          )}
          <div className="flex items-center gap-[5px] bg-card px-4 py-3 rounded-2xl rounded-tl-[2px] shadow-card">
            <span className="w-[7px] h-[7px] rounded-full bg-dot animate-[typing-bounce_1.2s_infinite_ease-in-out]" />
            <span className="w-[7px] h-[7px] rounded-full bg-dot animate-[typing-bounce_1.2s_infinite_ease-in-out] [animation-delay:0.15s]" />
            <span className="w-[7px] h-[7px] rounded-full bg-dot animate-[typing-bounce_1.2s_infinite_ease-in-out] [animation-delay:0.3s]" />
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
