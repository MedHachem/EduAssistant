import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { DocumentStatus, DocumentType, LibraryDocument, UploadDocumentRequest, UploadEvent } from './document.model';
import { DocumentsApi } from './documents-api';

/** Admin-side state of the document library. */
@Injectable({ providedIn: 'root' })
export class DocumentsStore {
  private readonly api = inject(DocumentsApi);

  private readonly _documents = signal<LibraryDocument[]>([]);
  readonly documents = this._documents.asReadonly();
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);

  readonly byType = computed(() => {
    const map = new Map<DocumentType, LibraryDocument[]>();
    for (const d of this._documents()) map.set(d.type, [...(map.get(d.type) ?? []), d]);
    return map;
  });

  refresh(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.list().subscribe({
      next: (docs) => {
        this._documents.set([...docs].sort((a, b) => b.uploadedAt.localeCompare(a.uploadedAt)));
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Could not load the document library.');
        this.loading.set(false);
      },
    });
  }

  upload(req: UploadDocumentRequest): Observable<UploadEvent> {
    return this.api.upload(req).pipe(
      tap((e) => {
        if (e.kind === 'done') this._documents.update((list) => [e.document, ...list]);
      }),
    );
  }

  setStatus(id: string, status: DocumentStatus): Observable<LibraryDocument> {
    return this.api.setStatus(id, status).pipe(tap((doc) => this.replace(doc)));
  }

  delete(id: string): Observable<void> {
    return this.api.delete(id).pipe(tap(() => this._documents.update((list) => list.filter((d) => d.id !== id))));
  }

  fileUrl(id: string, which: 'file' | 'correction' = 'file'): Observable<string> {
    return this.api.fileUrl(id, which);
  }

  private replace(doc: LibraryDocument): void {
    this._documents.update((list) => list.map((d) => (d.id === doc.id ? doc : d)));
  }
}
