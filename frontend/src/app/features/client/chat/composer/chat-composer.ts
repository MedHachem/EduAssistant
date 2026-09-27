import { Component, ElementRef, input, output, signal, viewChild } from '@angular/core';

const MAX_HEIGHT_PX = 200;

@Component({
  selector: 'app-chat-composer',
  template: `
    <form class="composer" (submit)="submit($event)">
      <textarea
        #box
        rows="1"
        [value]="text()"
        (input)="onInput($event)"
        (keydown)="onKeydown($event)"
        placeholder="Pose ta question sur le cours ou un exercice…"
        aria-label="Message"
        enterkeyhint="send"
      ></textarea>
      @if (busy()) {
        <button type="button" class="action stop" (click)="stop.emit()" aria-label="Arrêter la réponse" title="Arrêter">
          <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2" /></svg>
        </button>
      } @else {
        <button type="submit" class="action send" [disabled]="!text().trim()" aria-label="Envoyer" title="Envoyer (Entrée)">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.4 20.4 21 12 3.4 3.6 3.4 10l12.6 2-12.6 2z" /></svg>
        </button>
      }
    </form>
    <p class="hint">Entrée pour envoyer · Maj + Entrée pour aller à la ligne</p>
  `,
  styles: `
    :host { display: block; }
    .composer {
      display: flex;
      align-items: flex-end;
      gap: 0.5rem;
      padding: 0.5rem 0.5rem 0.5rem 1rem;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 1.25rem;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.06);
      transition: border-color 0.15s;
      &:focus-within { border-color: var(--primary); }
    }
    textarea {
      flex: 1;
      min-height: 2.25rem;
      max-height: 200px;
      padding: 0.45rem 0;
      border: none;
      outline: none;
      resize: none;
      background: transparent;
      font: inherit;
      font-size: 0.95rem;
      line-height: 1.4;
      color: var(--text);
      /* Keep the empty box one line tall on narrow screens. */
      &::placeholder { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    }
    .action {
      flex: none;
      display: grid;
      place-items: center;
      width: 2.25rem;
      height: 2.25rem;
      border: none;
      border-radius: 50%;
      cursor: pointer;
      color: #fff;
      transition: background 0.15s, opacity 0.15s;
      svg { width: 1.1rem; height: 1.1rem; fill: currentColor; }
    }
    .send {
      background: var(--primary);
      &:disabled { opacity: 0.35; cursor: default; }
      &:not(:disabled):hover { background: var(--primary-hover); }
    }
    .stop {
      background: var(--text);
      &:hover { background: #000; }
    }
    .hint {
      margin: 0.35rem 0 0;
      text-align: center;
      font-size: 0.7rem;
      color: var(--muted);
    }
    @media (hover: none) {
      .hint { display: none; }
    }
  `,
})
export class ChatComposer {
  readonly busy = input(false);
  readonly send = output<string>();
  readonly stop = output<void>();

  protected readonly text = signal('');
  private readonly box = viewChild.required<ElementRef<HTMLTextAreaElement>>('box');

  focus(): void {
    this.box().nativeElement.focus();
  }

  /** Pre-fills the box (e.g. from a suggestion) without sending. */
  setText(value: string): void {
    this.text.set(value);
    queueMicrotask(() => {
      this.resize();
      this.focus();
    });
  }

  protected onInput(e: Event): void {
    this.text.set((e.target as HTMLTextAreaElement).value);
    this.resize();
  }

  protected onKeydown(e: KeyboardEvent): void {
    // Enter sends, Shift+Enter inserts a new line; ignore while an IME composition is active.
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      this.submit();
    }
  }

  protected submit(e?: Event): void {
    e?.preventDefault();
    const value = this.text().trim();
    if (!value || this.busy()) return;
    this.send.emit(value);
    this.text.set('');
    // Clear the DOM now (the binding updates on the next render) so the height shrinks back immediately.
    this.box().nativeElement.value = '';
    this.resize();
  }

  private resize(): void {
    const el = this.box().nativeElement;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
  }
}
