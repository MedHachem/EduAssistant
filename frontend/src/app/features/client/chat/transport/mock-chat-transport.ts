import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import { Subject } from 'rxjs';
import { ClientFrame, ServerFrame, UserMessageFrame } from '../chat-protocol';
import { ConnectionStatus } from '../chat.model';
import { ChatTransport } from './chat-transport';

const CANNED: { match: RegExp; answer: string }[] = [
  {
    match: /th[ée]or[èe]me des valeurs interm/i,
    answer:
      "Le **théorème des valeurs intermédiaires** dit ceci :\n\nSi f est continue sur un intervalle $[a, b]$, alors pour tout réel k compris entre $f(a)$ et $f(b)$, l'équation $f(x) = k$ admet au moins une solution dans $[a, b]$.\n\nCas particulier très utilisé : si $f(a) \\cdot f(b) < 0$, alors f s'annule au moins une fois sur $]a, b[$.\n\nVeux-tu qu'on l'applique ensemble sur un exemple ?",
  },
  {
    match: /continu/i,
    answer:
      "Une fonction f est **continue en un réel a** de son ensemble de définition si\n\n$$\\lim_{x \\to a} f(x) = f(a).$$\n\nÀ retenir :\n- toute fonction polynôme est continue sur $\\mathbb{R}$ ;\n- toute fonction rationnelle est continue sur son ensemble de définition ;\n- les fonctions $x \\mapsto \\sin x$ et $x \\mapsto \\cos x$ sont continues sur $\\mathbb{R}$.\n\nQuelle fonction veux-tu étudier ?",
  },
  {
    match: /limite|lim/i,
    answer:
      "Pour calculer une limite, commence toujours par **remplacer directement**. Si tu obtiens une forme indéterminée comme $\\dfrac{0}{0}$ ou $\\infty - \\infty$, il faut transformer l'expression.\n\nExemple : pour $x \\neq 1$,\n\n$$\\frac{2x^2-4x+2}{|x-1|} = 2|x-1|,$$\n\ndonc $\\lim_{x \\to 1} \\dfrac{2x^2-4x+2}{|x-1|} = 0$.\n\nEnvoie-moi la limite qui te pose problème et on la fait étape par étape.",
  },
];

const FALLBACK =
  "Bonne question ! Je suis ton assistant pour le chapitre **Continuité et limites**.\n\nPeux-tu préciser ce que tu cherches : une définition, un théorème, ou de l'aide sur un exercice ? Tu peux écrire les formules en LaTeX, par exemple $\\lim_{x \\to +\\infty} f(x)$.";

/**
 * Local stand-in for the AI Teacher while the WebSocket API is being developed.
 * Speaks exactly the same protocol as the real server (assistant_start → deltas → end).
 */
@Injectable()
export class MockChatTransport extends ChatTransport {
  private readonly _status = signal<ConnectionStatus>('idle');
  private readonly _frames = new Subject<ServerFrame>();
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();

  readonly status = this._status.asReadonly();
  readonly frames = this._frames.asObservable();

  constructor() {
    super();
    inject(DestroyRef).onDestroy(() => this.disconnect());
  }

  connect(): void {
    if (this._status() === 'connected' || this._status() === 'connecting') return;
    this._status.set('connecting');
    setTimeout(() => this._status.set('connected'), 400);
  }

  disconnect(): void {
    this.timers.forEach(clearTimeout);
    this.timers.clear();
    this._status.set('idle');
  }

  send(frame: ClientFrame): void {
    if (frame.type === 'user_message') this.answer(frame);
    else this.stop(frame.replyTo);
  }

  private answer(frame: UserMessageFrame): void {
    const messageId = crypto.randomUUID();
    const { conversationId } = frame;
    const text = CANNED.find((c) => c.match.test(frame.content))?.answer ?? FALLBACK;
    // Stream word by word, keeping whitespace, like a token stream.
    const chunks = text.match(/\S+\s*/g) ?? [text];
    let i = 0;

    const tick = () => {
      if (i === 0) this._frames.next({ type: 'assistant_start', conversationId, messageId, replyTo: frame.messageId });
      if (i < chunks.length) {
        this._frames.next({ type: 'assistant_delta', conversationId, messageId, delta: chunks[i++] });
        this.timers.set(frame.messageId, setTimeout(tick, 25 + Math.random() * 45));
      } else {
        this._frames.next({ type: 'assistant_end', conversationId, messageId });
        this.timers.delete(frame.messageId);
      }
    };
    // "Thinking" delay before the first token.
    this.timers.set(frame.messageId, setTimeout(tick, 700));
  }

  private stop(replyTo: string): void {
    clearTimeout(this.timers.get(replyTo));
    this.timers.delete(replyTo);
  }
}
