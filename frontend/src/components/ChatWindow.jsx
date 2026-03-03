import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function ChatWindow({ messages }) {
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
  }, [messages])

  return (
    <div className="chat-window" ref={containerRef} onScroll={handleScroll}>
      {messages.map((message) => (
        <div key={message.id} className={`chat-message chat-message--${message.role}`}>
          <div className="chat-bubble">
            {message.role === 'assistant' ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content || '...'}
              </ReactMarkdown>
            ) : (
              message.content || '...'
            )}
          </div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
