import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  archiveConversation as apiArchive,
  listConversations,
  renameConversation as apiRename,
  searchConversations,
} from '../api/client'

export function useConversationList(auth, agentRole = 'sales') {
  const [conversations, setConversations] = useState([])
  const [total, setTotal] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [activeId, setActiveId] = useState(null)
  const offsetRef = useRef(0)

  const load = useCallback(async (reset = false) => {
    if (!auth) return
    setLoading(true)
    try {
      const offset = reset ? 0 : offsetRef.current
      const data = await listConversations(auth, agentRole, { offset, limit: 20 })
      if (reset) {
        setConversations(data.conversations)
      } else {
        setConversations((prev) => [...prev, ...data.conversations])
      }
      setTotal(data.total)
      setHasMore(data.has_more)
      offsetRef.current = offset + data.conversations.length
    } catch (e) {
      console.error('Failed to load conversations:', e)
    } finally {
      setLoading(false)
    }
  }, [auth, agentRole])

  // Initial load
  useEffect(() => {
    load(true)
  }, [load])

  const loadMore = useCallback(() => {
    if (hasMore && !loading) load(false)
  }, [hasMore, loading, load])

  const refresh = useCallback(() => {
    offsetRef.current = 0
    load(true)
  }, [load])

  const search = useCallback(async (query) => {
    setSearchQuery(query)
    if (!query || query.length < 2) {
      load(true)
      return
    }
    setLoading(true)
    try {
      const data = await searchConversations(auth, query, agentRole)
      setConversations(data.conversations)
      setTotal(data.total)
      setHasMore(false)
    } catch (e) {
      console.error('Failed to search conversations:', e)
    } finally {
      setLoading(false)
    }
  }, [auth, agentRole, load])

  const archive = useCallback(async (conversationId) => {
    try {
      await apiArchive(conversationId, auth)
      setConversations((prev) => prev.filter((c) => c.id !== conversationId))
      setTotal((prev) => prev - 1)
      if (activeId === conversationId) setActiveId(null)
    } catch (e) {
      console.error('Failed to archive conversation:', e)
    }
  }, [auth, activeId])

  const rename = useCallback(async (conversationId, title) => {
    try {
      await apiRename(conversationId, title, auth)
      setConversations((prev) =>
        prev.map((c) => (c.id === conversationId ? { ...c, title } : c)),
      )
    } catch (e) {
      console.error('Failed to rename conversation:', e)
    }
  }, [auth])

  // Add new conversation to the top of the list
  const addConversation = useCallback((conv) => {
    setConversations((prev) => [conv, ...prev])
    setTotal((prev) => prev + 1)
    setActiveId(conv.id)
  }, [])

  return useMemo(() => ({
    conversations,
    total,
    hasMore,
    loading,
    searchQuery,
    activeId,
    setActiveId,
    load: refresh,
    loadMore,
    search,
    archive,
    rename,
    addConversation,
  }), [conversations, total, hasMore, loading, searchQuery, activeId, refresh, loadMore, search, archive, rename, addConversation])
}
