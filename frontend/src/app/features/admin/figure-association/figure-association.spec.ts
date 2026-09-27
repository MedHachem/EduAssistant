import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { KnowledgeBase, KnowledgeItem } from '../knowledge-review/knowledge.model';
import { AssociationCandidateRaw, AssociationFile, FigureAssociationRaw } from './figure-association.model';
import { FigureAssociation } from './figure-association';
import { FigureAssociationStateService } from './figure-association-state.service';

const CHAPTER = 'math-4eme-tome1-ch01';
const REVIEWS_URL = `/api/chapters/${CHAPTER}/reviews`;

function item(id: string, patch: Partial<KnowledgeItem> = {}): KnowledgeItem {
  return {
    id,
    type: 'theorem',
    document_id: 'doc',
    chapter_id: CHAPTER,
    section_id: 'sec-a',
    subsection_id: null,
    title: null,
    source: {
      document_id: 'doc',
      pdf_pages: [18],
      reconstructed_sources: [],
      bloc_type: 'theoreme',
      bloc_numero: null,
      continues_from_previous_page: false,
      continues_on_next_page: false,
    },
    original_content: 'Some theorem content used as a preview in the review UI.',
    proof: null,
    concepts: [],
    links: null,
    exercise_details: null,
    extracted_from: null,
    uncertainty: { has_uncertain_markers: false, has_gap_markers: false, uncertain_spans: [] },
    validation_status: 'VALIDATED',
    validation_history: [],
    created_at: '',
    schema_version: '1',
    ...patch,
  };
}

function knowledgeBase(items: KnowledgeItem[]): KnowledgeBase {
  return {
    document: { id: 'doc', title: '', subject: '', level: '', country: '', source_pdf: '', total_pages: 1 },
    chapter: { id: CHAPTER, document_id: 'doc', number: 1, title: '', pdf_page_start: 1, pdf_page_end: 27 },
    sections: [],
    subsections: [],
    concepts: [],
    items,
  };
}

function candidate(itemId: string, patch: Partial<AssociationCandidateRaw> = {}): AssociationCandidateRaw {
  return {
    association_id: `assoc-${CHAPTER}-figure_001-${itemId}`,
    item_id: itemId,
    item_type: 'theorem',
    relation: 'illustrates',
    score: 0.8,
    signals: { same_page: true, neighboring_page: false, same_section: true, same_subsection: false, reading_order_proximity: 0.8 },
    ...patch,
  };
}

function figureAssociation(figureId: string, patch: Partial<FigureAssociationRaw> = {}): FigureAssociationRaw {
  return {
    figure_id: figureId,
    chapter_id: CHAPTER,
    source_page: 18,
    candidate_image: `${figureId}.png`,
    decision: 'REVIEW_REQUIRED',
    review_status: 'PENDING',
    chosen_association_id: `assoc-${CHAPTER}-${figureId}-it-1`,
    chosen_item_id: 'it-1',
    relation: 'illustrates',
    score: 0.8,
    candidates: [candidate('it-1'), candidate('it-2', { score: 0.6, relation: 'related_to' })],
    ...patch,
  };
}

function associationFile(associations: FigureAssociationRaw[]): AssociationFile {
  const counts = { auto_match: 0, review_required: 0, no_match: 0 };
  for (const a of associations) {
    if (a.decision === 'AUTO_MATCH') counts.auto_match++;
    else if (a.decision === 'REVIEW_REQUIRED') counts.review_required++;
    else counts.no_match++;
  }
  return {
    chapter_id: CHAPTER,
    algorithm_version: 'assoc-v1',
    generated_at: new Date().toISOString(),
    summary: { total_figures: associations.length, ...counts },
    pipeline_status: counts.review_required > 0 ? 'ASSOCIATION_REVIEW_REQUIRED' : 'ASSOCIATION_AUTO_COMPLETED',
    associations,
  };
}

