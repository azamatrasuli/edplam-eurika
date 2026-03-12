import { useCallback, useRef, useState } from 'react'
import { transcribeAudio } from '../api/client'
import { VoiceRecorder } from './VoiceRecorder'

export function MessageInput({ disabled, onSend }) {
  const [text, setText] = useState('')
  const [voiceMode, setVoiceMode] = useState('idle') // 'idle' | 'recording' | 'transcribing'
  const [micError, setMicError] = useState('')
  const textareaRef = useRef(null)

  function submit() {
    const value = text.trim()
    if (!value) return
    onSend(value)
    setText('')
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function startRecording() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setMicError('Браузер не поддерживает запись аудио')
      return
    }
    setMicError('')
    setVoiceMode('recording')
  }

  const handleVoiceDone = useCallback(async (blob) => {
    setVoiceMode('transcribing')
    try {
      const transcript = await transcribeAudio(blob)
      setText((prev) => {
        if (!transcript) return prev
        return prev ? `${prev} ${transcript}` : transcript
      })
      setVoiceMode('idle')
      // Focus textarea after render
      setTimeout(() => textareaRef.current?.focus(), 50)
    } catch {
      setMicError('Не удалось распознать голос. Попробуйте ещё раз.')
      setVoiceMode('idle')
    }
  }, [])

  const handleVoiceCancel = useCallback(() => {
    setVoiceMode('idle')
  }, [])

  // Transcribing state
  if (voiceMode === 'transcribing') {
    return (
      <div className="flex items-center justify-center gap-1 bg-input-surface border-[1.5px] border-input-border rounded-3xl px-4 py-3 h-[52px]">
        <span className="text-sm text-fg-muted">Распознаю голос</span>
        <span className="flex gap-1 ml-1">
          <span className="w-1.5 h-1.5 rounded-full bg-brand animate-[transcribe-pulse_1.2s_infinite_ease-in-out]" style={{ animationDelay: '0s' }} />
          <span className="w-1.5 h-1.5 rounded-full bg-brand animate-[transcribe-pulse_1.2s_infinite_ease-in-out]" style={{ animationDelay: '0.2s' }} />
          <span className="w-1.5 h-1.5 rounded-full bg-brand animate-[transcribe-pulse_1.2s_infinite_ease-in-out]" style={{ animationDelay: '0.4s' }} />
        </span>
      </div>
    )
  }

  // Recording state
  if (voiceMode === 'recording') {
    return (
      <>
        {micError && (
          <div className="text-[13px] text-error bg-error-bg px-3 py-1.5 rounded-lg mb-2 border border-error-border">
            {micError}
          </div>
        )}
        <VoiceRecorder onDone={handleVoiceDone} onCancel={handleVoiceCancel} />
      </>
    )
  }

  // Idle state — normal input
  return (
    <>
      {micError && (
        <div className="text-[13px] text-error bg-error-bg px-3 py-1.5 rounded-lg mb-2 border border-error-border">
          {micError}
        </div>
      )}
      <div className="input-ring flex items-end gap-2 bg-input-surface border-[1.5px] border-input-border rounded-3xl pl-4 pr-1.5 py-1.5 transition-[border-color,box-shadow] duration-200 ease-in-out">
        <textarea
          ref={textareaRef}
          className="flex-1 border-none py-2 resize-none text-[15px] bg-transparent text-fg leading-[1.4] min-h-6 max-h-30 outline-none placeholder:text-fg-muted placeholder:opacity-60"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Напишите сообщение..."
          rows={1}
          disabled={disabled}
        />
        <div className="flex gap-1 shrink-0 items-end">
          <button
            className="w-9 h-9 p-0 text-[17px] flex items-center justify-center rounded-full border-none cursor-pointer shrink-0 transition-[background,color,transform] duration-150 ease-in-out disabled:opacity-30 disabled:cursor-default bg-voice text-fg-muted hover:bg-voice-hover hover:text-fg"
            onClick={startRecording}
            disabled={disabled}
            title="Голосовое сообщение"
            type="button"
          >
            🎤
          </button>
          <button
            className="w-9 h-9 p-0 flex items-center justify-center border-none rounded-full bg-brand text-white cursor-pointer shrink-0 transition-[background,transform,opacity] duration-150 ease-in-out hover:bg-brand-hover hover:scale-105 active:scale-95 disabled:opacity-30 disabled:cursor-default"
            onClick={submit}
            disabled={disabled || !text.trim()}
            title="Отправить"
            type="button"
          >
            <svg className="w-[18px] h-[18px] fill-current" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path d="M3.478 2.405a.75.75 0 0 0-.926.94l2.432 7.905H13.5a.75.75 0 0 1 0 1.5H4.984l-2.432 7.905a.75.75 0 0 0 .926.94l18-8a.75.75 0 0 0 0-1.38l-18-8Z" />
            </svg>
          </button>
        </div>
      </div>
    </>
  )
}
