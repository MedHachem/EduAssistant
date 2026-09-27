import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { DOCUMENT_TYPES } from '../../../core/documents/document-types';
import { DocumentStatus, DocumentType } from '../../../core/documents/document.model';
import { DocumentsStore } from '../../../core/documents/documents.store';
import { DocumentTable } from './document-table/document-table';

/** Data Injection › Upload: the three official document types + the whole library. */
@Component({
  selector: 'app-data-injection',
  imports: [RouterLink, DocumentTable],
  templateUrl: './data-injection.html',
  styleUrl: './data-injection.scss',
})
export class DataInjection {
  protected readonly store = inject(DocumentsStore);

  protected readonly search = signal('');
  protected readonly typeFilter = signal<'ALL' | DocumentType>('ALL');
  protected readonly statusFilter = signal<'ALL' | DocumentStatus>('ALL');
  protected readonly types = DOCUMENT_TYPES;

  protected readonly cards = computed(() =>
    DOCUMENT_TYPES.map((type) => {
      const docs = this.store.byType().get(type.key) ?? [];
      return { type, total: docs.length, published: docs.filter((d) => d.status === 'PUBLISHED').length };
    }),
  );

  protected readonly filtered = computed(() => {
    const q = this.search().trim().toLowerCase();
    return this.store.documents().filter(
      (d) =>
        (this.typeFilter() === 'ALL' || d.type === this.typeFilter()) &&
        (this.statusFilter() === 'ALL' || d.status === this.statusFilter()) &&
        (!q || `${d.title} ${d.subject} ${d.fileName}`.toLowerCase().includes(q)),
    );
  });

  constructor() {
    this.store.refresh();
  }

  protected setType(value: string): void {
    this.typeFilter.set(value as 'ALL' | DocumentType);
  }

  protected setStatus(value: string): void {
    this.statusFilter.set(value as 'ALL' | DocumentStatus);
  }
}
