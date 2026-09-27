import { Component, ElementRef, afterRenderEffect, computed, inject, signal, viewChild } from '@angular/core';
import { KnowledgeService, pageImageUrl } from '../knowledge-review/knowledge.service';
import { KnowledgeItem } from '../knowledge-review/knowledge.model';
import { findInQueue } from '../knowledge-review/review-queue';
import { FigureAssociationService, finalFigureImageUrl } from './figure-association.service';
import { FigureAssociationStateService } from './figure-association-state.service';
import {
  AssociationFile,
  CandidateView,
  CONFIDENCE_BY_DECISION,
  ConfidenceTier,
  FigureAssociationRow,
  REVIEW_STATUS_LABELS,
  FigureAssociationReviewStatus,
} from './figure-association.model';

/** Matches the math-4eme-tome1-ch01-* id prefix used across the pipeline (see data/src/config.py). */
const CHAPTER_ID = 'math-4eme-tome1-ch01';

const PREVIEW_MAX_CHARS = 160;

type StatusFilter = 'ALL' | FigureAssociationReviewStatus;
type ConfidenceFilter = 'ALL' | ConfidenceTier;

const ITEM_TYPE_LABELS: Record<string, string> = {
  theorem: 'Theorem',
  property: 'Property',
  definition: 'Definition',
  activity: 'Activity',
  exercise: 'Exercise',
  remark: 'Remark',
};

function itemDisplayTitle(item: KnowledgeItem): string {
  if (item.title) return item.title;
  const label = ITEM_TYPE_LABELS[item.type] ?? item.type;
  const numero = item.source?.bloc_numero;
  return numero ? `${label} ${numero}` : label;
}

function itemPreview(item: KnowledgeItem): string {
  const text = (item.original_content ?? '').replace(/\s+/g, ' ').trim();
  return text.length > PREVIEW_MAX_CHARS ? text.slice(0, PREVIEW_MAX_CHARS).trimEnd() + '…' : text;
}

@Component({
  selector: 'app-figure-association',
  templateUrl: './figure-association.html',
  styleUrl: './figure-association.scss',
  host: { '(document:keydown)': 'onKey($event)' },
})
export class FigureAssociation {
  private readonly associations = inject(FigureAssociationService);
  private readonly knowledge = inject(KnowledgeService);
  protected readonly review = inject(FigureAssociationStateService);

  private readonly listEl = viewChild<ElementRef<HTMLElement>>('list');
  private readonly panelEl = viewChild<ElementRef<HTMLElement>>('panel');

  protected readonly file = signal<AssociationFile | null>(null);
  protected readonly itemsById = signal<Map<string, KnowledgeItem> | null>(null);
  protected readonly loadError = signal<string | null>(null);

  protected readonly search = signal('');
  protected readonly statusFilter = signal<StatusFilter>('ALL');
  protected readonly confidenceFilter = signal<ConfidenceFilter>('ALL');
  protected readonly showSource = signal(false);
  protected readonly selectedId = signal<string | null>(null);

  protected readonly statusLabels = REVIEW_STATUS_LABELS;
  protected readonly statusOptions: StatusFilter[] = ['ALL', 'PENDING', 'CONFIRMED', 'REASSIGNED', 'REJECTED'];
  protected readonly confidenceOptions: ConfidenceFilter[] = ['ALL', 'High', 'Medium', 'Low'];
  protected readonly finalFigureImageUrl = finalFigureImageUrl;
  protected readonly pageImageUrl = pageImageUrl;

  /** Static per-figure data (from the generated file + resolved item text), computed once per load. */
  private readonly baseRows = computed<FigureAssociationRow[]>(() => {
    const file = this.file();
    const items = this.itemsById();
    if (!file || !items) return [];
    return file.associations.map((a) => {
      const candidates: CandidateView[] = a.candidates.map((c) => {
        const item = items.get(c.item_id);
        return {
          itemId: c.item_id,
          itemType: c.item_type,
          relation: c.relation,
          title: item ? itemDisplayTitle(item) : c.item_id,
          preview: item ? itemPreview(item) : '',
        };
      });
      return {
        figureId: a.figure_id,
        sourcePage: a.source_page,
        imagePath: a.candidate_image,
        decision: a.decision,
        confidence: CONFIDENCE_BY_DECISION[a.decision],
        candidates,
        reviewStatus: 'PENDING',
        chosenItemId: a.chosen_item_id,
      };
    });
  });

  /** Base rows + current local review overlay. */
  protected readonly rows = computed<FigureAssociationRow[]>(() => {
    this.review.state(); // track signal
    return this.baseRows().map((r) => ({
      ...r,
      reviewStatus: this.review.statusOf(r.figureId),
      chosenItemId: this.review.chosenItemIdOf(r.figureId, r.chosenItemId),
    }));
  });

  protected readonly stats = computed(() => {
    const rows = this.rows();
    const confirmed = rows.filter((r) => r.reviewStatus === 'CONFIRMED').length;
    const reassigned = rows.filter((r) => r.reviewStatus === 'REASSIGNED').length;
    const rejected = rows.filter((r) => r.reviewStatus === 'REJECTED').length;
    const reviewed = confirmed + reassigned + rejected;
    const total = rows.length;
    return {
      total,
      reviewed,
      pending: total - reviewed,
      confirmed,
      reassigned,
      rejected,
      percent: total ? (100 * reviewed) / total : 0,
    };
  });

