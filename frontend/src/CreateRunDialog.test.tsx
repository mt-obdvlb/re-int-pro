import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CreateRunDialog } from './CreateRunDialog'
import { api, ApiError, type Run } from './api'

beforeEach(() => {
  sessionStorage.clear()
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
})
afterEach(cleanup)

it('reuses the same idempotency key after an ambiguous network error', async () => {
  const create = vi
    .spyOn(api, 'create')
    .mockRejectedValueOnce(new ApiError('网络中断'))
    .mockResolvedValueOnce({ run_id: 'run_test' } as Run)
  const done = vi.fn()
  render(
    <CreateRunDialog
      onClose={() => {}}
      onCreated={done}
      incidents={[
        {
          incident_id: 'inc_0123456789abcdef',
          title: '测试快照',
          alert: '测试',
          service: 'checkout-api',
          window_start: '2026-09-08T00:00:00Z',
          window_end: '2026-09-08T00:01:00Z',
          dataset_version: 'test',
        },
      ]}
      strategies={[
        { strategy_id: 'competitive_cost', name: '竞争假设与成本', description: '测试' },
      ]}
      model="FakeLLM-v2"
    />,
  )
  const user = userEvent.setup()
  await user.click(screen.getByText('开始运行'))
  expect(await screen.findByRole('alert')).toBeTruthy()
  await user.click(screen.getByText('确认原请求'))
  expect(create).toHaveBeenCalledTimes(2)
  expect(create.mock.calls[0][1]).toBe(create.mock.calls[1][1])
  expect(create.mock.calls[0][0]).toEqual(create.mock.calls[1][0])
  expect(done).toHaveBeenCalledTimes(1)
  expect(sessionStorage.getItem('probeops.pending.v2')).toBeNull()
})
