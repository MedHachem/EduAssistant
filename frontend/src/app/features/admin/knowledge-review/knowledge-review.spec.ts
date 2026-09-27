import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { KnowledgeBase, KnowledgeItem, Question } from './knowledge.model';
import { formatPages } from './knowledge-format';
import { KnowledgeReview } from './knowledge-review';
import { tokenize, renderToHtml } from '../../../shared/math-text/math-text';
import { QuestionTree } from './question-tree/question-tree';
import { findInQueue } from './review-queue';
import { ReviewStateService } from './review-state.service';

function item(id: string, patch: Partial<KnowledgeItem> = {}): KnowledgeItem {
  return {
    id: `ch01-${id}`,
    type: 'activity',
    document_id: 'doc',
    chapter_id: 'ch01',
    section_id: 'sec-1',
    subsection_id: null,
    title: null,
    source: {
      document_id: 'doc',
      pdf_pages: [6],
      reconstructed_sources: [],
      bloc_type: 'activite',
      bloc_numero: '1',
      continues_from_previous_page: false,
      continues_on_next_page: false,
    },
    original_content: `Contenu ${id} $f(x)$`,
    proof: null,
    concepts: [],
    links: null,
    exercise_details: null,
    extracted_from: null,
    uncertainty: { has_uncertain_markers: false, has_gap_markers: false, uncertain_spans: [] },
    validation_status: 'REVIEW_REQUIRED',
    validation_history: [],
    created_at: '',
    schema_version: '1.0',
    ...patch,
  };
}

function kb(items: KnowledgeItem[]): KnowledgeBase {
  return {
    document: { id: 'doc', title: 'Doc', subject: '', level: '', country: '', source_pdf: '', total_pages: 1 },
    chapter: { id: 'ch01', document_id: 'doc', number: 1, title: 'Continuité et limites', pdf_page_start: 5, pdf_page_end: 27 },
    sections: [{ id: 'sec-1', chapter_id: 'ch01', label: 'I', title: 'Rappels', pdf_page_start: 6, pdf_page_end: 8 }],
    subsections: [],
    concepts: [],
    items,
  };
}

describe('tokenize / renderToHtml', () => {
  it('splits text, inline math, display math and figure tags', () => {
    const segs = tokenize('a $x$ b $$y$$ <figure id="f1" status="described">desc $z$</figure>');
    expect(segs.map((s) => s.kind)).toEqual(['text', 'inline', 'text', 'display', 'text', 'figure']);
    expect(segs[5]).toMatchObject({ id: 'f1', status: 'described', value: 'desc $z$' });
  });

  it('escapes plain text and renders math with KaTeX', () => {
    const html = renderToHtml('<b>x</b> $\\dfrac{1}{2}$');
    expect(html).toContain('&lt;b&gt;x&lt;/b&gt;');
    expect(html).toContain('class="katex"');
  });

  it('does not throw on invalid LaTeX', () => {
    expect(() => renderToHtml('$\\frac{$')).not.toThrow();
  });
});

describe('helpers', () => {
  it('formats page ranges', () => {
    expect(formatPages([20, 21, 22])).toBe('20–22');
    expect(formatPages([9])).toBe('9');
    expect(formatPages([9, 11])).toBe('9, 11');
  });

  it('finds the next matching element, optionally wrapping', () => {
    const list = [1, 2, 3, 4];
    const even = (n: number) => n % 2 === 0;
    expect(findInQueue(list, 1, 1, even)).toBe(3);
    expect(findInQueue(list, 3, 1, even)).toBe(-1);
    expect(findInQueue(list, 3, 1, even, true)).toBe(1);
    expect(findInQueue(list, 3, -1, even)).toBe(1);
    expect(findInQueue(list, -1, 1, even)).toBe(1);
  });
});

