import { CheckCircle, CircleNotch, Clock, Prohibit, WarningCircle } from '@phosphor-icons/react'
import type { Run } from './api'

const labels = {
  queued: '等待执行',
  running: '运行中',
  cancel_requested: '取消中',
  completed: '已完成',
  cancelled: '已取消',
  failed: '失败',
}
export function Status({ status }: { status: Run['status'] }) {
  const Icon =
    status === 'completed'
      ? CheckCircle
      : status === 'failed'
        ? WarningCircle
        : status === 'cancelled'
          ? Prohibit
          : status === 'queued'
            ? Clock
            : CircleNotch
  return (
    <span className={`status status-${status}`}>
      <Icon size={18} />
      {labels[status]}
    </span>
  )
}

export function ErrorNotice({ error, retry }: { error: Error; retry?: () => void }) {
  return (
    <div className="error-notice" role="alert">
      <WarningCircle size={20} />
      <span>{error.message}</span>
      {retry && <button onClick={retry}>重试</button>}
    </div>
  )
}
