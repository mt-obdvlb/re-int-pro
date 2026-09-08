import { useEffect, useRef, useState } from 'react'
import { X, ArrowRight } from '@phosphor-icons/react'
import {
  api,
  defaultLimits,
  ApiError,
  money,
  type CreateRun,
  type Incident,
  type Strategy,
  type Run,
} from './api'
import { ErrorNotice } from './Status'

export function CreateRunDialog({
  onClose,
  onCreated,
  incidents,
  strategies,
  model,
}: {
  onClose: () => void
  onCreated: (run: Run) => void
  incidents: Incident[]
  strategies: Strategy[]
  model: string
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const inFlight = useRef(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  // Retain the key and payload on ambiguous network failures, including reopening the dialog.
  const [pending, setPending] = useState<{ key: string; body: CreateRun } | null>(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem('probeops.pending.v2') ?? 'null')
      return saved?.body?.incident_id && saved?.body?.limits && typeof saved.key === 'string'
        ? saved
        : null
    } catch {
      return null
    }
  })
  const [limits, setLimits] = useState(pending?.body.limits ?? defaultLimits)
  const [incidentId, setIncidentId] = useState(
    pending?.body.incident_id ??
      incidents.find((i) => i.incident_id !== 'demo_latency')?.incident_id ??
      incidents[0]?.incident_id ??
      '',
  )
  const [strategyId, setStrategyId] = useState<CreateRun['strategy_id']>(
    pending?.body.strategy_id ?? (incidentId === 'demo_latency' ? 'fixed' : 'competitive_cost'),
  )
  useEffect(() => {
    dialog.current?.showModal()
  }, [])
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setError(null)
    const intent = pending ?? {
      key: crypto.randomUUID(),
      body: { incident_id: incidentId, strategy_id: strategyId, limits },
    }
    setPending(intent)
    try {
      // Fail before sending if the intent cannot be retained for a safe retry.
      sessionStorage.setItem('probeops.pending.v2', JSON.stringify(intent))
      const run = await api.create(intent.body, intent.key)
      try {
        sessionStorage.removeItem('probeops.pending.v2')
      } catch {
        /* in-memory state still resolves */
      }
      onCreated(run)
    } catch (e) {
      setError(e as Error)
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
        setPending(null)
        try {
          sessionStorage.removeItem('probeops.pending.v2')
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
        <p className="muted">选择冻结观测与诊断策略。</p>
        <div className="mode-note">
          {model.startsWith('Fake') || incidentId === 'demo_latency'
            ? '规则模拟模型，用于验证工程行为，不产生模型费用。'
            : `${model} · 本次费用上限 ${money(limits.max_cost_micro_cny)}，请求前预留费用。`}
        </div>
        {pending && <p className="muted">有一笔待确认请求。重试会使用原请求，避免重复创建。</p>}
        <fieldset disabled={busy || !!pending}>
          <legend>任务与运行限制</legend>
          <label className="full-width">
            观测任务
            <select
              value={incidentId}
              required
              onChange={(e) => {
                setIncidentId(e.target.value)
                if (e.target.value === 'demo_latency') setStrategyId('fixed')
              }}
            >
              {incidents.map((i) => (
                <option key={i.incident_id} value={i.incident_id}>
                  {i.title} · {i.incident_id}
                </option>
              ))}
            </select>
          </label>
          <label className="full-width">
            诊断策略
            <select
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value as CreateRun['strategy_id'])}
            >
              {strategies
                .filter((s) => incidentId !== 'demo_latency' || s.strategy_id === 'fixed')
                .map((s) => (
                  <option key={s.strategy_id} value={s.strategy_id}>
                    {s.name}
                  </option>
                ))}
            </select>
          </label>
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
          <label>
            费用上限 <span>0.001–0.25 元</span>
            <input
              type="number"
              min="0.001"
              max="0.25"
              step="0.001"
              required
              value={limits.max_cost_micro_cny / 1000000}
              onChange={(e) =>
                setLimits({
                  ...limits,
                  max_cost_micro_cny: Math.round(Number(e.target.value) * 1000000),
                })
              }
            />
          </label>
        </fieldset>
        {error && <ErrorNotice error={error} />}
        <div className="dialog-actions">
          <button type="button" disabled={busy} onClick={onClose}>
            返回
          </button>
          <button className="primary" disabled={busy || !incidentId}>
            {busy ? '正在提交…' : pending ? '确认原请求' : '开始运行'}
            <ArrowRight size={16} />
          </button>
        </div>
      </form>
    </dialog>
  )
}
