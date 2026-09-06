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
  render(<CreateRunDialog onClose={() => {}} onCreated={done} />)
  const user = userEvent.setup()
  await user.click(screen.getByText('开始运行'))
  expect(await screen.findByRole('alert')).toBeTruthy()
  await user.click(screen.getByText('确认原请求'))
  expect(create).toHaveBeenCalledTimes(2)
  expect(create.mock.calls[0][1]).toBe(create.mock.calls[1][1])
  expect(create.mock.calls[0][0]).toEqual(create.mock.calls[1][0])
  expect(done).toHaveBeenCalledTimes(1)
  expect(sessionStorage.getItem('probeops.pending')).toBeNull()
})
