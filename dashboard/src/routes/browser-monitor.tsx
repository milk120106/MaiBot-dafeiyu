import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent, MouseEvent, WheelEvent } from 'react'
import { ArrowLeft, Hand, Monitor, MousePointer2, RefreshCw, RotateCcw, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { backendApi } from '@/lib/http/instances'
import { getWsBaseUrl } from '@/lib/api-base'

type Target = { id: string; title: string; url: string }
type MonitorState = {
  type: 'state'
  running: boolean
  controller: 'bot' | 'user'
  clients: number
  targets: Target[]
  url: string
}

const VIEW_WIDTH = 1280
const VIEW_HEIGHT = 800

export function BrowserMonitorPage() {
  const [frame, setFrame] = useState('')
  const [connected, setConnected] = useState(false)
  const [running, setRunning] = useState(false)
  const [controller, setController] = useState<'bot' | 'user'>('bot')
  const [targets, setTargets] = useState<Target[]>([])
  const [currentUrl, setCurrentUrl] = useState('about:blank')
  const [address, setAddress] = useState('')
  const [selectedTarget, setSelectedTarget] = useState('')
  const [error, setError] = useState('')
  const socketRef = useRef<WebSocket | null>(null)
  const viewRef = useRef<HTMLDivElement | null>(null)

  const send = useCallback((payload: Record<string, unknown>) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(payload))
    }
  }, [])

  useEffect(() => {
    let disposed = false
    let socket: WebSocket | null = null

    async function connect() {
      try {
        setError('')
        await backendApi.post('/api/webui/browser-monitor/start', {})
        if (disposed) return
        const base = await getWsBaseUrl()
        socket = new WebSocket(`${base}/api/webui/browser-monitor/ws`)
        socketRef.current = socket
        socket.onopen = () => !disposed && setConnected(true)
        socket.onmessage = (event) => {
          if (disposed) return
          const message = JSON.parse(event.data)
          if (message.type === 'frame') {
            setFrame(`data:image/jpeg;base64,${message.data}`)
          } else if (message.type === 'state') {
            const state = message as MonitorState
            setRunning(state.running)
            setController(state.controller)
            setTargets(state.targets || [])
            setCurrentUrl(state.url || 'about:blank')
            setAddress(state.url || '')
            setSelectedTarget((previous) => previous || state.targets?.[0]?.id || '')
          } else if (message.type === 'error') {
            setError(message.error || '監看連線失敗')
          }
        }
        socket.onerror = () => !disposed && setError('無法連線瀏覽器監看服務')
        socket.onclose = () => !disposed && setConnected(false)
      } catch (cause) {
        if (!disposed) setError(cause instanceof Error ? cause.message : String(cause))
      }
    }

    void connect()
    return () => {
      disposed = true
      socket?.close()
      socketRef.current = null
    }
  }, [])

  const point = (event: MouseEvent) => {
    const rect = viewRef.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return {
      x: Math.max(0, Math.min(VIEW_WIDTH, ((event.clientX - rect.left) / rect.width) * VIEW_WIDTH)),
      y: Math.max(0, Math.min(VIEW_HEIGHT, ((event.clientY - rect.top) / rect.height) * VIEW_HEIGHT)),
    }
  }

  const mouse = (event: MouseEvent, type: string, button = 'left') => {
    if (controller !== 'user') return
    event.preventDefault()
    send({ action: 'mouse', type, ...point(event), button, clickCount: 1 })
  }

  const wheel = (event: WheelEvent) => {
    if (controller !== 'user') return
    event.preventDefault()
    send({ action: 'mouse', type: 'mouseWheel', ...point(event), deltaX: event.deltaX, deltaY: event.deltaY })
  }

  const key = (event: KeyboardEvent, type: 'keyDown' | 'keyUp') => {
    if (controller !== 'user') return
    event.preventDefault()
    send({
      action: 'key', type, key: event.key, code: event.code,
      text: type === 'keyDown' && event.key.length === 1 ? event.key : '',
      windowsVirtualKeyCode: event.keyCode,
      nativeVirtualKeyCode: event.keyCode,
    })
  }

  const navigate = (event: FormEvent) => {
    event.preventDefault()
    if (controller === 'user' && address.trim()) send({ action: 'navigate', url: address.trim() })
  }

  const stop = async () => {
    socketRef.current?.close()
    socketRef.current = null
    setConnected(false)
    setFrame('')
    try {
      await backendApi.post('/api/webui/browser-monitor/stop', {})
      setRunning(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Monitor className="h-5 w-5" />
          <h1 className="text-lg font-semibold">瀏覽器即時監看</h1>
          <span className={`rounded px-2 py-0.5 text-xs ${connected ? 'bg-emerald-500/15 text-emerald-500' : 'bg-muted text-muted-foreground'}`}>
            {connected ? '已連線' : '未連線'}
          </span>
          <span className={`rounded px-2 py-0.5 text-xs ${controller === 'user' ? 'bg-amber-500/15 text-amber-500' : 'bg-sky-500/15 text-sky-500'}`}>
            {controller === 'user' ? '控制權：主人' : '控制權：大肥魚'}
          </span>
        </div>
        <Button variant="outline" size="sm" onClick={stop} disabled={!running}>
          <X className="mr-1 h-4 w-4" /> 關閉監看
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          className="h-9 min-w-48 rounded-md border bg-background px-2 text-sm"
          value={selectedTarget}
          onChange={(event) => {
            setSelectedTarget(event.target.value)
            send({ action: 'select_target', target_id: event.target.value })
          }}
        >
          {targets.map((target) => <option key={target.id} value={target.id}>{target.title || target.url}</option>)}
        </select>
        <form className="flex min-w-0 flex-1 items-center gap-2" onSubmit={navigate}>
          <Input value={address} onChange={(event) => setAddress(event.target.value)} placeholder="輸入網址後按 Enter" />
          <Button type="submit" size="sm" disabled={controller !== 'user'}>前往</Button>
        </form>
        <Button variant="outline" size="icon" disabled={controller !== 'user'} onClick={() => send({ action: 'back' })} title="上一頁">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="icon" disabled={controller !== 'user'} onClick={() => send({ action: 'reload' })} title="重新整理">
          <RefreshCw className="h-4 w-4" />
        </Button>
        <Button
          size="sm"
          variant={controller === 'user' ? 'default' : 'outline'}
          onClick={() => send({ action: controller === 'user' ? 'release' : 'takeover' })}
        >
          {controller === 'user' ? <RotateCcw className="mr-1 h-4 w-4" /> : <Hand className="mr-1 h-4 w-4" />}
          {controller === 'user' ? '歸還控制權' : '接管控制權'}
        </Button>
      </div>

      {error && <div className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-sm text-destructive">{error}</div>}

      <div
        ref={viewRef}
        tabIndex={0}
        className={`relative min-h-0 flex-1 overflow-hidden rounded-lg border bg-black outline-none ${controller === 'user' ? 'cursor-none ring-1 ring-amber-500/60' : ''}`}
        onMouseMove={(event) => mouse(event, 'mouseMoved')}
        onMouseDown={(event) => mouse(event, 'mousePressed')}
        onMouseUp={(event) => mouse(event, 'mouseReleased')}
        onWheel={wheel}
        onKeyDown={(event) => key(event, 'keyDown')}
        onKeyUp={(event) => key(event, 'keyUp')}
      >
        {frame ? (
          <img src={frame} alt="無頭瀏覽器即時畫面" className="h-full w-full object-contain" draggable={false} />
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <div className="flex items-center gap-2"><MousePointer2 className="h-5 w-5" /> 等待瀏覽器畫面…</div>
          </div>
        )}
      </div>
      <div className="truncate text-xs text-muted-foreground">{currentUrl}</div>
    </div>
  )
}
