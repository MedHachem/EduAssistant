import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { KnowledgeBase } from './knowledge.model';

/**
 * Loads the generated Knowledge Base as a static asset.
 * scripts/sync-knowledge.mjs copies data/output/knowledge/*.json → public/knowledge/ (one-way, never written back).
 */
@Injectable({ providedIn: 'root' })
export class KnowledgeService {
  private readonly http = inject(HttpClient);

  load(file = 'chapter_01_continuite_limites.json'): Observable<KnowledgeBase> {
    return this.http.get<KnowledgeBase>(`/knowledge/${file}`);
  }
}

/** Page images rendered by the pipeline, copied the same way: data/output/page_images/ → /page-images/. */
export function pageImageUrl(pdfPage: number): string {
  return `/page-images/page_${String(pdfPage).padStart(3, '0')}.png`;
}