describe('FigureAssociationStateService', () => {
  function setup() {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    const svc = TestBed.inject(FigureAssociationStateService);
    const http = TestBed.inject(HttpTestingController);
    return { svc, http };
  }

  it('loads saved reviews from the backend on use() and restores them as the source of truth', () => {
    const { svc, http } = setup();
    svc.use(CHAPTER);
    http.expectOne(REVIEWS_URL).flush([
      { chapterId: CHAPTER, figureId: 'figure_001', knowledgeItemId: 'it-1', relation: 'illustrates', status: 'CONFIRMED', reviewedAt: '2026-01-01T00:00:00Z', reviewedBy: null },
    ]);

    expect(svc.statusOf('figure_001')).toBe('CONFIRMED');
    expect(svc.chosenItemIdOf('figure_001', null)).toBe('it-1');
    expect(svc.statusOf('figure_999')).toBe('PENDING');
  });

  it('confirm sends a PUT with CONFIRMED and updates state optimistically', () => {
    const { svc, http } = setup();
    svc.use(CHAPTER);
    http.expectOne(REVIEWS_URL).flush([]);

    svc.confirm('figure_001', 'it-1', 'illustrates');
    expect(svc.statusOf('figure_001')).toBe('CONFIRMED');
    expect(svc.chosenItemIdOf('figure_001', null)).toBe('it-1');

    const req = http.expectOne(`${REVIEWS_URL}/figure_001`);
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ status: 'CONFIRMED', knowledgeItemId: 'it-1', relation: 'illustrates' });
    req.flush({});
  });

  it('reassign sends a PUT with REASSIGNED', () => {
    const { svc, http } = setup();
    svc.use(CHAPTER);
    http.expectOne(REVIEWS_URL).flush([]);

    svc.reassign('figure_001', 'it-2');
    const req = http.expectOne(`${REVIEWS_URL}/figure_001`);
    expect(req.request.body.status).toBe('REASSIGNED');
    expect(req.request.body.knowledgeItemId).toBe('it-2');
    req.flush({});
  });

  it('reject sends a PUT with REJECTED and a null item', () => {
    const { svc, http } = setup();
    svc.use(CHAPTER);
    http.expectOne(REVIEWS_URL).flush([]);

    svc.reject('figure_001');
    const req = http.expectOne(`${REVIEWS_URL}/figure_001`);
    expect(req.request.body).toEqual({ status: 'REJECTED', knowledgeItemId: null, relation: null });
    req.flush({});

    expect(svc.statusOf('figure_001')).toBe('REJECTED');
    expect(svc.chosenItemIdOf('figure_001', 'fallback')).toBeNull();
  });

  it('clear sends a DELETE for one figure', () => {
    const { svc, http } = setup();
    svc.use(CHAPTER);
    http.expectOne(REVIEWS_URL).flush([
      { chapterId: CHAPTER, figureId: 'figure_001', knowledgeItemId: 'it-1', relation: null, status: 'CONFIRMED', reviewedAt: '', reviewedBy: null },
    ]);

    svc.clear('figure_001');
    expect(svc.statusOf('figure_001')).toBe('PENDING');
    const req = http.expectOne(`${REVIEWS_URL}/figure_001`);
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  it('clearAll sends a DELETE for the whole chapter', () => {
    const { svc, http } = setup();
    svc.use(CHAPTER);
    http.expectOne(REVIEWS_URL).flush([
      { chapterId: CHAPTER, figureId: 'figure_001', knowledgeItemId: 'it-1', relation: null, status: 'CONFIRMED', reviewedAt: '', reviewedBy: null },
    ]);

    svc.clearAll();
    expect(svc.statusOf('figure_001')).toBe('PENDING');
    const req = http.expectOne(REVIEWS_URL);
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });
});

