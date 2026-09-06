import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CaretRight, Copy, FileText, Prohibit } from '@phosphor-icons/react'
import { api, terminal } from './api'
import { ErrorNotice, Status } from './Status'

export function RunDetail({ id }: { id: string }) {
  const [tab, setTab] = useState<'events' | 'evidence' | 'report'>('events')
  const [copied, setCopied] = useState('')
  const client = useQueryClient()
  const run = useQuery({
    queryKey: ['run', id],
    queryFn: () => api.run(id),
    refetchInterval: (q) => (q.state.data && terminal(q.state.data) ? false : 700),
  })
  const active = run.data ? !terminal(run.data) : true
  const events = useQuery({
    queryKey: ['events', id, run.data?.last_event_seq],
    queryFn: () => api.events(id),
    enabled: !!run.data,
  })
  const evidence = useQuery({
    queryKey: ['evidence', id, run.data?.last_event_seq],
    queryFn: () => api.evidence(id),
    enabled: !!run.data,
  })
  const report = useQuery({
    queryKey: ['report', id],
    queryFn: () => api.report(id),
    enabled: run.data?.status === 'completed' && tab === 'report',
  })
  const cancel = useMutation({
    mutationFn: () => api.cancel(id),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['run', id] })
      await client.invalidateQueries({ queryKey: ['runs'] })
    },
  })
  if (run.error)
    return (
      <ErrorNotice
        error={run.error}
        retry={() => {
          void run.refetch()
        }}
      />
    )
  if (!run.data)
    return (
      <div className="empty" role="status">
        正在读取运行详情…
      </div>
    )
  const current = run.data
  async function copyTrace() {
    try {
      await navigator.clipboard.writeText(current.trace_id)
      setCopied('链路 ID 已复制')
    } catch {
      setCopied('复制失败，请选择下方链路 ID 手动复制。')
    }
  }
  return (
    <section className="run-detail" aria-labelledby="detail-heading">
      <div className="section-heading">
        <h2 id="detail-heading">运行详情</h2>
        <div className="inline">
          <Status status={current.status} />
          {active && (
            <button
              className="subtle small"
              disabled={cancel.isPending || current.status === 'cancel_requested'}
              onClick={() => cancel.mutate()}
            >
              <Prohibit size={16} />
              {current.status === 'cancel_requested' ? '正在取消' : '取消运行'}
            </button>
          )}
        </div>
      </div>
      {cancel.error && <ErrorNotice error={cancel.error} />}
      <div className="tabs" aria-label="运行详情视图">
        {(
          [
            ['events', '过程'],
            ['evidence', '证据'],
            ['report', '报告'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            aria-pressed={tab === key}
            className={tab === key ? 'active' : ''}
            onClick={() => setTab(key)}
          >
            {label}
            {key === 'evidence' && (
              <span className="tab-count">{evidence.data?.items.length ?? 0}</span>
            )}
          </button>
        ))}
      </div>
      {tab === 'events' && (
        <>
          {events.error && (
            <ErrorNotice
              error={events.error}
              retry={() => {
                void events.refetch()
              }}
            />
          )}
          {events.isPending && (
            <p role="status" className="muted">
              正在读取过程…
            </p>
          )}
          <ol className="timeline">
            {events.data?.items.map((event) => (
              <li key={event.seq}>
                <span className="step-index">{event.seq}</span>
                <details>
                  <summary>
                    <span>{event.message}</span>
                    <time dateTime={event.timestamp}>
                      {new Date(event.timestamp).toLocaleTimeString('zh-CN', { hour12: false })}
                    </time>
                    <CaretRight size={16} />
                  </summary>
                  <div className="event-meta">
                    <code>{event.kind}</code>
                    <span>
                      span <code>{event.span_id}</code>
                    </span>
                    {event.evidence_ids.length > 0 && (
                      <button className="text-button" onClick={() => setTab('evidence')}>
                        查看关联证据
                      </button>
                    )}
                  </div>
                </details>
              </li>
            ))}
          </ol>
          {current.status === 'queued' && (
            <p className="mode-note" role="status">
              等待 worker。若长时间未开始，请确认已启动本地 worker。
            </p>
          )}
        </>
      )}
      {tab === 'evidence' && (
        <>
          {evidence.error && (
            <ErrorNotice
              error={evidence.error}
              retry={() => {
                void evidence.refetch()
              }}
            />
          )}
          {!evidence.data?.items.length && !evidence.error && (
            <div className="empty">
              <FileText size={28} />
              <h3>暂无观测证据</h3>
              <p>{active ? '探测完成后，观测会出现在这里。' : '本次运行未产生观测。'}</p>
            </div>
          )}
          {evidence.data?.items.map((item) => (
            <article className="evidence-item" key={item.evidence_id}>
              <div className="section-heading">
                <code>{item.tool_name}</code>
                <span className="badge">模拟观测</span>
              </div>
              <p>{item.summary}</p>
              <dl className="evidence-meta">
                <dt>来源</dt>
                <dd>{item.source}</dd>
                <dt>证据 ID</dt>
                <dd>
                  <code>{item.evidence_id}</code>
                </dd>
                <dt>内容摘要</dt>
                <dd>
                  <code>{item.content_hash}</code>
                </dd>
              </dl>
            </article>
          ))}
        </>
      )}
      {tab === 'report' && (
        <>
          {current.status !== 'completed' ? (
            <div className="empty">
              <FileText size={28} />
              <h3>{active ? '报告尚未生成' : '本次运行没有报告'}</h3>
              <p>{active ? '流程完成后可查看报告。' : `停止原因：${current.stop_reason}`}</p>
            </div>
          ) : report.error ? (
            <ErrorNotice
              error={report.error}
              retry={() => {
                void report.refetch()
              }}
            />
          ) : !report.data ? (
            <p role="status">正在读取报告…</p>
          ) : (
            <article className="report">
              <span className="badge">模拟流程</span>
              <h3>无法确定根因</h3>
              <p>{report.data.summary}</p>
              <ul>
                {report.data.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <div className="report-facts">
                <span>
                  模拟调用 <strong>{current.usage.llm_calls}</strong> 次
                </span>
                <span>
                  探测 <strong>{current.usage.probe_count}</strong> 次
                </span>
                <span>
                  模型费用 <strong>¥0.00</strong>
                </span>
              </div>
            </article>
          )}
        </>
      )}
      <footer className="trace-footer">
        <span>
          链路 ID <code>{current.trace_id}</code>
        </span>
        <button
          className="icon-button"
          aria-label="复制链路 ID"
          onClick={() => {
            void copyTrace()
          }}
        >
          <Copy size={15} />
        </button>
        <span role="status">{copied}</span>
      </footer>
    </section>
  )
}
