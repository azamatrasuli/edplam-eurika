import { useCallback, useRef, useState } from 'react'
import { synthesizeSpeech } from '../api/client'

/**
 * Hook for text-to-speech playback on assistant messages.
 *
 * Returns:
 *   play(messageId, text) — start/pause/resume
 *   stop()               — stop and reset
 *   playingId            — id of the message currently playing (or null)
 *   ttsState             — 'idle' | 'loading' | 'playing' | 'paused'
 */
export function useTTS(auth, { onError } = {}) {
  const [playingId, setPlayingId] = useState(null)
  const [ttsState, setTtsState] = useState('idle')
  const audioRef = useRef(null)
  const cacheRef = useRef(new Map())

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
      audioRef.current = null
    }
    setPlayingId(null)
    setTtsState('idle')
  }, [])

  const play = useCallback(async (messageId, text) => {
    // Toggle pause/resume for the same message
    if (playingId === messageId && audioRef.current) {
      if (ttsState === 'playing') {
        audioRef.current.pause()
        setTtsState('paused')
        return
      }
      if (ttsState === 'paused') {
        audioRef.current.play()
        setTtsState('playing')
        return
      }
    }

    // Stop any current playback before starting new
    stop()

    setPlayingId(messageId)
    setTtsState('loading')

    try {
      // Use cached blob URL if available
      let blobUrl = cacheRef.current.get(messageId)
      if (!blobUrl) {
        const blob = await synthesizeSpeech(text, auth)
        blobUrl = URL.createObjectURL(blob)
        cacheRef.current.set(messageId, blobUrl)
      }

      const audio = new Audio(blobUrl)
      audioRef.current = audio

      audio.onended = () => {
        setPlayingId(null)
        setTtsState('idle')
        audioRef.current = null
      }

      audio.onerror = () => {
        setPlayingId(null)
        setTtsState('idle')
        audioRef.current = null
      }

      await audio.play()
      setTtsState('playing')
    } catch {
      setPlayingId(null)
      setTtsState('idle')
      onError?.('Не удалось воспроизвести голос. Попробуйте ещё раз')
    }
  }, [auth, playingId, ttsState, stop])

  return { play, stop, playingId, ttsState }
}