describe('ReviewStateService', () => {
  beforeEach(() => localStorage.clear());

  it('overlays decisions on the generated status and persists them per chapter', () => {
    const svc = TestBed.inject(ReviewStateService);
    svc.use('ch01');
    expect(svc.statusOf('a', 'REVIEW_REQUIRED')).toBe('REVIEW_REQUIRED');
    svc.set('a', 'VALIDATED');
    expect(svc.statusOf('a', 'REVIEW_REQUIRED')).toBe('VALIDATED');
    expect(JSON.parse(localStorage.getItem('edu.knowledge-review.v1.ch01')!).a.status).toBe('VALIDATED');
    svc.clear('a');
    expect(svc.statusOf('a', 'REVIEW_REQUIRED')).toBe('REVIEW_REQUIRED');
  });
});

describe('QuestionTree', () => {
  it('renders sub-questions nested under their parent instead of flattening them', async () => {
    const questions: Question[] = [
      {
        label: '1',
        text: 'Soit f.',
        sub_questions: [
          { label: 'a', text: 'Déterminer', sub_questions: [] },
          { label: 'b', text: 'Montrer', sub_questions: [] },
          { label: 'c', text: 'En déduire', sub_questions: [] },
        ],
      },
    ];
    const fixture = TestBed.createComponent(QuestionTree);
    fixture.componentRef.setInput('questions', questions);
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const top = el.querySelectorAll(':scope > ol > li');
    expect(top.length).toBe(1);
    const nested = top[0].querySelectorAll(':scope > app-question-tree > ol > li');
    expect([...nested].map((li) => li.querySelector('.q-label')!.textContent)).toEqual(['a.', 'b.', 'c.']);
  });
});

describe('KnowledgeReview page', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
  });

  async function setup(items: KnowledgeItem[]) {
    const fixture = TestBed.createComponent(KnowledgeReview);
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/knowledge/chapter_01_continuite_limites.json').flush(kb(items));
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const stat = (label: string) =>
      [...el.querySelectorAll('.stat')].find((s) => s.textContent!.includes(label))!.querySelector('.stat-value')!.textContent!.trim();
    const click = async (text: string) => {
      [...el.querySelectorAll('button')].find((b) => b.textContent!.includes(text))!.click();
      await fixture.whenStable();
    };
    const selectedId = () => el.querySelector('.panel-title code')!.textContent;
    return { fixture, el, stat, click, selectedId };
  }

  it('computes the dashboard and advances to the next item after validating / rejecting', async () => {
    const { el, stat, click, selectedId } = await setup([item('act-001'), item('act-002'), item('thm-001', { type: 'theorem' })]);

    expect(stat('Total')).toBe('3');
    expect(stat('Remaining')).toBe('3');
    expect(selectedId()).toBe('ch01-act-001');

    await click('Validate');
    expect(stat('Validated')).toBe('1');
    expect(stat('Remaining')).toBe('2');
    expect(el.querySelector('.progress-label')!.textContent).toContain('1 / 3 reviewed');
    expect(selectedId()).toBe('ch01-act-002');

    await click('Reject');
    expect(stat('Rejected')).toBe('1');
    expect(selectedId()).toBe('ch01-thm-001');
  });

  it('shows "No correction present in source." and never invents one', async () => {
    const exo = item('exo-001', {
      type: 'exercise',
      exercise_details: {
        statement: 'Soit f.',
        questions: [],
        correction: { present_in_source: false, content: null },
        qcm_choices: null,
      },
    });
    const { el } = await setup([exo]);
    expect(el.textContent).toContain('No correction present in source.');
    expect(el.textContent).not.toContain('Proof');
  });

  it('shows unresolved figure references', async () => {
    const withFig = item('act-009', {
      links: {
        definitions: [], theorems: [], properties: [], formulas: [], methods: [], exercises: [],
        figures: [{ pdf_page: 9, reconstructed_figure_id: 'fig-act1', candidate_id: null, figure_status_in_source: 'described', match_status: 'unresolved' }],
      },
    });
    const { el } = await setup([withFig]);
    expect(el.textContent).toContain('Figure reference: unresolved');
  });
});
