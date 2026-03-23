import { useCallback, useEffect, useState } from 'react'
import { fetchConversations, fetchConversationMessages } from '../api/dashboard'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function getKey() {
  const hash = window.location.hash
  const q = hash.includes('?') ? hash.split('?')[1] : ''
  const params = new URLSearchParams(q)
  const key = params.get('key') || new URLSearchParams(window.location.search).get('key')
  if (key) sessionStorage.setItem('dashboard_key', key)
  return key || sessionStorage.getItem('dashboard_key') || ''
}

export function SupervisorPage() {
  const [conversations, setConversations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedConv, setSelectedConv] = useState(null)
  const [messages, setMessages] = useState([])
  const [messagesLoading, setMessagesLoading] = useState(false)
  const [filter, setFilter] = useState({ status: '', channel: '', agent_role: '' })

  const key = getKey()

  const loadConversations = useCallback(async () => {
    if (!key) { setError('API-ключ не указан. Добавьте ?key=... в URL'); setLoading(false); return }
    setLoading(true)
    try {
      const data = await fetchConversations({
        status: filter.status || undefined,
        channel: filter.channel || undefined,
        agent_role: filter.agent_role || undefined,
        per_page: 50,
      })
      setConversations(data.items || [])
      setError('')
    } catch (e) {
      setError(e.message)
    }
    setLoading(false)
  }, [key, filter])

  useEffect(() => { loadConversations() }, [loadConversations])

  // Auto-refresh every 10 seconds
  useEffect(() => {
    const interval = setInterval(loadConversations, 10000)
    return () => clearInterval(interval)
  }, [loadConversations])

  const loadMessages = useCallback(async (convId, showLoading = false) => {
    if (showLoading) setMessagesLoading(true)
    try {
      const data = await fetchConversationMessages(convId)
      setMessages(data.messages || [])
    } catch {
      setMessages([])
    }
    if (showLoading) setMessagesLoading(false)
  }, [])

  const openConversation = useCallback(async (conv) => {
    setSelectedConv(conv)
    await loadMessages(conv.id, true)
  }, [loadMessages])

  // Auto-refresh messages for selected conversation every 3 seconds
  useEffect(() => {
    if (!selectedConv) return
    const interval = setInterval(() => loadMessages(selectedConv.id), 3000)
    return () => clearInterval(interval)
  }, [selectedConv, loadMessages])

  if (!key) {
    return (
      <div className="flex items-center justify-center h-dvh bg-[#0d1117] text-white">
        <div className="text-center">
          <h2 className="text-xl font-bold mb-2">Supervisor</h2>
          <p className="text-gray-400">Добавьте <code>?key=API_KEY</code> в URL</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-dvh bg-[#0d1117] text-white">
      {/* Left: Conversation List */}
      <div className="w-[380px] border-r border-gray-800 flex flex-col shrink-0">
        <div className="p-4 border-b border-gray-800">
          <h1 className="text-lg font-bold mb-3">Supervisor</h1>
          <div className="flex gap-2 text-xs">
            <select value={filter.status} onChange={(e) => setFilter((f) => ({ ...f, status: e.target.value }))} className="bg-gray-800 rounded px-2 py-1 text-gray-300">
              <option value="">Все статусы</option>
              <option value="active">Активные</option>
              <option value="escalated">Эскалация</option>
            </select>
            <select value={filter.agent_role} onChange={(e) => setFilter((f) => ({ ...f, agent_role: e.target.value }))} className="bg-gray-800 rounded px-2 py-1 text-gray-300">
              <option value="">Все роли</option>
              <option value="sales">Продажи</option>
              <option value="support">Поддержка</option>
              <option value="teacher">Учитель</option>
            </select>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading && <div className="p-4 text-gray-500 text-sm">Загрузка...</div>}
          {error && <div className="p-4 text-red-400 text-sm">{error}</div>}
          {conversations.map((conv) => (
            <button
              key={conv.id}
              onClick={() => openConversation(conv)}
              className={`w-full text-left p-3 border-b border-gray-800/50 hover:bg-gray-800/50 transition-colors ${
                selectedConv?.id === conv.id ? 'bg-gray-800/70' : ''
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className={`w-2 h-2 rounded-full shrink-0 ${
                  conv.status === 'escalated' ? 'bg-red-500' : conv.status === 'active' ? 'bg-green-500' : 'bg-gray-500'
                }`} />
                <span className="text-sm font-medium truncate">{conv.display_name || conv.actor_id}</span>
                <span className="text-[10px] text-gray-500 ml-auto shrink-0">
                  {conv.agent_role === 'support' ? 'КС' : conv.agent_role === 'teacher' ? 'УЧ' : 'ПР'}
                </span>
              </div>
              <div className="text-xs text-gray-400 truncate">{conv.channel} · {conv.message_count || 0} сообщ.</div>
              {conv.has_payment && (
                <span className="text-[10px] px-1 rounded bg-green-900/40 text-green-400 mt-1 inline-block">
                  {conv.payment_status === 'paid' ? 'Оплачено' : 'Ожидает оплаты'}
                </span>
              )}
            </button>
          ))}
          {!loading && conversations.length === 0 && (
            <div className="p-4 text-gray-500 text-sm text-center">Нет разговоров</div>
          )}
        </div>
      </div>

      {/* Right: Conversation Detail */}
      <div className="flex-1 flex flex-col">
        {!selectedConv ? (
          <div className="flex-1 flex items-center justify-center text-gray-500">
            Выберите разговор слева
          </div>
        ) : (
          <>
            <div className="p-4 border-b border-gray-800 flex items-center gap-3">
              <div>
                <div className="font-medium">{selectedConv.display_name || selectedConv.actor_id}</div>
                <div className="text-xs text-gray-400">
                  {selectedConv.channel} · {selectedConv.agent_role} · {selectedConv.status}
                  {selectedConv.status === 'escalated' && ' (эскалация)'}
                </div>
              </div>
              <a
                href={`/#/?conv=${selectedConv.id}&manager_key=${key}&role=${selectedConv.agent_role || 'sales'}`}
                target="_blank"
                rel="noreferrer"
                className="ml-auto px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 transition-colors"
              >
                💬 Подключиться
              </a>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {messagesLoading && <div className="text-gray-500 text-sm">Загрузка сообщений...</div>}
              {messages.map((msg, i) => {
                const isManager = msg.metadata?.source === 'manager'
                const isUser = msg.role === 'user'
                return (
                  <div key={i} className="flex items-start gap-2">
                    <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${
                      isUser ? 'bg-emerald-600 text-white'
                        : isManager ? 'bg-blue-600 text-white'
                        : 'bg-gray-700 text-gray-300'
                    }`}>
                      {isUser ? 'К' : isManager ? 'М' : 'Э'}
                    </div>
                    <div className={`flex-1 px-3 py-2 rounded-xl text-sm ${
                      isUser ? 'bg-emerald-900/30 border border-emerald-800/50'
                        : isManager ? 'bg-blue-900/30 border border-blue-800/50'
                        : 'bg-gray-800/50'
                    }`}>
                      <div className="text-[10px] text-gray-500 mb-0.5">
                        {isUser ? 'Клиент' : isManager ? (msg.metadata?.sender_name || 'Менеджер') : 'Эврика'}
                        {msg.created_at && ` · ${new Date(msg.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`}
                      </div>
                      <ReactMarkdown remarkPlugins={[remarkGfm]} className="prose-sm prose-invert max-w-none">
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
