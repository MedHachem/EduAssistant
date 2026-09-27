import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { FigureCandidateRaw, FigureReviewReport } from './figure-review.model';
import { FigureReview } from './figure-review';
import { FigureReviewStateService } from './figure-review-state.service';

function candidate(id: string, patch: Partial<FigureCandidateRaw> = {}): FigureCandidateRaw {
  return {
    candidate_id: id,
    pdf_page: 13,
    type: 'candidate',
    classification_hint: 'figure',
    hint_meaning: 'Likely a graphical figure.',
    hint_explanation: 'one dominant connected graphical shape, no text-line banding',
    confidence: 0.8,
    refinement_uncertain: false,
    likely_text_box: false,
    seed_bbox: [1552, 604, 1888, 956],
    refined_bbox: [1451, 427, 1989, 965],
    bbox: [1451, 427, 1989, 965],
    image_path: `figure_candidates_refined/page_013/${id}.png`,
    needs_review: true,
    ...patch,
  };
}

function report(candidates: FigureCandidateRaw[]): FigureReviewReport {
  return {
    note: 'test',
    total_candidates: candidates.length,
    counts_by_hint: { figure: 0, text_only: 0, ambiguous: 0 },
    candidates,
  };
}

describe('FigureReviewStateService', () => {
  beforeEach(() => localStorage.clear());

  it('persists decisions under a SEPARATE key from knowledge-item review state', () => {
    const svc = TestBed.inject(FigureReviewStateService);
    svc.use('math-4eme-tome1-ch01');
    expect(svc.statusOf('page_013_candidate_02')).toBe('UNREVIEWED');

    svc.set('page_013_candidate_02', 'VALIDATED');
    expect(svc.statusOf('page_013_candidate_02')).toBe('VALIDATED');

    const raw = localStorage.getItem('edu.figure-review.v1.math-4eme-tome1-ch01');
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!)['page_013_candidate_02'].status).toBe('VALIDATED');
    // Must never touch the knowledge-item review key.
    expect(localStorage.getItem('edu.knowledge-review.v1.math-4eme-tome1-ch01')).toBeNull();

    svc.clear('page_013_candidate_02');
    expect(svc.statusOf('page_013_candidate_02')).toBe('UNREVIEWED');
  });
});

describe('FigureReview page', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { data: of({}) } },
      ],
    });
  });

  async function setup(candidates: FigureCandidateRaw[]) {
    const fixture = TestBed.createComponent(FigureReview);
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/figures/visual_elements_review.json').flush(report(candidates));
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const stat = (label: string) =>
      [...el.querySelectorAll('.stat')].find((s) => s.textContent!.includes(label))!.querySelector('.stat-value')!.textContent!.trim();
    const click = async (text: string) => {
      [...el.querySelectorAll('button')].find((b) => b.textContent!.includes(text))!.click();
      await fixture.whenStable();
    };
    const selectedId = () => el.querySelector('.panel-title code')!.textContent;
    return { fixture, el, http, stat, click, selectedId };
  }

  it('loads candidates from the generated report and resolves the crop image path', async () => {
    const { el } = await setup([candidate('page_013_candidate_02'), candidate('page_019_candidate_04', { pdf_page: 19 })]);

    expect(el.querySelectorAll('.thumb-card').length).toBe(2);
    const img = el.querySelector('.thumb-card img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('/figure_candidates_refined/page_013/page_013_candidate_02.png');
  });

  it('computes dashboard stats', async () => {
    const { stat } = await setup([candidate('a'), candidate('b'), candidate('c')]);
    expect(stat('Total')).toBe('3');
    expect(stat('Unreviewed')).toBe('3');
  });

  it('Validate Figure changes state and advances to the next unreviewed candidate', async () => {
    const { stat, click, selectedId } = await setup([candidate('a'), candidate('b')]);
    expect(selectedId()).toBe('a');

    await click('Validate Figure');
    expect(stat('Validated')).toBe('1');
    expect(stat('Unreviewed')).toBe('1');
    expect(selectedId()).toBe('b');
  });

  it('Reject / Not a Figure changes state', async () => {
    const { stat, click } = await setup([candidate('a', { classification_hint: 'text_only', likely_text_box: true, confidence: 0 })]);
    await click('Reject');
    expect(stat('Rejected')).toBe('1');
  });

  it('Needs Correction changes state', async () => {
    const { stat, click } = await setup([candidate('a')]);
    await click('Needs Correction');
    expect(stat('Needs correction')).toBe('1');
  });

  it('filters by status', async () => {
    const { fixture, el, click } = await setup([candidate('a'), candidate('b')]);
    await click('Validate Figure');

    const select = el.querySelector('select[aria-label="Status filter"]') as HTMLSelectElement;
    select.value = 'VALIDATED';
    select.dispatchEvent(new Event('change'));
    await fixture.whenStable();

    expect(el.querySelectorAll('.thumb-card').length).toBe(1);
  });

  it('state survives a fresh component instance (page refresh)', async () => {
    const { click } = await setup([candidate('page_013_candidate_02')]);
    await click('Validate Figure');

    const svc = TestBed.inject(FigureReviewStateService);
    svc.use('math-4eme-tome1-ch01');
    expect(svc.statusOf('page_013_candidate_02')).toBe('VALIDATED');
  });

  it('never writes to the knowledge-item review localStorage key', async () => {
    const { click } = await setup([candidate('a')]);
    await click('Validate Figure');
    expect(localStorage.getItem('edu.knowledge-review.v1.math-4eme-tome1-ch01')).toBeNull();
  });
});

describe('FigureReview page — round 3 (route data)', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: ActivatedRoute,
          useValue: {
            data: of({
              round: {
                reviewFile: 'visual_elements_review_v3.json',
                chapterIdSuffix: '-v3',
                roundLabel: 'Round 3 — completeness-refined (V3)',
              },
            }),
          },
        },
      ],
    });
  });

  it('loads the round-specific report file and keeps a separate review-state key', async () => {
    const fixture = TestBed.createComponent(FigureReview);
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/figures/visual_elements_review_v3.json').flush({
      note: 'round 3',
      total_candidates: 1,
      counts_by_hint: { figure: 1, text_only: 0, ambiguous: 0 },
      candidates: [candidate('page_025_candidate_01')],
    });
    await fixture.whenStable();

    const el = fixture.nativeElement as HTMLElement;
    [...el.querySelectorAll('button')].find((b) => b.textContent!.includes('Validate Figure'))!.click();
    await fixture.whenStable();

    expect(localStorage.getItem('edu.figure-review.v1.math-4eme-tome1-ch01-v3')).toBeTruthy();
    expect(localStorage.getItem('edu.figure-review.v1.math-4eme-tome1-ch01')).toBeNull();
  });
});