  protected readonly filtered = computed(() => {
    const q = this.search().trim().toLowerCase();
    const status = this.statusFilter();
    const confidence = this.confidenceFilter();
    return this.rows().filter(
      (r) =>
        (status === 'ALL' || r.reviewStatus === status) &&
        (confidence === 'ALL' || r.confidence === confidence) &&
        (!q || r.figureId.toLowerCase().includes(q) || String(r.sourcePage).includes(q)),
    );
  });

  protected readonly selected = computed(() => this.rows().find((r) => r.figureId === this.selectedId()) ?? null);

  private readonly selectedIndex = computed(() => this.filtered().findIndex((r) => r.figureId === this.selectedId()));

  protected readonly hasPrev = computed(() => this.neighbour(-1) !== -1);
  protected readonly hasNext = computed(() => this.neighbour(1) !== -1);

  constructor() {
    this.review.use(CHAPTER_ID);

    this.knowledge.load().subscribe({
      next: (kb) => this.itemsById.set(new Map(kb.items.map((it) => [it.id, it]))),
      error: () => this.loadError.set('Could not load the knowledge base.'),
    });

    this.associations.load(CHAPTER_ID).subscribe({
      next: (file) => {
        this.file.set(file);
        const first = this.rows().find((r) => r.reviewStatus === 'PENDING') ?? this.rows()[0];
        this.selectedId.set(first?.figureId ?? null);
      },
      error: () => this.loadError.set(`Could not load /associations/${CHAPTER_ID}/figure_knowledge.json.`),
    });

    afterRenderEffect(() => {
      const id = this.selectedId();
      if (!id) return;
      this.listEl()?.nativeElement.querySelector(`[data-id="${id}"]`)?.scrollIntoView({ block: 'nearest' });
      this.panelEl()?.nativeElement.scrollTo({ top: 0 });
    });
  }

  protected select(id: string): void {
    this.selectedId.set(id);
  }

  protected previous(): void {
    this.go(-1);
  }

  protected next(): void {
    this.go(1);
  }

  /** Accept the currently chosen item (algorithm's pick, or a previous reassignment) as correct. */
  protected confirm(): void {
    const current = this.selected();
    if (!current?.chosenItemId) return;
    const relation = current.candidates.find((c) => c.itemId === current.chosenItemId)?.relation ?? null;
    this.advanceAfter(current, () => this.review.confirm(current.figureId, current.chosenItemId!, relation));
  }

  /** Pick a different candidate than the current one. */
  protected chooseAnother(itemId: string): void {
    const current = this.selected();
    if (!current) return;
    const relation = current.candidates.find((c) => c.itemId === itemId)?.relation ?? null;
    this.review.reassign(current.figureId, itemId, relation);
  }

  protected reject(): void {
    const current = this.selected();
    if (!current) return;
    this.advanceAfter(current, () => this.review.reject(current.figureId));
  }

  protected undo(): void {
    const current = this.selected();
    if (current) this.review.clear(current.figureId);
  }

  protected resetAll(): void {
    if (confirm('Clear all local association-review decisions for this chapter? The generated file is not affected.')) {
      this.review.clearAll();
    }
  }

  protected setStatusFilter(value: string): void {
    this.statusFilter.set(value as StatusFilter);
  }

  protected setConfidenceFilter(value: string): void {
    this.confidenceFilter.set(value as ConfidenceFilter);
  }

  protected onKey(e: KeyboardEvent): void {
    const target = e.target as HTMLElement | null;
    if (e.ctrlKey || e.metaKey || e.altKey || target?.closest('input, textarea, select')) return;
    const actions: Record<string, () => void> = {
      j: () => this.next(),
      ArrowDown: () => this.next(),
      k: () => this.previous(),
      ArrowUp: () => this.previous(),
      v: () => this.confirm(),
      r: () => this.reject(),
      u: () => this.undo(),
    };
    const action = actions[e.key];
    if (action) {
      e.preventDefault();
      action();
    }
  }

  private advanceAfter(current: FigureAssociationRow, apply: () => void): void {
    const queue = this.filtered();
    const from = queue.findIndex((r) => r.figureId === current.figureId);
    apply();
    const pending = (r: FigureAssociationRow) => r.figureId !== current.figureId && this.review.statusOf(r.figureId) === 'PENDING';
    const target = findInQueue(queue, from, 1, pending, true);
    if (target !== -1) this.selectedId.set(queue[target].figureId);
  }

  private go(dir: 1 | -1): void {
    const i = this.neighbour(dir);
    if (i !== -1) this.selectedId.set(this.filtered()[i].figureId);
  }

  private neighbour(dir: 1 | -1): number {
    const list = this.filtered();
    const from = this.selectedIndex();
    const start = from === -1 ? (dir === 1 ? -1 : list.length) : from;
    return findInQueue(list, start, dir, () => true);
  }
}
