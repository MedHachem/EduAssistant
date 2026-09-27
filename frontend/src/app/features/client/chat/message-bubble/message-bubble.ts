import { DatePipe } from '@angular/common';
import { Component, input, output, signal } from '@angular/core';
import { MathText } from '../../../../shared/math-text/math-text';
import { ChatMessage } from '../chat.model';

@Component({
  selector: 'app-message-bubble',
  imports: [MathText, DatePipe],
  template: `
    @let m = message();
    <div class="row" [class.user]="m.role === 'user'" [class.assistant]="m.role === 'assistant'">
      @if (m.role === 'assistant') {
        <span class="avatar" aria-hidden="true">IA</span>
      }
      <div class="stack">
        <div class="bubble" [class.streaming]="m.status === 'streaming'">
          @if (m.content) {
            <app-math-text [text]="m.content" [markdown]="m.role === 'assistant'" />
          }
          @if (m.status === 'streaming' && !m.content) {
            <span class="cursor" aria-hidden="true"></span>
          }
        </div>
        <div class="meta">
          <span>{{ m.createdAt | date: 'HH:mm' }}</span>
          @switch (m.status) {
            @case ('pending') { <span>· En attente de connexion…</span> }
            @case ('cancelled') {
              <span>· {{ m.role === 'assistant' ? 'Réponse interrompue' : 'Annulé' }}</span>
            }
            @case ('error') { <span class="error">· {{ m.error ?? 'Erreur' }}</span> }
          }
          @if (m.role === 'user' && (m.status === 'cancelled' || m.status === 'error')) {
            <button type="button" class="link" (click)="retry.emit(m)">Réessayer</button>
          }
          @if (m.role === 'assistant' && m.status === 'done') {
            <button type="button" class="link" (click)="copy(m.content)">{{ copied() ? 'Copié ✓' : 'Copier' }}</button>
          }
        </div>
      </div>
    </div>
  `,
  styles: `
    .row {
      display: flex;
      gap: 0.6rem;
      align-items: flex-start;
      &.user { justify-content: flex-end; }
    }
    .avatar {
      flex: none;
      display: grid;
      place-items: center;
      width: 2rem;
      height: 2rem;
      border-radius: 50%;
      background: var(--primary-soft);
      color: var(--primary);
      font-size: 0.72rem;
      font-weight: 800;
    }
    .stack {
      display: flex;
      flex-direction: column;
      min-width: 0;
      max-width: min(46rem, 85%);
    }
    .user .stack { align-items: flex-end; }
    .bubble {
      padding: 0.65rem 0.9rem;
      border-radius: 1.1rem;
      overflow-wrap: anywhere;
      min-width: 0;
      max-width: 100%;
    }
    .user .bubble {
      background: var(--primary);
      color: #fff;
      border-bottom-right-radius: 0.3rem;
    }
    .assistant .bubble {
      background: var(--surface);
      border: 1px solid var(--border);
      border-top-left-radius: 0.3rem;
    }
    /* Cursor at the end of the streamed text (inside MathText's rendered block). */
    .bubble.streaming ::ng-deep .math-rendered::after,
    .cursor {
      content: '';
      display: inline-block;
      width: 0.5rem;
      height: 1rem;
      margin-left: 0.1rem;
      vertical-align: text-bottom;
      background: var(--primary);
      animation: blink 1s steps(2, start) infinite;
    }
    @keyframes blink { to { visibility: hidden; } }
    .meta {
      display: flex;
      gap: 0.3rem;
      align-items: center;
      padding: 0.2rem 0.4rem 0;
      font-size: 0.7rem;
      color: var(--muted);
    }
    .error { color: #a12626; }
    .link {
      padding: 0;
      margin-left: 0.3rem;
      border: none;
      background: none;
      font: inherit;
      color: var(--primary);
      cursor: pointer;
      &:hover { text-decoration: underline; }
    }
    @media (max-width: 640px) {
      .avatar { display: none; }
      .stack { max-width: 92%; }
    }
  `,
})
export class MessageBubble {
  readonly message = input.required<ChatMessage>();
  readonly retry = output<ChatMessage>();

  protected readonly copied = signal(false);

  protected async copy(text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1500);
    } catch {
      // Clipboard unavailable (insecure context / permissions): ignore.
    }
  }
}
