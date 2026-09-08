import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, ClockCounterClockwise, Flask, Moon, Pulse, Sun } from '@phosphor-icons/react'
import { api } from './api'
import { Workspace } from './Workspace'

export function App() {
  const location = useLocation()
  const [dark, setDark] = useState(
    () =>
      localStorage.getItem('probeops.theme') === 'dark' ||
      (!localStorage.getItem('probeops.theme') &&
        matchMedia('(prefers-color-scheme: dark)').matches),
  )
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('probeops.theme', dark ? 'dark' : 'light')
  }, [dark])
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 5000 })
  const label =
    location.pathname === '/runs'
      ? '运行记录'
      : location.pathname === '/guide'
        ? '使用说明'
        : '诊断工作台'
  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">
        跳到工作区
      </a>
      <aside className="sidebar">
        <NavLink to="/" className="wordmark">
          ProbeOps
        </NavLink>
        <nav aria-label="主导航">
          <NavLink to="/" end>
            <Pulse size={21} />
            诊断工作台
          </NavLink>
          <NavLink to="/runs">
            <ClockCounterClockwise size={21} />
            运行记录
          </NavLink>
          <NavLink to="/guide">
            <BookOpen size={21} />
            使用说明
          </NavLink>
        </nav>
        <div className="sidebar-footer">
          <span>
            <Flask size={20} />
            {health.data?.llm_mode === 'bailian' ? '百炼模式' : '规则模拟模式'}
          </span>
          <small>
            <i className={health.isError ? 'connection offline' : 'connection'} />
            {health.isError
              ? '后端暂时离线'
              : health.isPending
                ? '正在连接后端'
                : '本地运行 · 只读诊断'}
          </small>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            工作空间 <span>/</span> {label}
          </div>
          <button
            className="icon-button"
            onClick={() => setDark(!dark)}
            aria-label={dark ? '切换浅色主题' : '切换深色主题'}
          >
            {dark ? <Sun size={21} /> : <Moon size={21} />}
          </button>
        </header>
        <main id="workspace">
          <Routes>
            <Route path="/" element={<Workspace />} />
            <Route path="/runs" element={<Workspace history />} />
            <Route path="/guide" element={<Guide />} />
            <Route
              path="*"
              element={
                <div className="empty">
                  <h1>页面不存在</h1>
                  <NavLink to="/">返回诊断工作台</NavLink>
                </div>
              }
            />
          </Routes>
        </main>
      </div>
    </div>
  )
}

function Guide() {
  return (
    <article className="guide">
      <h1>使用说明</h1>
      <p className="lead">先看一次完整流程，再检查每一步的证据。</p>
      <section>
        <h2>开始一次诊断运行</h2>
        <ol>
          <li>在诊断工作台点击“新建运行”，设置探测、调用和时间上限。</li>
          <li>
            选择冻结快照与策略后，任务进入本地队列。独立 worker
            生成竞争候选，通过四种只读工具验证预测。
          </li>
          <li>点击运行记录，查看过程、证据和报告；刷新页面后记录仍会保留。</li>
          <li>运行中可申请取消。排队任务立即取消，执行中的任务在检查点停止。</li>
        </ol>
      </section>
      <section>
        <h2>如何理解结果</h2>
        <p>
          “已完成”只说明流程执行结束。只有满足两类观测通道支持、领先分差和无直接反驳条件，报告才会标记定位；其他情况诚实保留竞争解释。
        </p>
        <p>
          模型模式在侧栏明确标注。规则模拟模式只验证程序行为，百炼模式按真实用量计费；超时或断连时，未知费用保留在账本中。
        </p>
      </section>
      <section>
        <h2>排查连接问题</h2>
        <p>
          后端离线时，页面保留错误与重试入口。运行长时间排队时，检查本地 worker 是否已启动。链路 ID
          可以关联后端日志和本地 OpenTelemetry 记录。
        </p>
        <p>此版本面向本机开发演示，请通过 127.0.0.1 访问。</p>
      </section>
    </article>
  )
}
