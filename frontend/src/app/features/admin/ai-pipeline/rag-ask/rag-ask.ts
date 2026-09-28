import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { MathText } from '../../../../shared/math-text/math-text';
import { ANSWER_STATUS_LABELS, AnswerResultRaw, AnswerStatus, chunkLocationLabel } from './rag-ask.model';
import { RagAskService } from './rag-ask.service';

/** Admin test page for the RAG pipeline stage: Semantic Search → RAG
 * Context Assembly → Gemini Answer Generation, via POST /api/v1/ask.
 * Replaces the generic "not implemented yet" PipelineStage placeholder
 * for this one stage -- the pipeline itself IS implemented; this page
 * exists to exercise and inspect it. */
@Component({
  selector: 'app-rag-ask',
  imports: [MathText],
  templateUrl: './rag-ask.html',
  styleUrl: './rag-ask.scss',
})
export class RagAsk {
  private readonly ragAskService = inject(RagAskService);

  protected readonly chapterId = signal('math-4eme-tome1-ch01');
  protected readonly query = signal("Comment étudier les variations d'une fonction ?");
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly result = signal<AnswerResultRaw | null>(null);

  protected readonly statusLabel = (status: AnswerStatus) => ANSWER_STATUS_LABELS[status];
  protected readonly chunkLocationLabel = chunkLocationLabel;

  protected canSubmit(): boolean {
    return this.chapterId().trim().length > 0 && this.query().trim().length > 0;
  }

  protected submit(): void {
    if (!this.canSubmit() || this.loading()) return;
    this.loading.set(true);
    this.error.set(null);
    this.result.set(null);

    this.ragAskService.ask({ chapter_id: this.chapterId().trim(), query: this.query().trim() }).subscribe({
      next: (result) => {
        this.result.set(result);
        this.loading.set(false);
      },
      error: (err: HttpErrorResponse) => {
        this.error.set(this.describeError(err));
        this.loading.set(false);
      },
    });
  }

  private describeError(err: HttpErrorResponse): string {
    const detail = typeof err.error?.detail === 'string' ? err.error.detail : null;
    if (err.status === 422) return detail ?? 'Invalid request.';
    if (err.status === 502) return detail ?? 'The answer-generation provider is currently unavailable.';
    if (err.status === 0) return 'Could not reach the API — is it running (see data/src/api/main.py)?';
    return detail ?? `Request failed (HTTP ${err.status}).`;
  }
}
