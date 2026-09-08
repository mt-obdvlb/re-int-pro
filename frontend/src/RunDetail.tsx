import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CaretRight, Copy, FileText, Prohibit } from '@phosphor-icons/react'
import { api, terminal, money, faultNames } from './api'
import { ErrorNotice, Status } from './Status'

export function RunDetail({ id }: { id: string }) {
  const [tab, setTab] = useState<'hypotheses' | 'events' | 'evidence' | 'report'>('hypotheses')
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
            ['hypotheses', '竞争假设'],
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
      {tab === 'hypotheses' && (
        <div className="hypotheses">
          <p className="muted">支持 +1、反驳 −2。两类观测通道支持且领先至少 2 分，才允许定位。</p>
          {!current.hypotheses.length && (
            <p role="status">{active ? '正在生成可证伪的候选解释…' : '本次运行未生成有效候选。'}</p>
          )}
          {current.hypotheses.map((h) => (
            <article key={h.hypothesis_id} className="hypothesis-row">
              <div className="section-heading">
                <div>
                  <h3>{faultNames[h.fault_type] ?? h.fault_type}</h3>
                  <code>{h.component}</code>
                </div>
                <div className="hypothesis-score">
                  <strong>
                    {h.score > 0 ? '+' : ''}
                    {h.score}
                  </strong>
                  <span>
                    {
                      {
                        active: '待验证',
                        supported: '满足定位条件',
                        contradicted: '存在反驳',
                        unresolved: '未确定',
                      }[h.status]
                    }
                  </span>
                </div>
              </div>
              <details>
                <summary>预测与证据 · {h.evidence_ids.length} 项引用</summary>
                <ul className="prediction-list">
                  {h.predictions.map((p) => (
                    <li key={`${p.tool_name}-${p.observation}`}>
                      <code>{p.observation}</code>
                      <span>
                        {
                          {
                            high: '偏高 / 存在',
                            normal: '正常 / 不存在',
                            low: '偏低',
                            unknown: '无法预测',
                          }[p.expected]
                        }
                      </span>
                    </li>
                  ))}
                </ul>
                {h.evidence_ids.length > 0 && (
                  <button className="text-button" onClick={() => setTab('evidence')}>
                    查看观测证据
                  </button>
                )}
              </details>
            </article>
          ))}
        </div>
      )}
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
                  {event.decision && (
                    <div className="decision-detail">
                      <p>{event.decision.reason}</p>
                      <dl>
                        <dt>探测</dt>
                        <dd>
                          <code>{event.decision.probe_id}</code>
                        </dd>
                        <dt>可区分候选对</dt>
                        <dd>{event.decision.disagreement_pairs}</dd>
                        <dt>估算成本单位</dt>
                        <dd>{event.decision.estimated_cost_units.toFixed(3)}</dd>
                        <dt>效用 D/(c+0.1)</dt>
                        <dd>{event.decision.utility.toFixed(3)}</dd>
                      </dl>
                    </div>
                  )}
                  {event.hypotheses && (
                    <ul className="prediction-list">
                      {event.hypotheses.map((h) => (
                        <li key={h.hypothesis_id}>
                          <span>{faultNames[h.fault_type] ?? h.fault_type}</span>
                          <span>
                            {h.score > 0 ? '+' : ''}
                            {h.score} · {h.status}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
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
                <span className="badge">
                  {item.source.startsWith('synthetic:') ? '模拟观测' : '冻结快照'} · {item.outcome}
                </span>
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
              <span className="badge">{current.model}</span>
              <h3>
                {report.data.conclusion === 'located'
                  ? `${report.data.component} · ${faultNames[report.data.fault_type] ?? report.data.fault_type}`
                  : '无法确定根因'}
              </h3>
              <p>{report.data.summary}</p>
              <p className="muted">
                停止原因：{current.stop_reason} · {report.data.evidence_ids.length} 项证据引用
              </p>
              {report.data.alternatives.length > 0 && (
                <p>
                  其他解释：{report.data.alternatives.map((a) => faultNames[a] ?? a).join('、')}
                </p>
              )}
              <ul>
                {report.data.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <div className="report-facts">
                <span>
                  模型调用 <strong>{current.usage.llm_calls}</strong> 次
                </span>
                <span>
                  探测 <strong>{current.usage.probe_count}</strong> 次
                </span>
                <span>
                  已结算 <strong>{money(current.usage.settled_micro_cny)}</strong>
                </span>
                <span>
                  未确认 <strong>{money(current.usage.uncertain_micro_cny)}</strong>
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
