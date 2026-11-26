import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { BrowserMonitorPage } from '@/routes/browser-monitor'

const mocks = vi.hoisted(() => ({ post: vi.fn(), wsBase: vi.fn() }))
vi.mock('@/lib/http/instances', () => ({ backendApi: { post: mocks.post } }))
vi.mock('@/lib/api-base', () => ({ getWsBaseUrl: mocks.wsBase }))

class MockWebSocket {
  static OPEN = 1
  readyState = 1
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  send = vi.fn()
  close = vi.fn()
  constructor(public url: string) {}
}

afterEach(() => vi.unstubAllGlobals())

describe('browser monitor page', () => {
  it('renders stream state and sends takeover command', async () => {
    mocks.post.mockResolvedValue({ success: true })
    mocks.wsBase.mockResolvedValue('ws://127.0.0.1:8000')
    vi.stubGlobal('WebSocket', MockWebSocket)
    let socket: MockWebSocket
    const Original = globalThis.WebSocket
    globalThis.WebSocket = class extends MockWebSocket {
      constructor(url: string) {
        super(url)
        socket = this
      }
    } as unknown as typeof WebSocket

    const view = render(<BrowserMonitorPage />)
    await waitFor(() => expect(socket!).toBeDefined())
    await act(async () => {
      socket!.onopen?.()
      socket!.onmessage?.({
        data: JSON.stringify({
          type: 'state', running: true, controller: 'bot', clients: 1,
          targets: [{ id: 't1', title: 'Example', url: 'https://example.com' }],
          url: 'https://example.com',
        }),
      })
      socket!.onmessage?.({ data: JSON.stringify({ type: 'frame', data: 'aGVsbG8=' }) })
    })

    expect(screen.getByText('瀏覽器即時監看')).toBeInTheDocument()
    expect(screen.getByText('控制權：大肥魚')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '接管控制權' }))
    expect(socket!.send).toHaveBeenCalledWith(JSON.stringify({ action: 'takeover' }))
    view.unmount()
    expect(socket!.close).toHaveBeenCalled()
    globalThis.WebSocket = Original
  })
})
