import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AuthService } from '../../../core/auth/auth.service';
import { ServerFrame } from './chat-protocol';
import { ChatMessage, Conversation } from './chat.model';
import { ChatTransport } from './transport/chat-transport';

const STORAGE_PREFIX = 'edu.chat.v1.';
const TITLE_LENGTH = 48;

function now(): string {
  return new Date().toISOString();
}

function titleFrom(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length > TITLE_LENGTH ? flat.slice(0, TITLE_LENGTH - 1) + '…' : flat;
}

/**
 * State of the student ↔ AI Teacher chat, driven by transport frames.
 * Conversations are kept in localStorage for now (temporary, until the backend owns history).
 */
@Injectable()
export class ChatStore {
  private readonly transport = inject(ChatTransport);
  private readonly storageKey = STORAGE_PREFIX + (inject(AuthService).currentUser()?.id ?? 'anonymous');

  private readonly _conversations = signal<Conversation[]>(this.restore());
  private readonly _activeId = signal<string | null>(null);
  /** User message ids whose answer was cancelled before it started. */
  private readonly cancelled = new Set<string>();

  readonly connection = this.transport.status;

  /** Most recently updated first. */
  readonly conversations = computed(() =>
    [...this._conversations()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
  );
  readonly activeId = this._activeId.asReadonly();
  readonly active = computed(() => this._conversations().find((c) => c.id === this._activeId()) ?? null);
  readonly messages = computed(() => this.active()?.messages ?? []);

  /** Last user message is waiting for the first token. */
  readonly awaitingReply = computed(() => {
    const last = this.messages().at(-1);
    return last?.role === 'user' && (last.status === 'sent' || last.status === 'pending');
  });
  readonly streaming = computed(() => this.messages().at(-1)?.status === 'streaming');
  readonly busy = computed(() => this.awaitingReply() || this.streaming());

  constructor() {
    this.transport.frames.pipe(takeUntilDestroyed()).subscribe((f) => this.onFrame(f));
    this.transport.connect();

    // Queued messages are flushed by the transport once connected.
    effect(() => {
      if (this.connection() === 'connected') this.updateAllMessages((m) => (m.status === 'pending' ? { ...m, status: 'sent' } : m));
    });

    effect(() => localStorage.setItem(this.storageKey, JSON.stringify(this._conversations())));
  }

  select(id: string): void {
    this._activeId.set(id);
  }

  /** Starts a draft; the conversation is created on the first message. */
  newConversation(): void {
    this._activeId.set(null);
  }

  delete(id: string): void {
    this._conversations.update((list) => list.filter((c) => c.id !== id));
    if (this._activeId() === id) this._activeId.set(null);
  }

  send(text: string): void {
    const content = text.trim();
    if (!content || this.busy()) return;

    let conversationId = this._activeId();
    if (!conversationId || !this.active()) {
      conversationId = crypto.randomUUID();
      const created: Conversation = { id: conversationId, title: titleFrom(content), createdAt: now(), updatedAt: now(), messages: [] };
      this._conversations.update((list) => [created, ...list]);
      this._activeId.set(conversationId);
    }

    const message: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      createdAt: now(),
      status: this.connection() === 'connected' ? 'sent' : 'pending',
    };
    this.append(conversationId, message);
    this.transport.send({ type: 'user_message', conversationId, messageId: message.id, content });
  }

  /** Stops the current answer (or the pending request). */
  cancel(): void {
    const conv = this.active();
    const last = conv?.messages.at(-1);
    if (!conv || !last) return;

    if (last.role === 'assistant' && last.status === 'streaming' && last.replyTo) {
      this.transport.send({ type: 'cancel', conversationId: conv.id, replyTo: last.replyTo });
      this.patch(conv.id, last.id, { status: 'cancelled' });
    } else if (last.role === 'user' && this.awaitingReply()) {
      this.cancelled.add(last.id);
      this.transport.send({ type: 'cancel', conversationId: conv.id, replyTo: last.id });
      this.patch(conv.id, last.id, { status: 'cancelled' });
    }
  }

  /** Re-sends a failed or cancelled user message as a new one. */
  retry(message: ChatMessage): void {
    if (message.role === 'user') this.send(message.content);
  }

  private onFrame(f: ServerFrame): void {
    switch (f.type) {
      case 'assistant_start':
        if (this.cancelled.delete(f.replyTo)) return;
        this.append(f.conversationId, {
          id: f.messageId,
          role: 'assistant',
          content: '',
          createdAt: now(),
          status: 'streaming',
          replyTo: f.replyTo,
        });
        this.patch(f.conversationId, f.replyTo, { status: 'done' });
        break;
      case 'assistant_delta':
        this.patch(f.conversationId, f.messageId, (m) =>
          m.status === 'streaming' ? { content: m.content + f.delta } : {},
        );
        break;
      case 'assistant_end':
        this.patch(f.conversationId, f.messageId, (m) => (m.status === 'streaming' ? { status: 'done' } : {}));
        break;
      case 'error':
        if (f.conversationId && f.messageId) {
          this.patch(f.conversationId, f.messageId, { status: 'error', error: f.message });
        } else {
          console.warn('[chat] server error', f.message);
        }
        break;
    }
  }

  private append(conversationId: string, message: ChatMessage): void {
    this.updateConversation(conversationId, (c) => ({ ...c, updatedAt: now(), messages: [...c.messages, message] }));
  }

  private patch(
    conversationId: string,
    messageId: string,
    change: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>),
  ): void {
    this.updateConversation(conversationId, (c) => ({
      ...c,
      messages: c.messages.map((m) =>
        m.id === messageId ? { ...m, ...(typeof change === 'function' ? change(m) : change) } : m,
      ),
    }));
  }

  private updateConversation(id: string, fn: (c: Conversation) => Conversation): void {
    this._conversations.update((list) => list.map((c) => (c.id === id ? fn(c) : c)));
  }

  private updateAllMessages(fn: (m: ChatMessage) => ChatMessage): void {
    this._conversations.update((list) => list.map((c) => ({ ...c, messages: c.messages.map(fn) })));
  }

  private restore(): Conversation[] {
    try {
      const list = JSON.parse(localStorage.getItem(this.storageKey) ?? '[]') as Conversation[];
      // An answer interrupted by a reload can't resume: mark it cancelled (the user can retry).
      return list.map((c) => ({
        ...c,
        messages: c.messages.map((m) =>
          m.status === 'streaming' || m.status === 'pending' || m.status === 'sent' ? { ...m, status: 'cancelled' } : m,
        ),
      }));
    } catch {
      return [];
    }
  }
}
