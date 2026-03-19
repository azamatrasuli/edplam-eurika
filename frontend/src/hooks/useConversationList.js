import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  archiveConversation as apiArchive,
  deleteConversation as apiDelete,
  listConversations,
  renameConversation as apiRename,
  searchConversations,
  unarchiveConversation as apiUnarchive,
} from '../api/client'

export function useConversationList(auth, agentRole = 'sales', { onError } = {}) {
  const [conversations, setConversations] = useState([])
  const [total, setTotal] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [activeId, setActiveId] = useState(null)
  const offsetRef = useRef(0)

  // Undo archive state
  const [archiveToast, setArchiveToast] = useState(null) // { id, conversation, title }
  const undoTimerRef = useRef(null)

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
      onError?.('Не удалось загрузить историю диалогов')
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
      onError?.('Поиск не удался. Попробуйте ещё раз')
    } finally {
      setLoading(false)
    }
  }, [auth, agentRole, load])

  const archive = useCallback(async (conversationId) => {
    // Save conversation data for undo
    const conv = conversations.find((c) => c.id === conversationId)
    const convIndex = conversations.findIndex((c) => c.id === conversationId)

    // Optimistically remove from list
    setConversations((prev) => prev.filter((c) => c.id !== conversationId))
    setTotal((prev) => prev - 1)

    const wasActive = activeId === conversationId
    if (wasActive) setActiveId(null)

    try {
      await apiArchive(conversationId, auth)

      // Show toast with undo
      clearTimeout(undoTimerRef.current)
      setArchiveToast({
        id: conversationId,
        conversation: conv,
        index: convIndex,
        title: conv?.title || conv?.last_user_message || null,
        wasActive,
      })
    } catch (e) {
      // Restore on failure
      console.error('Failed to archive conversation:', e)
      onError?.('Не удалось архивировать диалог')
      if (conv) {
        setConversations((prev) => {
          const next = [...prev]
          next.splice(convIndex, 0, conv)
          return next
        })
        setTotal((prev) => prev + 1)
        if (wasActive) setActiveId(conversationId)
      }
    }
  }, [auth, activeId, conversations])

  const undoArchive = useCallback(async () => {
    if (!archiveToast) return

    const { id, conversation, index, wasActive } = archiveToast
    setArchiveToast(null)
    clearTimeout(undoTimerRef.current)

    try {
      await apiUnarchive(id, auth)
      // Restore to original position
      setConversations((prev) => {
        const next = [...prev]
        const insertAt = Math.min(index, next.length)
        next.splice(insertAt, 0, conversation)
        return next
      })
      setTotal((prev) => prev + 1)
      if (wasActive) setActiveId(id)
    } catch (e) {
      console.error('Failed to unarchive conversation:', e)
      onError?.('Не удалось восстановить диалог')
    }
  }, [auth, archiveToast])

  const dismissArchiveToast = useCallback(() => {
    setArchiveToast(null)
  }, [])

  const deleteConversation = useCallback(async (conversationId) => {
    const conv = conversations.find((c) => c.id === conversationId)
    const convIndex = conversations.findIndex((c) => c.id === conversationId)

    // Optimistically remove
    setConversations((prev) => prev.filter((c) => c.id !== conversationId))
    setTotal((prev) => prev - 1)
    if (activeId === conversationId) setActiveId(null)

    try {
      await apiDelete(conversationId, auth)
    } catch (e) {
      console.error('Failed to delete conversation:', e)
      onError?.('Не удалось удалить диалог')
      // Restore on failure
      if (conv) {
        setConversations((prev) => {
          const next = [...prev]
          next.splice(convIndex, 0, conv)
          return next
        })
        setTotal((prev) => prev + 1)
      }
    }
  }, [auth, activeId, conversations])

  const rename = useCallback(async (conversationId, title) => {
    try {
      await apiRename(conversationId, title, auth)
      setConversations((prev) =>
        prev.map((c) => (c.id === conversationId ? { ...c, title } : c)),
      )
    } catch (e) {
      console.error('Failed to rename conversation:', e)
      onError?.('Не удалось переименовать диалог')
    }
  }, [auth])

  // Add new conversation to the top of the list
  const addConversation = useCallback((conv) => {
    setConversations((prev) => [conv, ...prev])
    setTotal((prev) => prev + 1)
    setActiveId(conv.id)
  }, [])

  // Update title reactively (from SSE stream)
  const updateTitle = useCallback((conversationId, title) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === conversationId ? { ...c, title } : c)),
    )
  }, [])

  // Update sidebar metadata after message send (message count, last user message, timestamp)
  const bumpConversation = useCallback((conversationId, userText) => {
    setConversations((prev) => {
      const updated = prev.map((c) => {
        if (c.id !== conversationId) return c
        return {
          ...c,
          message_count: (c.message_count || 0) + 2,
          last_user_message: userText,
          updated_at: new Date().toISOString(),
        }
      })
      // Move to top
      const idx = updated.findIndex((c) => c.id === conversationId)
      if (idx > 0) {
        const [conv] = updated.splice(idx, 1)
        updated.unshift(conv)
      }
      return updated
    })
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
    undoArchive,
    archiveToast,
    dismissArchiveToast,
    deleteConversation,
    rename,
    addConversation,
    updateTitle,
    bumpConversation,
  }), [conversations, total, hasMore, loading, searchQuery, activeId, refresh, loadMore, search, archive, undoArchive, archiveToast, dismissArchiveToast, deleteConversation, rename, addConversation, updateTitle, bumpConversation])
}
