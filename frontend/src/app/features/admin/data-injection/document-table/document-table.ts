import { DatePipe } from '@angular/common';
import { Component, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Observable } from 'rxjs';
import { documentType, levelLabel } from '../../../../core/documents/document-types';
import { LibraryDocument } from '../../../../core/documents/document.model';
import { DocumentsStore } from '../../../../core/documents/documents.store';
import { formatSize } from '../../../../shared/pdf-dropzone/pdf-dropzone';

@Component({
  selector: 'app-document-table',
  imports: [DatePipe, RouterLink],
  templateUrl: './document-table.html',
  styleUrl: './document-table.scss',
})
export class DocumentTable {
  private readonly store = inject(DocumentsStore);

  readonly documents = input.required<LibraryDocument[]>();
  readonly showType = input(true);
  readonly emptyText = input('No documents yet.');

  /** Id of the row with an action in progress. */
  protected readonly busy = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);

  protected readonly size = formatSize;
  protected readonly typeOf = documentType;
  protected readonly level = levelLabel;

  protected open(doc: LibraryDocument, which: 'file' | 'correction' = 'file'): void {
    // Open synchronously (inside the click) so popup blockers allow it, then point it to the file URL.
    const win = window.open('', '_blank');
    this.store.fileUrl(doc.id, which).subscribe({
      next: (url) => {
        if (win) win.location.href = url;
        else window.location.href = url;
      },
      error: () => {
        win?.close();
        this.error.set(`Could not open “${doc.fileName}”.`);
      },
    });
  }

  protected toggleStatus(doc: LibraryDocument): void {
    this.run(doc, () => this.store.setStatus(doc.id, doc.status === 'PUBLISHED' ? 'DRAFT' : 'PUBLISHED'));
  }

  protected remove(doc: LibraryDocument): void {
    if (!confirm(`Delete “${doc.title}”? The PDF will be removed from storage.`)) return;
    this.run(doc, () => this.store.delete(doc.id));
  }

  private run(doc: LibraryDocument, action: () => Observable<unknown>): void {
    this.busy.set(doc.id);
    this.error.set(null);
    action().subscribe({
      complete: () => this.busy.set(null),
      error: () => {
        this.busy.set(null);
        this.error.set(`Action failed for “${doc.title}”.`);
      },
    });
  }
}
