import { useEffect, useRef, useState } from 'react'
import { X, ArrowRight } from '@phosphor-icons/react'
import { api, defaultLimits, ApiError, type Limits, type Run } from './api'
import { ErrorNotice } from './Status'

export function CreateRunDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (run: Run) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const inFlight = useRef(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  // Retain the key and payload on ambiguous network failures, including reopening the dialog.
  const [pending, setPending] = useState<{ key: string; limits: Limits } | null>(() => {
    try {
      return JSON.parse(sessionStorage.getItem('probeops.pending') ?? 'null')
    } catch {
      return null
    }
  })
  const [limits, setLimits] = useState<Limits>(pending?.limits ?? defaultLimits)
  useEffect(() => {
    dialog.current?.showModal()
  }, [])
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setError(null)
    const intent = pending ?? { key: crypto.randomUUID(), limits }
    setPending(intent)
    try {
      // Fail before sending if the intent cannot be retained for a safe retry.
      sessionStorage.setItem('probeops.pending', JSON.stringify(intent))
      const run = await api.create(
        { incident_id: 'demo_latency', strategy_id: 'fixed', limits: intent.limits },
        intent.key,
      )
      try {
        sessionStorage.removeItem('probeops.pending')
      } catch {
        /* in-memory state still resolves */
      }
      onCreated(run)
    } catch (e) {
      setError(e as Error)
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
        setPending(null)
        try {
          sessionStorage.removeItem('probeops.pending')
        } catch {
          /* original intent remains safe */
        }
      }
    } finally {
      setBusy(false)
      inFlight.current = false
    }
  }
  return (
    <dialog
      ref={dialog}
      onCancel={(e) => {
        e.preventDefault()
        if (!busy) onClose()
      }}
      aria-labelledby="create-title"
    >
      <form onSubmit={submit}>
        <div className="dialog-heading">
          <h2 id="create-title">新建运行</h2>
          <button
            type="button"
            className="icon-button"
            aria-label="关闭新建运行"
            disabled={busy}
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        <p className="muted">API 响应延迟 · 固定流程演示</p>
        <div className="mode-note">FakeLLM 与模拟指标快照，不产生模型费用。</div>
        {pending && <p className="muted">有一笔待确认请求。重试会使用原请求，避免重复创建。</p>}
        <fieldset disabled={busy || !!pending}>
          <legend>运行限制</legend>
          <label>
            探测上限 <span>1–12 次</span>
            <input
              type="number"
              min="1"
              max="12"
              required
              value={limits.max_steps}
              onChange={(e) => setLimits({ ...limits, max_steps: Number(e.target.value) })}
            />
          </label>
          <label>
            调用上限 <span>1–16 次</span>
            <input
              type="number"
              min="1"
              max="16"
              required
              value={limits.max_llm_calls}
              onChange={(e) => setLimits({ ...limits, max_llm_calls: Number(e.target.value) })}
            />
          </label>
          <label>
            时间上限 <span>1–180 秒</span>
            <input
              type="number"
              min="1"
              max="180"
              required
              value={limits.max_wall_seconds}
              onChange={(e) => setLimits({ ...limits, max_wall_seconds: Number(e.target.value) })}
            />
          </label>
        </fieldset>
        {error && <ErrorNotice error={error} />}
        <div className="dialog-actions">
          <button type="button" disabled={busy} onClick={onClose}>
            返回
          </button>
          <button className="primary" disabled={busy}>
            {busy ? '正在提交…' : pending ? '确认原请求' : '开始运行'}
            <ArrowRight size={16} />
          </button>
        </div>
      </form>
    </dialog>
  )
}
