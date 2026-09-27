import { Component, input } from '@angular/core';
import { Question } from '../knowledge.model';
import { MathText } from '../../../../shared/math-text/math-text';

/** Renders question → sub_questions → … recursively, keeping the source hierarchy (1 / a, b, c). */
@Component({
  selector: 'app-question-tree',
  imports: [MathText],
  template: `
    <ol class="q-list" [class.nested]="depth() > 0">
      @for (q of questions(); track $index) {
        <li class="q-item">
          <div class="q-row">
            <span class="q-label">{{ q.label ? q.label + '.' : '•' }}</span>
            @if (q.text) {
              <app-math-text class="q-text" [text]="q.text" [raw]="raw()" />
            }
          </div>
          @if (q.sub_questions.length) {
            <app-question-tree [questions]="q.sub_questions" [raw]="raw()" [depth]="depth() + 1" />
          }
        </li>
      }
    </ol>
  `,
  styles: `
    .q-list {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .q-list.nested {
      margin-top: 0.35rem;
      padding-left: 1.75rem;
      border-left: 2px solid var(--border);
    }
    .q-item + .q-item {
      margin-top: 0.5rem;
    }
    .q-row {
      display: flex;
      gap: 0.5rem;
      align-items: baseline;
    }
    .q-label {
      flex: none;
      min-width: 1.75rem;
      font-weight: 700;
      color: var(--primary);
    }
    .q-text {
      flex: 1;
      min-width: 0;
    }
  `,
})
export class QuestionTree {
  readonly questions = input.required<Question[]>();
  readonly raw = input(false);
  readonly depth = input(0);
}
