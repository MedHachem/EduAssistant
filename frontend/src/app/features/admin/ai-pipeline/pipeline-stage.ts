import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { DocumentsStore } from '../../../core/documents/documents.store';
import { PipelineStageInfo } from './pipeline-stages';

@Component({
  selector: 'app-pipeline-stage',
  imports: [RouterLink],
  template: `
    @if (stage(); as s) {
      <header class="page-header">
        <span class="kicker">Build AI Pipeline</span>
        <h1>{{ s.title }} <span class="soon">Next phase</span></h1>
        <p>{{ s.description }}</p>
      </header>

      <div class="grid">
        <section class="card">
          <h2>Planned steps</h2>
          <ol>
            @for (step of s.steps; track step) { <li>{{ step }}</li> }
          </ol>
        </section>

        <section class="card">
          <h2>Input</h2>
          <p>
            Runs on documents uploaded in <a routerLink="/admin/data-injection">Data injection</a>
            — currently <strong>{{ documentCount() }}</strong> in the library.
          </p>
          @if (s.scripts.length) {
            <h2>Pipeline scripts</h2>
            <ul class="scripts">
              @for (sc of s.scripts; track sc) { <li><code>data/src/{{ sc }}</code></li> }
            </ul>
          }
        </section>
      </div>
    }
  `,
  styles: `
    .kicker { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--primary); }
    h1 { display: flex; align-items: center; gap: 0.6rem; }
    .soon { padding: 0.15rem 0.55rem; border-radius: 999px; background: #fff4d6; color: #8a5a00; font-size: 0.72rem; font-weight: 600; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; max-width: 1000px; }
    h2 { margin: 0 0 0.6rem; font-size: 0.95rem; }
    h2:not(:first-child) { margin-top: 1rem; }
    ol, .scripts { margin: 0; padding-left: 1.2rem; font-size: 0.875rem; line-height: 1.8; }
    p { margin: 0; font-size: 0.875rem; }
    a { color: var(--primary); }
    code { font-size: 0.8rem; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
  `,
})
export class PipelineStage {
  private readonly store = inject(DocumentsStore);

  protected readonly stage = toSignal(inject(ActivatedRoute).data.pipe(map((d) => d['stage'] as PipelineStageInfo)));
  protected readonly documentCount = computed(() => this.store.documents().length);

  constructor() {
    this.store.refresh();
  }
}
