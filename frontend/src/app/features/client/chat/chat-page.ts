import { Component, ElementRef, afterRenderEffect, computed, inject, signal, viewChild } from '@angular/core';
import { ConnectionStatus, Conversation } from './chat.model';
import { ChatStore } from './chat.store';
import { ChatComposer } from './composer/chat-composer';
import { MessageBubble } from './message-bubble/message-bubble';

/** Distance from the bottom (px) under which the thread keeps following new content. */
const STICK_THRESHOLD = 80;

const CONNECTION_LABELS: Record<ConnectionStatus, string> = {
  idle: 'Déconnecté',
  connecting: 'Connexion…',
  connected: 'En ligne',
  reconnecting: 'Reconnexion…',
  offline: 'Hors ligne',
};

@Component({
  selector: 'app-chat-page',
  imports: [ChatComposer, MessageBubble],
  templateUrl: './chat-page.html',
  styleUrl: './chat-page.scss',
  host: { '(document:keydown.escape)': 'drawerOpen.set(false)' },
})
export class ChatPage {
  protected readonly store = inject(ChatStore);

  private readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');
  private readonly composer = viewChild.required(ChatComposer);

  protected readonly drawerOpen = signal(false);
  protected readonly atBottom = signal(true);
  protected readonly connectionLabel = computed(() => CONNECTION_LABELS[this.store.connection()]);

  protected readonly suggestions = [
    "Qu'est-ce qu'une fonction continue en un réel a ?",
    'Explique-moi le théorème des valeurs intermédiaires',
    'Comment calculer une limite en +∞ ?',
    'Comment lever une forme indéterminée 0/0 ?',
  ];

  constructor() {
    // Follow the stream while the student is at the bottom; don't yank them down if they scrolled up.
    afterRenderEffect(() => {
      this.store.messages();
      this.store.awaitingReply();
      const el = this.scroller()?.nativeElement;
      if (el && this.atBottom()) el.scrollTop = el.scrollHeight;
    });
  }

  protected send(text: string): void {
    this.atBottom.set(true);
    this.store.send(text);
  }

  protected newConversation(): void {
    this.store.newConversation();
    this.drawerOpen.set(false);
    this.composer().focus();
  }

  protected open(c: Conversation): void {
    this.store.select(c.id);
    this.atBottom.set(true);
    this.drawerOpen.set(false);
  }

  protected remove(c: Conversation, e: Event): void {
    e.stopPropagation();
    if (confirm(`Supprimer la conversation « ${c.title} » ?`)) this.store.delete(c.id);
  }

  protected onScroll(el: HTMLElement): void {
    this.atBottom.set(el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD);
  }

  protected scrollToBottom(): void {
    const el = this.scroller()?.nativeElement;
    el?.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }

  protected when(iso: string): string {
    const d = new Date(iso);
    const today = new Date();
    return d.toDateString() === today.toDateString()
      ? d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' });
  }
}
