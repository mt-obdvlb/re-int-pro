import type { components } from './api-schema'

export type Run = components['schemas']['Run']
export type Event = components['schemas']['Event']
export type Evidence = components['schemas']['Evidence']
export type Report = components['schemas']['Report']
export type CreateRun = components['schemas']['CreateRun']
export type Limits = components['schemas']['Limits']
export type Incident = components['schemas']['Incident']
export type Strategy = components['schemas']['Strategy']
export const money = (micro: number) => `¥${(micro / 1000000).toFixed(4)}`
export const strategyNames: Record<string, string> = {
  fixed: '固定流程',
  react: 'ReAct',
  graph_greedy: '图贪心',
  competitive_cost: '竞争假设与成本',
  no_cost: '去成本消融',
  random_probe: '随机探测',
}
export const faultNames: Record<string, string> = {
  pool_exhaustion: '连接池耗尽',
  queue_backlog: '任务队列积压',
  cache_latency: '缓存延迟',
  config_error: '配置错误',
  unknown: '未知原因',
}
export const defaultLimits: Limits = {
  max_steps: 12,
  max_llm_calls: 16,
  max_wall_seconds: 180,
  max_cost_micro_cny: 250000,
}
export const terminal = (run: Run) => ['completed', 'failed', 'cancelled'].includes(run.status)

export class ApiError extends Error {
  constructor(
    message: string,
    readonly requestId = '',
    readonly status = 0,
  ) {
    super(message)
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      signal: AbortSignal.timeout(10000),
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError('暂时无法连接后端。请检查服务后重试。')
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new ApiError(
      typeof error.message === 'string' ? error.message : '请求未完成，请稍后重试。',
      response.headers.get('X-Request-ID') ?? '',
      response.status,
    )
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<components['schemas']['Health']>('/healthz'),
  incidents: () => request<components['schemas']['IncidentList']>('/api/v1/incidents'),
  strategies: () => request<components['schemas']['StrategyList']>('/api/v1/strategies'),
  budget: () => request<components['schemas']['Budget']>('/api/v1/budget'),
  runs: (cursor = '') =>
    request<components['schemas']['RunPage']>(
      `/api/v1/runs?limit=20&cursor=${encodeURIComponent(cursor)}`,
    ),
  run: (id: string) => request<Run>(`/api/v1/runs/${encodeURIComponent(id)}`),
  events: (id: string) =>
    request<components['schemas']['EventPage']>(
      `/api/v1/runs/${encodeURIComponent(id)}/events?limit=100`,
    ),
  evidence: (id: string) =>
    request<components['schemas']['EvidencePage']>(
      `/api/v1/runs/${encodeURIComponent(id)}/evidence?limit=100`,
    ),
  report: (id: string) => request<Report>(`/api/v1/runs/${encodeURIComponent(id)}/report`),
  create: (body: CreateRun, key: string) =>
    request<Run>('/api/v1/runs', {
      method: 'POST',
      headers: { 'Idempotency-Key': key },
      body: JSON.stringify(body),
    }),
  cancel: (id: string) =>
    request<Run>(`/api/v1/runs/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason: '用户从工作台取消' }),
    }),
}
