import { Injectable, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';
import { renderToHtml } from '../../../shared/math-text/math-text';
import { ClientFrame, ServerFrame } from './chat-protocol';
import { ConnectionStatus } from './chat.model';
import { ChatStore } from './chat.store';
import { ChatComposer } from './composer/chat-composer';
import { ChatTransport } from './transport/chat-transport';
import { resolveWsUrl } from './transport/websocket-chat-transport';

@Injectable()
class FakeTransport extends ChatTransport {
  readonly status = signal<ConnectionStatus>('connected');
  readonly subject = new Subject<ServerFrame>();
  readonly frames = this.subject.asObservable();
  readonly sent: ClientFrame[] = [];
  connect(): void {}
  disconnect(): void {}
  send(frame: ClientFrame): void {
    this.sent.push(frame);
  }
}

describe('ChatStore', () => {
  let store: ChatStore;
  let transport: FakeTransport;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [ChatStore, FakeTransport, { provide: ChatTransport, useExisting: FakeTransport }],
    });
    store = TestBed.inject(ChatStore);
    transport = TestBed.inject(FakeTransport);
  });

  function userFrame() {
    const f = transport.sent.at(-1)!;
    if (f.type !== 'user_message') throw new Error('expected user_message');
    return f;
  }

  it('creates a conversation on first message and sends a user_message frame', () => {
    store.send('  Explique la continuité  ');
    expect(store.conversations().length).toBe(1);
    expect(store.active()!.title).toBe('Explique la continuité');
    expect(userFrame().content).toBe('Explique la continuité');
    expect(store.awaitingReply()).toBe(true);
    expect(store.busy()).toBe(true);
  });

  it('builds the assistant answer from start / delta / end frames', () => {
    store.send('Bonjour');
    const { conversationId, messageId } = userFrame();

    transport.subject.next({ type: 'assistant_start', conversationId, messageId: 'a1', replyTo: messageId });
    expect(store.streaming()).toBe(true);
    expect(store.awaitingReply()).toBe(false);

    transport.subject.next({ type: 'assistant_delta', conversationId, messageId: 'a1', delta: 'Bonjour ' });
    transport.subject.next({ type: 'assistant_delta', conversationId, messageId: 'a1', delta: '$x$ !' });
    transport.subject.next({ type: 'assistant_end', conversationId, messageId: 'a1' });

    const answer = store.messages().at(-1)!;
    expect(answer).toMatchObject({ role: 'assistant', content: 'Bonjour $x$ !', status: 'done', replyTo: messageId });
    expect(store.busy()).toBe(false);
  });

  it('ignores new messages while an answer is in progress', () => {
    store.send('Q1');
    store.send('Q2');
    expect(store.messages().length).toBe(1);
  });

  it('cancels a streaming answer and ignores further deltas', () => {
    store.send('Q');
    const { conversationId, messageId } = userFrame();
    transport.subject.next({ type: 'assistant_start', conversationId, messageId: 'a1', replyTo: messageId });
    transport.subject.next({ type: 'assistant_delta', conversationId, messageId: 'a1', delta: 'Début' });

    store.cancel();
    expect(transport.sent.at(-1)).toEqual({ type: 'cancel', conversationId, replyTo: messageId });
    transport.subject.next({ type: 'assistant_delta', conversationId, messageId: 'a1', delta: ' suite' });

    expect(store.messages().at(-1)).toMatchObject({ content: 'Début', status: 'cancelled' });
    expect(store.busy()).toBe(false);
  });

  it('cancelling before the first token drops the late answer', () => {
    store.send('Q');
    const { conversationId, messageId } = userFrame();
    store.cancel();
    transport.subject.next({ type: 'assistant_start', conversationId, messageId: 'a1', replyTo: messageId });
    expect(store.messages().length).toBe(1);
    expect(store.messages()[0].status).toBe('cancelled');
  });

  it('marks messages sent while disconnected as pending, then sent on connection', () => {
    transport.status.set('reconnecting');
    store.send('Q');
    expect(store.messages()[0].status).toBe('pending');
    transport.status.set('connected');
    TestBed.tick();
    expect(store.messages()[0].status).toBe('sent');
  });

  it('attaches server errors to the related message', () => {
    store.send('Q');
    const { conversationId, messageId } = userFrame();
    transport.subject.next({ type: 'error', conversationId, messageId, message: 'Service indisponible' });
    expect(store.messages()[0]).toMatchObject({ status: 'error', error: 'Service indisponible' });
    expect(store.busy()).toBe(false);
  });

  it('persists conversations in localStorage', () => {
    store.send('Q');
    TestBed.tick();
    const saved = JSON.parse(localStorage.getItem('edu.chat.v1.anonymous')!);
    expect(saved[0].messages[0].content).toBe('Q');
  });
});

describe('ChatComposer', () => {
  it('sends on Enter, keeps Shift+Enter for new lines', async () => {
    const fixture = TestBed.createComponent(ChatComposer);
    const sent: string[] = [];
    fixture.componentInstance.send.subscribe((v) => sent.push(v));
    await fixture.whenStable();
    const box = (fixture.nativeElement as HTMLElement).querySelector('textarea')!;

    box.value = 'ligne 1';
    box.dispatchEvent(new Event('input'));
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true }));
    expect(sent).toEqual([]);

    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    expect(sent).toEqual(['ligne 1']);
  });
});

describe('light markdown + ws url', () => {
  it('renders bold, bullets and headings only when enabled', () => {
    const src = '### Titre\n- **important** $x$';
    const html = renderToHtml(src, true);
    expect(html).toContain('<strong class="md-heading">Titre</strong>');
    expect(html).toContain('• <strong>important</strong>');
    expect(renderToHtml(src)).not.toContain('<strong>');
  });

  it('resolves relative WebSocket URLs against the current host', () => {
    expect(resolveWsUrl('/ws/chat', { protocol: 'https:', host: 'edu.tn' } as Location)).toBe('wss://edu.tn/ws/chat');
    expect(resolveWsUrl('/ws/chat', { protocol: 'http:', host: 'localhost:4200' } as Location)).toBe('ws://localhost:4200/ws/chat');
    expect(resolveWsUrl('ws://api:8080/ws')).toBe('ws://api:8080/ws');
  });
});
