import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import { Subject } from 'rxjs';
import { environment } from '../../../../../environments/environment';
import { ClientFrame, ServerFrame } from '../chat-protocol';
import { ConnectionStatus } from '../chat.model';
import { ChatTransport } from './chat-transport';

const MAX_BACKOFF_MS = 30_000;

/** Resolves a relative path such as "/ws/chat" to ws(s)://<current host>/ws/chat. */
export function resolveWsUrl(url: string, loc: Location = location): string {
  if (/^wss?:\/\//.test(url)) return url;
  const scheme = loc.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${loc.host}${url.startsWith('/') ? '' : '/'}${url}`;
}

/**
 * Real transport: one WebSocket per session, automatic reconnection with exponential
 * backoff, outgoing queue while disconnected.
 * TODO(auth): pass the JWT (e.g. as a query param or first frame) once real auth exists.
 */
@Injectable()
export class WebSocketChatTransport extends ChatTransport {
  private readonly url = resolveWsUrl(environment.chat.wsUrl);
  private socket: WebSocket | null = null;
  private readonly queue: ClientFrame[] = [];
  private retries = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private manualClose = false;

  private readonly _status = signal<ConnectionStatus>('idle');
  private readonly _frames = new Subject<ServerFrame>();

  readonly status = this._status.asReadonly();
  readonly frames = this._frames.asObservable();

  constructor() {
    super();
    const onOnline = () => this.reconnectNow();
    const onOffline = () => this._status.set('offline');
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    inject(DestroyRef).onDestroy(() => {
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
      this.disconnect();
    });
  }

  connect(): void {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;
    this.manualClose = false;
    this._status.set(this.retries ? 'reconnecting' : 'connecting');

    const ws = new WebSocket(this.url);
    this.socket = ws;

    ws.onopen = () => {
      this.retries = 0;
      this._status.set('connected');
      while (this.queue.length) ws.send(JSON.stringify(this.queue.shift()));
    };
    ws.onmessage = (event) => {
      try {
        this._frames.next(JSON.parse(event.data as string) as ServerFrame);
      } catch {
        console.warn('[chat] ignored non-JSON frame', event.data);
      }
    };
    ws.onclose = () => {
      this.socket = null;
      if (this.manualClose) {
        this._status.set('idle');
        return;
      }
      this.scheduleReconnect();
    };
    // onerror is always followed by onclose; reconnection is handled there.
  }

  disconnect(): void {
    this.manualClose = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.socket?.close();
    this.socket = null;
    this._status.set('idle');
  }

  send(frame: ClientFrame): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(frame));
    } else {
      this.queue.push(frame);
      this.connect();
    }
  }

  private scheduleReconnect(): void {
    if (!navigator.onLine) {
      this._status.set('offline');
      return;
    }
    this._status.set('reconnecting');
    const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.retries) + Math.random() * 500;
    this.retries++;
    this.retryTimer = setTimeout(() => this.connect(), delay);
  }

  private reconnectNow(): void {
    if (this.manualClose) return;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.connect();
  }
}
