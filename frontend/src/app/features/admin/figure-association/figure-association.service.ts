import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { AssociationFile } from './figure-association.model';

/**
 * Loads the generated figure <-> knowledge association file as a static
 * asset. scripts/sync-knowledge.mjs copies
 * data/output/<chapter_id>/associations/figure_knowledge.json →
 * public/associations/<chapter_id>/figure_knowledge.json (one-way,
 * never written back).
 */
@Injectable({ providedIn: 'root' })
export class FigureAssociationService {
  private readonly http = inject(HttpClient);

  load(chapterId: string): Observable<AssociationFile> {
    return this.http.get<AssociationFile>(`/associations/${chapterId}/figure_knowledge.json`);
  }
}

/** candidate_image from the association file (e.g. "figure_012.png") →
 * served URL. Reuses final_figures/ (Phase 5a), synced the same way. */
export function finalFigureImageUrl(image: string): string {
  return `/final_figures/${image}`;
}
