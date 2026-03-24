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

  // Archived conversations (reactive)
  const [archivedConvs, setArchivedConvs] = useState([])
  const [archivedLoading, setArchivedLoading] = useState(false)
  const archivedLoadedRef = useRef(false)

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

  // Load archived conversations
  const loadArchived = useCallback(async () => {
    if (!auth) return
    setArchivedLoading(true)
    try {
      const data = await listConversations(auth, agentRole, { offset: 0, limit: 50, includeArchived: true })
      setArchivedConvs(data.conversations.filter((c) => c.archived_at))
      archivedLoadedRef.current = true
    } catch (e) {
      console.error('Failed to load archived:', e)
      onError?.('Не удалось загрузить архив')
    } finally {
      setArchivedLoading(false)
    }
  }, [auth, agentRole])

  const archive = useCallback(async (conversationId) => {
    // Save conversation data for undo
    const conv = conversations.find((c) => c.id === conversationId)
    const convIndex = conversations.findIndex((c) => c.id === conversationId)

    // Optimistically remove from active list
    setConversations((prev) => prev.filter((c) => c.id !== conversationId))
    setTotal((prev) => prev - 1)

    // Optimistically add to archived list (if loaded)
    if (conv) {
      const archivedCopy = { ...conv, archived_at: new Date().toISOString() }
      setArchivedConvs((prev) => [archivedCopy, ...prev])
    }

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
        setConversations((prev) => [conv, ...prev])
        setTotal((prev) => prev + 1)
        setArchivedConvs((prev) => prev.filter((c) => c.id !== conversationId))
        if (wasActive) setActiveId(conversationId)
      }
    }
  }, [auth, activeId, conversations])

  const undoArchive = useCallback(async () => {
    if (!archiveToast) return

    const { id, conversation, index, wasActive } = archiveToast
    setArchiveToast(null)
    clearTimeout(undoTimerRef.current)

    // Optimistically remove from archived, add back to active
    setArchivedConvs((prev) => prev.filter((c) => c.id !== id))

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
      // Restore archived entry on failure
      if (conversation) {
        setArchivedConvs((prev) => [{ ...conversation, archived_at: conversation.archived_at || new Date().toISOString() }, ...prev])
      }
    }
  }, [auth, archiveToast])

  // Unarchive from archive list (restore to active)
  const unarchiveFromList = useCallback(async (conversationId) => {
    const conv = archivedConvs.find((c) => c.id === conversationId)

    // Optimistically move
    setArchivedConvs((prev) => prev.filter((c) => c.id !== conversationId))

    try {
      await apiUnarchive(conversationId, auth)
      if (conv) {
        const restored = { ...conv, archived_at: null }
        setConversations((prev) => [restored, ...prev])
        setTotal((prev) => prev + 1)
      }
    } catch (e) {
      console.error('Failed to unarchive:', e)
      onError?.('Не удалось восстановить диалог')
      if (conv) setArchivedConvs((prev) => [conv, ...prev])
    }
  }, [auth, archivedConvs])

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
      if (conv) {
        setConversations((prev) => [conv, ...prev])
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
      const exists = prev.some((c) => c.id === conversationId)
      if (!exists) {
        // Race condition: conversation was created after the list was fetched — add it now
        return [{
          id: conversationId,
          title: null,
          agent_role: agentRole,
          message_count: 2,
          last_user_message: userText,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          archived_at: null,
        }, ...prev]
      }
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
  }, [agentRole])

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
    archivedConvs,
    archivedLoading,
    loadArchived,
    unarchiveFromList,
  }), [conversations, total, hasMore, loading, searchQuery, activeId, refresh, loadMore, search, archive, undoArchive, archiveToast, dismissArchiveToast, deleteConversation, rename, addConversation, updateTitle, bumpConversation, archivedConvs, archivedLoading, loadArchived, unarchiveFromList])
}