describe('FigureAssociation page', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
  });

  async function setup(associations: FigureAssociationRaw[], items: KnowledgeItem[], savedReviews: unknown[] = []) {
    const fixture = TestBed.createComponent(FigureAssociation);
    const http = TestBed.inject(HttpTestingController);
    http.expectOne(REVIEWS_URL).flush(savedReviews);
    http.expectOne('/knowledge/chapter_01_continuite_limites.json').flush(knowledgeBase(items));
    http.expectOne(`/associations/${CHAPTER}/figure_knowledge.json`).flush(associationFile(associations));
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const stat = (label: string) =>
      [...el.querySelectorAll('.stat')].find((s) => s.textContent!.includes(label))!.querySelector('.stat-value')!.textContent!.trim();
    const click = async (text: string) => {
      [...el.querySelectorAll('button')].find((b) => b.textContent!.includes(text))!.click();
      await fixture.whenStable();
      // flush the background PUT/DELETE fired by the click, if any
      http.match(() => true).forEach((r) => r.flush({}));
    };
    const selectedId = () => el.querySelector('.panel-title code')!.textContent;
    return { fixture, el, http, stat, click, selectedId };
  }

  it('loads figures from the generated association file and resolves the figure image', async () => {
    const { el } = await setup([figureAssociation('figure_001'), figureAssociation('figure_002', { source_page: 19 })], [item('it-1'), item('it-2')]);

    expect(el.querySelectorAll('.thumb-card').length).toBe(2);
    const img = el.querySelector('.thumb-card img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('/final_figures/figure_001.png');
  });

  it('restores a previously saved decision from the backend on load', async () => {
    const { el } = await setup(
      [figureAssociation('figure_001')],
      [item('it-1'), item('it-2')],
      [{ chapterId: CHAPTER, figureId: 'figure_001', knowledgeItemId: 'it-1', relation: 'illustrates', status: 'CONFIRMED', reviewedAt: '2026-01-01T00:00:00Z', reviewedBy: null }],
    );
    const badge = el.querySelector('.panel-tools .badge');
    expect(badge?.textContent).toContain('Confirmed');
  });

  it('shows the algorithm chosen item as the suggestion', async () => {
    const { el } = await setup([figureAssociation('figure_001')], [item('it-1', { title: 'IVT theorem' }), item('it-2')]);
    const chosen = el.querySelector('.item-card.chosen');
    expect(chosen?.textContent).toContain('IVT theorem');
  });

  it('Validate PUTs a CONFIRMED review and advances to the next pending figure', async () => {
    const { stat, click, selectedId } = await setup(
      [figureAssociation('figure_001'), figureAssociation('figure_002', { source_page: 19 })],
      [item('it-1'), item('it-2')],
    );
    expect(selectedId()).toBe('figure_001');

    await click('Validate');
    expect(stat('Confirmed')).toBe('1');
    expect(stat('Pending')).toBe('1');
    expect(selectedId()).toBe('figure_002');
  });

  it('Reject PUTs a REJECTED review', async () => {
    const { stat, click } = await setup([figureAssociation('figure_001')], [item('it-1'), item('it-2')]);
    await click('Reject');
    expect(stat('Rejected')).toBe('1');
  });

  it('Choose this instead reassigns to a different candidate', async () => {
    const { el, click, stat } = await setup([figureAssociation('figure_001')], [item('it-1'), item('it-2', { title: 'Other item' })]);
    await click('Choose this instead');
    const chosen = el.querySelector('.item-card.chosen');
    expect(chosen?.textContent).toContain('Other item');

    await click('Validate');
    expect(stat('Reassigned')).toBe('0'); // confirming after reassigning counts as Confirmed, not Reassigned
    expect(stat('Confirmed')).toBe('1');
  });

  it('a figure with no candidates cannot be validated, only rejected', async () => {
    const { el } = await setup([figureAssociation('figure_001', { candidates: [], chosen_item_id: null, decision: 'NO_MATCH' })], []);
    const validateBtn = [...el.querySelectorAll('button')].find((b) => b.textContent!.includes('Validate')) as HTMLButtonElement;
    expect(validateBtn.disabled).toBe(true);
  });
});
