import { useState } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { ArrowRight, Clock, Flask, Plus, Stack, Tray } from '@phosphor-icons/react'
import { api, defaultLimits, terminal, type Run } from './api'
import { Status, ErrorNotice } from './Status'
import { CreateRunDialog } from './CreateRunDialog'
import { RunDetail } from './RunDetail'

export function Workspace({ history = false }: { history?: boolean }) {
  const [search, setSearch] = useSearchParams()
  const [creating, setCreating] = useState(false)
  const [filter, setFilter] = useState('all')
  const client = useQueryClient()
  const selected = search.get('run') ?? ''
  const incidents = useQuery({ queryKey: ['incidents'], queryFn: api.incidents })
  const runs = useInfiniteQuery({
    queryKey: ['runs'],
    queryFn: ({ pageParam }) => api.runs(pageParam),
    initialPageParam: '',
    getNextPageParam: (page) => page.next_cursor || undefined,
    refetchInterval: 1500,
  })
  const selectedRun = useQuery({
    queryKey: ['run', selected],
    queryFn: () => api.run(selected),
    enabled: !!selected,
    refetchInterval: (q) => (q.state.data && terminal(q.state.data) ? false : 700),
  })
  const items = runs.data?.pages.flatMap((page) => page.items) ?? []
  const visible = items.filter(
    (run) => filter === 'all' || (filter === 'active' ? !terminal(run) : terminal(run)),
  )
  const limits = selectedRun.data?.limits ?? defaultLimits
  const incident = incidents.data?.items[0]
  async function created(run: Run) {
    setCreating(false)
    setSearch({ run: run.run_id })
    await client.invalidateQueries({ queryKey: ['runs'] })
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>{history ? '运行记录' : '诊断工作台'}</h1>
          <p>从告警出发，检查假设与证据。</p>
        </div>
        <button className="primary" disabled={!incident} onClick={() => setCreating(true)}>
          <Plus size={18} />
          新建运行
        </button>
      </div>
      {incidents.error && (
        <ErrorNotice
          error={incidents.error}
          retry={() => {
            void incidents.refetch()
          }}
        />
      )}
      <section className="incident-context" aria-label="演示任务">
        <h2>{incident?.title ?? '正在读取任务…'}</h2>
        <div className="context-line">
          <span className="badge">演示任务</span>
          <span>
            <Stack size={17} />
            {incident?.service ?? '—'}
          </span>
          <span>
            <Clock size={17} />
            09:40–09:45
          </span>
          <span>
            <Flask size={17} />
            {incident?.alert ?? '模拟数据，用于验证运行流程。'}
          </span>
        </div>
      </section>
      <div className="workspace-grid">
        <div className="primary-workspace">
          <section aria-labelledby="runs-heading">
            <div className="section-heading">
              <h2 id="runs-heading">运行记录</h2>
              <span className="muted small">模拟数据</span>
            </div>
            <div className="filters" aria-label="筛选运行">
              {[
                ['all', '全部'],
                ['active', '进行中'],
                ['ended', '已结束'],
              ].map(([key, label]) => (
                <button
                  key={key}
                  className={filter === key ? 'selected' : ''}
                  aria-pressed={filter === key}
                  onClick={() => setFilter(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            {runs.error && (
              <ErrorNotice
                error={runs.error}
                retry={() => {
                  void runs.refetch()
                }}
              />
            )}
            {runs.isPending ? (
              <div className="empty" role="status">
                正在读取运行记录…
              </div>
            ) : visible.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>运行</th>
                      <th>状态</th>
                      <th>策略</th>
                      <th className="number">费用</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((run) => (
                      <tr
                        key={run.run_id}
                        className={selected === run.run_id ? 'selected-row' : ''}
                      >
                        <td>
                          <button
                            className="run-link"
                            aria-pressed={selected === run.run_id}
                            onClick={() => setSearch({ run: run.run_id })}
                          >
                            <code>{run.run_id}</code>
                            <small>
                              {new Date(run.created_at).toLocaleString('zh-CN', { hour12: false })}
                            </small>
                          </button>
                        </td>
                        <td>
                          <Status status={run.status} />
                        </td>
                        <td>固定流程演示</td>
                        <td className="number">
                          ¥{(run.usage.settled_micro_cny / 1000000).toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              !runs.error && (
                <div className="empty">
                  <Tray size={32} />
                  <h3>{items.length ? '此筛选下没有运行' : '还没有运行记录'}</h3>
                  <p>
                    {items.length
                      ? '切换筛选条件，查看其他运行。'
                      : '新建一次模拟运行，查看任务从创建到完成的过程。'}
                  </p>
                  {!items.length && (
                    <button
                      className="text-button"
                      disabled={!incident}
                      onClick={() => setCreating(true)}
                    >
                      开始第一次运行
                      <ArrowRight size={16} />
                    </button>
                  )}
                </div>
              )
            )}
            {runs.hasNextPage && (
              <button
                className="load-more"
                disabled={runs.isFetchingNextPage}
                onClick={() => {
                  void runs.fetchNextPage()
                }}
              >
                {runs.isFetchingNextPage ? '正在加载…' : '加载更多记录'}
              </button>
            )}
          </section>
          {selected ? (
            <RunDetail key={selected} id={selected} />
          ) : (
            items.length > 0 && (
              <div className="empty">
                <h3>选择一条运行</h3>
                <p>查看它的过程、证据和报告。</p>
              </div>
            )
          )}
        </div>
        <aside className="inspector">
          <h2>任务上下文</h2>
          <dl>
            <dt>运行模式</dt>
            <dd>
              <code>FakeLLM</code>
            </dd>
            <dt>探测上限</dt>
            <dd>{limits.max_steps} 次</dd>
            <dt>调用上限</dt>
            <dd>{limits.max_llm_calls} 次</dd>
            <dt>时间上限</dt>
            <dd>{limits.max_wall_seconds} 秒</dd>
          </dl>
          <p>P1 验证基础链路，暂不提供真实根因判断。</p>
        </aside>
      </div>
      {creating && (
        <CreateRunDialog
          onClose={() => setCreating(false)}
          onCreated={(run) => {
            void created(run)
          }}
        />
      )}
    </>
  )
}
