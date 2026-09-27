import { Component, computed, input } from '@angular/core';
import { FigureLink, KnowledgeBase, KnowledgeItem } from '../knowledge.model';
import { basename, formatPages, typeLabel } from '../knowledge-format';
import { pageImageUrl } from '../knowledge.service';
import { MathText } from '../../../../shared/math-text/math-text';
import { QuestionTree } from '../question-tree/question-tree';
import { ReviewEntry } from '../review-state.service';

/** Read-only presentation of one generated KnowledgeItem. */
@Component({
  selector: 'app-item-detail',
  imports: [MathText, QuestionTree],
  templateUrl: './item-detail.html',
  styleUrl: './item-detail.scss',
})
export class ItemDetail {
  readonly item = input.required<KnowledgeItem>();
  readonly kb = input.required<KnowledgeBase>();
  readonly review = input<ReviewEntry | undefined>();
  readonly raw = input(false);
  readonly showSource = input(false);

  protected readonly typeLabel = typeLabel;
  protected readonly basename = basename;
  protected readonly pageImageUrl = pageImageUrl;

  protected readonly pages = computed(() => formatPages(this.item().source.pdf_pages));

  protected readonly section = computed(() => {
    const s = this.kb().sections.find((x) => x.id === this.item().section_id);
    return s ? (s.label === s.title ? s.title : `${s.label}. ${s.title}`) : null;
  });

  protected readonly subsection = computed(() => {
    const s = this.kb().subsections.find((x) => x.id === this.item().subsection_id);
    return s ? (s.label === s.title ? s.title : `${s.label} ${s.title}`) : null;
  });

  protected readonly chapter = computed(() => {
    const c = this.kb().chapter;
    return `Chapitre ${c.number} — ${c.title}`;
  });

  protected readonly figures = computed(() => this.item().links?.figures ?? []);

  /** Only web-relative image paths are displayed; local filesystem paths can't be loaded by the browser. */
  protected figureImage(f: FigureLink): string | null {
    const p = f.image_path;
    return p && (p.startsWith('/') || p.startsWith('http')) && !/^[a-zA-Z]:/.test(p) ? p : null;
  }
}
