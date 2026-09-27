import { Injectable, inject } from '@angular/core';
import { Observable, defer, from, map, of, throwError } from 'rxjs';
import { documentType, optionLabel } from './document-types';
import { DocumentStatus, LibraryDocument, UploadDocumentRequest, UploadEvent } from './document.model';
import { BlobStore } from './blob-store';
import { DocumentsApi } from './documents-api';

const STORAGE_KEY = 'edu.documents.v1';

/**
 * Best-effort page count read from the PDF bytes (the backend will do this properly).
 * Uses the largest "/Count n" of the page tree, falling back to counting "/Type /Page" objects.
 */
export function countPdfPages(bytes: Uint8Array): number | null {
  const text = new TextDecoder('latin1').decode(bytes);
  const counts = [...text.matchAll(/\/Type\s*\/Pages\b[^>]*?\/Count\s+(\d+)|\/Count\s+(\d+)[^>]*?\/Type\s*\/Pages\b/g)].map((m) =>
    Number(m[1] ?? m[2]),
  );
  if (counts.length) return Math.max(...counts);
  const pages = text.match(/\/Type\s*\/Page(?![s\w])/g)?.length ?? 0;
  return pages || null;
}

/**
 * In-browser document library used until the backend exists: metadata in localStorage,
 * PDFs in IndexedDB (BlobStore). Same behaviour as the HTTP API from the UI's point of view.
 */
@Injectable()
export class LocalDocumentsApi extends DocumentsApi {
  private readonly blobs = inject(BlobStore);
  private readonly urls = new Map<string, string>();

  list(): Observable<LibraryDocument[]> {
    return of(this.read());
  }

  upload(req: UploadDocumentRequest): Observable<UploadEvent> {
    return new Observable<UploadEvent>((sub) => {
      let cancelled = false;
      const run = async () => {
        const type = documentType(req.type);
        if (!type) throw new Error(`Unknown document type "${req.type}"`);

        // Simulated upload progress, so the UI behaves like a real network upload.
        for (const percent of [10, 35, 60, 85]) {
          if (cancelled) return;
          sub.next({ kind: 'progress', percent });
          await new Promise((r) => setTimeout(r, 120));
        }

        const id = crypto.randomUUID();
        const bytes = new Uint8Array(await req.file.arrayBuffer());
        await this.blobs.put(`${id}/file`, new Blob([bytes], { type: 'application/pdf' }));
        if (req.correction) {
          await this.blobs.put(`${id}/correction`, new Blob([await req.correction.arrayBuffer()], { type: 'application/pdf' }));
        }

        const m = req.metadata;
        const now = new Date().toISOString();
        const doc: LibraryDocument = {
          id,
          type: req.type,
          title: type.title(m, (key) => optionLabel(type, key, m[key])),
          subject: String(m['subject'] ?? ''),
          level: m['level'] != null ? String(m['level']) : null,
          section: m['section'] != null ? String(m['section']) : null,
          metadata: m,
          fileName: req.file.name,
          fileSize: req.file.size,
          pageCount: countPdfPages(bytes),
          hasCorrection: !!req.correction,
          status: req.status,
          uploadedAt: now,
          updatedAt: now,
        };
        this.write([doc, ...this.read()]);
        sub.next({ kind: 'progress', percent: 100 });
        sub.next({ kind: 'done', document: doc });
        sub.complete();
      };
      run().catch((e) => sub.error(e));
      return () => (cancelled = true);
    });
  }

  setStatus(id: string, status: DocumentStatus): Observable<LibraryDocument> {
    const docs = this.read();
    const doc = docs.find((d) => d.id === id);
    if (!doc) return throwError(() => new Error('Document not found'));
    const updated = { ...doc, status, updatedAt: new Date().toISOString() };
    this.write(docs.map((d) => (d.id === id ? updated : d)));
    return of(updated);
  }

  delete(id: string): Observable<void> {
    return defer(async () => {
      this.write(this.read().filter((d) => d.id !== id));
      await this.blobs.delete(`${id}/file`);
      await this.blobs.delete(`${id}/correction`);
      for (const key of [`${id}/file`, `${id}/correction`]) {
        const url = this.urls.get(key);
        if (url) URL.revokeObjectURL(url);
        this.urls.delete(key);
      }
    });
  }

  listCourses(): Observable<LibraryDocument[]> {
    return this.list().pipe(map((docs) => docs.filter((d) => d.type === 'book' && d.status === 'PUBLISHED')));
  }

  getCourse(id: string): Observable<LibraryDocument> {
    const doc = this.read().find((d) => d.id === id && d.type === 'book' && d.status === 'PUBLISHED');
    return doc ? of(doc) : throwError(() => new Error('Course not found'));
  }

  fileUrl(id: string, which: 'file' | 'correction' = 'file'): Observable<string> {
    const key = `${id}/${which}`;
    const cached = this.urls.get(key);
    if (cached) return of(cached);
    return from(this.blobs.get(key)).pipe(
      map((blob) => {
        if (!blob) throw new Error('File not found');
        const url = URL.createObjectURL(blob);
        this.urls.set(key, url);
        return url;
      }),
    );
  }

  private read(): LibraryDocument[] {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]') as LibraryDocument[];
    } catch {
      return [];
    }
  }

  private write(docs: LibraryDocument[]): void {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(docs));
  }
}
