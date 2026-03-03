import { useCallback, useRef, useState } from 'react'

export function MessageInput({ disabled, onSend, onSendVoice }) {
  const [text, setText] = useState('')
  const [recording, setRecording] = useState(false)
  const [micError, setMicError] = useState('')
  const mediaRecorderRef = useRef(null)
  const chunksRef = useRef([])

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

  const startRecording = useCallback(async () => {
    if (!onSendVoice) return
    setMicError('')
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setMicError('Браузер не поддерживает запись аудио')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
          ? 'audio/webm;codecs=opus'
          : 'audio/webm',
      })
      chunksRef.current = []

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      mediaRecorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        if (blob.size > 0) {
          onSendVoice(blob)
        }
      }

      mediaRecorderRef.current = mediaRecorder
      mediaRecorder.start()
      setRecording(true)
    } catch {
      setMicError('Разрешите доступ к микрофону в настройках браузера')
    }
  }, [onSendVoice])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    setRecording(false)
  }, [])

  return (
    <div className="message-input">
      {micError && <div className="mic-error">{micError}</div>}
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Напишите ваш вопрос..."
        rows={2}
        disabled={disabled || recording}
      />
      <div className="message-input-buttons">
        {onSendVoice && (
          <button
            className={`voice-btn${recording ? ' recording' : ''}`}
            onClick={recording ? stopRecording : startRecording}
            disabled={disabled}
            title={recording ? 'Остановить запись' : 'Голосовое сообщение'}
          >
            {recording ? '⏹' : '🎤'}
          </button>
        )}
        <button onClick={submit} disabled={disabled || !text.trim() || recording}>
          Отправить
        </button>
      </div>
    </div>
  )
}
