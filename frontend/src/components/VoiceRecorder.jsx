import { useCallback, useEffect, useRef, useState } from 'react'

const BAR_COUNT = 20

export function VoiceRecorder({ onDone, onCancel }) {
  const [elapsed, setElapsed] = useState(0)
  const [bars, setBars] = useState(() => new Array(BAR_COUNT).fill(0))

  const mediaRecorderRef = useRef(null)
  const chunksRef = useRef([])
  const streamRef = useRef(null)
  const audioCtxRef = useRef(null)
  const rafRef = useRef(null)
  const timerRef = useRef(null)
  const stoppedRef = useRef(false)

  useEffect(() => {
    let canceled = false

    async function init() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        if (canceled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        streamRef.current = stream

        // MediaRecorder
        const recorder = new MediaRecorder(stream, {
          mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? 'audio/webm;codecs=opus'
            : 'audio/webm',
        })
        chunksRef.current = []
        recorder.ondataavailable = (e) => {
          if (e.data.size > 0) chunksRef.current.push(e.data)
        }
        mediaRecorderRef.current = recorder
        recorder.start()

        // Audio analyser
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)()
        audioCtxRef.current = audioCtx
        const source = audioCtx.createMediaStreamSource(stream)
        const analyser = audioCtx.createAnalyser()
        analyser.fftSize = 64
        analyser.smoothingTimeConstant = 0.4
        analyser.minDecibels = -90
        analyser.maxDecibels = -10
        source.connect(analyser)

        const dataArray = new Uint8Array(analyser.frequencyBinCount) // 32
        const smooth = new Float32Array(BAR_COUNT) // smoothed values
        let frame = 0

        function tick() {
          analyser.getByteFrequencyData(dataArray)
          frame++

          const result = []
          for (let i = 0; i < BAR_COUNT; i++) {
            const idx = Math.min(i, dataArray.length - 1)
            const raw = dataArray[idx] / 255

            // Rise fast, fall slow
            const prev = smooth[i]
            smooth[i] = raw > prev
              ? prev + (raw - prev) * 0.6
              : prev * 0.92

            // Idle breathing so bars never look dead
            const breath = 0.06 * (0.5 + 0.5 * Math.sin(frame * 0.05 + i * 0.7))
            result.push(Math.max(smooth[i], breath))
          }
          setBars(result)
          rafRef.current = requestAnimationFrame(tick)
        }
        rafRef.current = requestAnimationFrame(tick)

        timerRef.current = setInterval(() => {
          setElapsed((p) => p + 1)
        }, 1000)
      } catch {
        if (!canceled) onCancel()
      }
    }

    init()
    return () => { canceled = true; cleanup() }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function cleanup() {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      try { audioCtxRef.current.close() } catch { /* */ }
    }
    audioCtxRef.current = null
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
  }

  const handleDone = useCallback(() => {
    if (stoppedRef.current) return
    stoppedRef.current = true
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state === 'inactive') {
      cleanup()
      onCancel()
      return
    }
    recorder.onstop = () => {
      cleanup()
      const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
      blob.size > 0 ? onDone(blob) : onCancel()
    }
    recorder.stop()
  }, [onDone, onCancel]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleCancel = useCallback(() => {
    if (stoppedRef.current) return
    stoppedRef.current = true
    const recorder = mediaRecorderRef.current
    if (recorder && recorder.state !== 'inactive') recorder.stop()
    cleanup()
    onCancel()
  }, [onCancel]) // eslint-disable-line react-hooks/exhaustive-deps

  const mm = String(Math.floor(elapsed / 60)).padStart(2, '0')
  const ss = String(elapsed % 60).padStart(2, '0')

  return (
    <div className="flex items-center gap-3 bg-input-surface border-[1.5px] border-input-border rounded-3xl px-3 py-2 h-[52px]">
      <button
        type="button"
        onClick={handleCancel}
        className="w-8 h-8 flex items-center justify-center rounded-full border-none cursor-pointer bg-voice hover:bg-voice-hover text-fg-muted hover:text-fg transition-colors duration-150"
        title="Отменить запись"
      >
        <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24"><path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
      </button>

      <div className="flex items-center gap-1.5 shrink-0 min-w-[58px]">
        <span className="w-2 h-2 rounded-full bg-red-500 animate-[transcribe-pulse_1.2s_infinite_ease-in-out]" />
        <span className="text-sm font-mono text-fg tabular-nums">{mm}:{ss}</span>
      </div>

      <div className="flex-1 flex items-end justify-center gap-[3px] overflow-hidden" style={{ height: 28 }}>
        {bars.map((level, i) => (
          <div
            key={i}
            className="rounded-full bg-brand"
            style={{
              width: 3,
              height: Math.max(3, Math.round(level * 28)),
              opacity: 0.45 + level * 0.55,
              transition: 'height 80ms ease-out, opacity 100ms ease-out',
            }}
          />
        ))}
      </div>

      <button
        type="button"
        onClick={handleDone}
        className="w-8 h-8 flex items-center justify-center rounded-full border-none cursor-pointer bg-brand text-white hover:bg-brand-hover transition-colors duration-150"
        title="Готово"
      >
        <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24"><path d="M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
      </button>
    </div>
  )
}
