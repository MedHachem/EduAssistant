import { Signal } from '@angular/core';
import { Observable } from 'rxjs';
import { ClientFrame, ServerFrame } from '../chat-protocol';
import { ConnectionStatus } from '../chat.model';

/**
 * Transport between the chat UI and the AI Teacher.
 * Implemented by WebSocketChatTransport (real API) and MockChatTransport (local simulation).
 */
export abstract class ChatTransport {
  abstract readonly status: Signal<ConnectionStatus>;
  abstract readonly frames: Observable<ServerFrame>;
  abstract connect(): void;
  abstract disconnect(): void;
  /** Frames sent while disconnected are queued and flushed on (re)connection. */
  abstract send(frame: ClientFrame): void;
}
