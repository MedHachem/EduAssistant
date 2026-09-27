import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { firstValueFrom, lastValueFrom, of, toArray } from 'rxjs';
import { BlobStore, MemoryBlobStore } from '../../../core/documents/blob-store';
import { DocumentsApi } from '../../../core/documents/documents-api';
import { DocumentsStore } from '../../../core/documents/documents.store';
import { HttpDocumentsApi } from '../../../core/documents/http-documents-api';
import { LocalDocumentsApi, countPdfPages } from '../../../core/documents/local-documents-api';
import { CoursesPage } from '../../client/courses/courses-page';
import { UploadPage } from './upload/upload-page';

const pdf = (name = 'manuel.pdf', body = '%PDF-1.4\n<< /Type /Pages /Kids [] /Count 3 >>') =>
  new File([body], name, { type: 'application/pdf' });

function provideLocalLibrary() {
  return [
    { provide: BlobStore, useClass: MemoryBlobStore },
    { provide: DocumentsApi, useClass: LocalDocumentsApi },
  ];
}

describe('countPdfPages', () => {
  it('reads the page tree count, or counts page objects', () => {
    expect(countPdfPages(new TextEncoder().encode('<< /Type /Pages /Count 207 >>'))).toBe(207);
    expect(countPdfPages(new TextEncoder().encode('/Type /Page /Type /Page /Type /Pages'))).toBe(2);
    expect(countPdfPages(new TextEncoder().encode('no pages'))).toBeNull();
  });
});

describe('LocalDocumentsApi', () => {
  let api: DocumentsApi;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: provideLocalLibrary() });
    api = TestBed.inject(DocumentsApi);
    URL.createObjectURL = () => 'blob:test';
    URL.revokeObjectURL = () => {};
  });

  async function upload(type: 'book' | 'exam', status: 'PUBLISHED' | 'DRAFT', metadata: Record<string, string | number>) {
    const events = await lastValueFrom(api.upload({ type, file: pdf(), metadata, status }).pipe(toArray()));
    const done = events.at(-1)!;
    if (done.kind !== 'done') throw new Error('upload did not finish');
    return { events, doc: done.document };
  }

  it('stores the PDF, reports progress and builds the document', async () => {
    const { events, doc } = await upload('book', 'PUBLISHED', { title: 'Maths T1', subject: 'Mathématiques', level: '4eme' });
    expect(events.filter((e) => e.kind === 'progress').length).toBeGreaterThan(1);
    expect(doc).toMatchObject({ type: 'book', title: 'Maths T1', subject: 'Mathématiques', level: '4eme', pageCount: 3, status: 'PUBLISHED' });
    expect(await firstValueFrom(api.fileUrl(doc.id))).toBe('blob:test');
  });

  it('generates exam titles from the metadata', async () => {
    const { doc } = await upload('exam', 'DRAFT', { examType: 'bac', year: 2024, session: 'principale', section: 'Mathématiques', subject: 'Mathématiques' });
    expect(doc.title).toBe('Baccalauréat 2024 · Session principale · Mathématiques · Mathématiques');
  });

  it('only exposes published books as courses', async () => {
    const { doc: published } = await upload('book', 'PUBLISHED', { title: 'A', subject: 'Physique' });
    const { doc: draft } = await upload('book', 'DRAFT', { title: 'B', subject: 'Physique' });
    await upload('exam', 'PUBLISHED', { examType: 'bac', year: 2024, session: 'principale', section: 'Lettres', subject: 'Arabe' });

    expect((await firstValueFrom(api.listCourses())).map((c) => c.id)).toEqual([published.id]);

    await firstValueFrom(api.setStatus(draft.id, 'PUBLISHED'));
    expect((await firstValueFrom(api.listCourses())).length).toBe(2);

    await lastValueFrom(api.delete(published.id));
    await expect(firstValueFrom(api.getCourse(published.id))).rejects.toThrow();
    await expect(firstValueFrom(api.fileUrl(published.id))).rejects.toThrow();
  });
});

describe('HttpDocumentsApi', () => {
  it('uploads multipart (file, correction, metadata) and maps progress', async () => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting(), HttpDocumentsApi] });
    const api = TestBed.inject(HttpDocumentsApi);
    const http = TestBed.inject(HttpTestingController);

    const events: string[] = [];
    api
      .upload({ type: 'exam', file: pdf('bac.pdf'), correction: pdf('corr.pdf'), metadata: { year: 2024 }, status: 'DRAFT' })
      .subscribe((e) => events.push(e.kind));

    const req = http.expectOne('/api/admin/documents');
    const body = req.request.body as FormData;
    expect((body.get('file') as File).name).toBe('bac.pdf');
    expect((body.get('correction') as File).name).toBe('corr.pdf');
    expect(JSON.parse(await (body.get('metadata') as Blob).text())).toEqual({ type: 'exam', status: 'DRAFT', year: 2024 });
    req.flush({ id: '1' });
    expect(events).toEqual(['done']);

    api.fileUrl('1').subscribe();
    http.expectOne('/api/documents/1/file-url?which=file').flush({ url: 'https://blob/x?sas', expiresAt: '' });
    api.listCourses().subscribe();
    http.expectOne('/api/courses').flush([]);
  });
});

describe('UploadPage', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        ...provideLocalLibrary(),
        { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ type: 'book' })) } },
      ],
    });
  });

  it('requires a file and a title, uploads, and lists the new book', async () => {
    const fixture = TestBed.createComponent(UploadPage);
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const uploadBtn = () => el.querySelector<HTMLButtonElement>('.btn-upload')!;

    expect(el.querySelector('h1')!.textContent).toContain('Official Books');
    expect(uploadBtn().disabled).toBe(true);
    expect(el.querySelector('.missing')!.textContent).toContain('PDF file');
    expect(el.querySelector('.missing')!.textContent).toContain('Book title');

    const title = el.querySelector<HTMLInputElement>('input[type=text]')!;
    title.value = 'Mathématiques 4ème — Tome 1';
    title.dispatchEvent(new Event('input'));
    (fixture.componentInstance as unknown as { file: { set(f: File): void } }).file.set(pdf());
    await fixture.whenStable();
    expect(el.querySelector('.missing')).toBeNull();

    uploadBtn().click();
    await vi.waitFor(async () => {
      await fixture.whenStable();
      expect(el.querySelector('.alert.success')?.textContent).toContain('available to students as a course');
    });

    const docs = TestBed.inject(DocumentsStore).documents();
    expect(docs).toHaveLength(1);
    expect(docs[0]).toMatchObject({ title: 'Mathématiques 4ème — Tome 1', status: 'PUBLISHED' });
    expect(el.querySelector('app-document-table')!.textContent).toContain('Mathématiques 4ème — Tome 1');
    // Form is reset for the next upload.
    expect(title.value).toBe('');
  });
});

describe('CoursesPage', () => {
  it('shows published books as course cards', async () => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideRouter([]), ...provideLocalLibrary()] });
    const api = TestBed.inject(DocumentsApi);
    for (const [title, status] of [['Physique T1', 'PUBLISHED'], ['Brouillon', 'DRAFT']] as const) {
      await lastValueFrom(api.upload({ type: 'book', file: pdf(), metadata: { title, subject: 'Physique', level: '4eme' }, status }));
    }

    const fixture = TestBed.createComponent(CoursesPage);
    await fixture.whenStable();
    const cards = [...(fixture.nativeElement as HTMLElement).querySelectorAll('.course')];
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain('Physique T1');
    expect(cards[0].textContent).toContain('4ème année secondaire');
  });
});
