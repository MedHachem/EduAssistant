import { Component, ElementRef, input, model, signal, viewChild } from '@angular/core';

const MAX_SIZE_MB = 200;

export function formatSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Returns an error message, or null when the file is an acceptable PDF. */
export function validatePdf(file: File, maxSizeMb = MAX_SIZE_MB): string | null {
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) return 'Only PDF files are accepted.';
  if (file.size > maxSizeMb * 1024 * 1024) return `File is too large (max ${maxSizeMb} MB).`;
  return null;
}

/** Click-or-drop PDF picker. Two-way binds the selected file: [(file)]. */
@Component({
  selector: 'app-pdf-dropzone',
  template: `
    <div
      class="dropzone"
      [class.dragging]="dragging()"
      [class.has-file]="file()"
      [class.compact]="compact()"
      role="button"
      tabindex="0"
      [attr.aria-label]="label()"
      (click)="!file() && input.click()"
      (keydown.enter)="input.click()"
      (keydown.space)="$event.preventDefault(); input.click()"
      (dragover)="onDragOver($event)"
      (dragleave)="dragging.set(false)"
      (drop)="onDrop($event)"
    >
      <input #input type="file" accept="application/pdf,.pdf" (change)="onPicked($event)" hidden />
      @if (file(); as f) {
        <svg class="pdf-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zm-1 7V3.5L18.5 9z" />
        </svg>
        <div class="file-info">
          <span class="file-name">{{ f.name }}</span>
          <span class="file-meta">{{ size(f.size) }}</span>
        </div>
        <button type="button" class="btn-link" (click)="$event.stopPropagation(); input.click()">Replace</button>
        <button type="button" class="btn-link remove" (click)="$event.stopPropagation(); clear()">Remove</button>
      } @else {
        <svg class="upload-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M11 16V7.8l-3.6 3.6L6 10l6-6 6 6-1.4 1.4L13 7.8V16zm-7 4v-4h2v2h12v-2h2v4z" />
        </svg>
        <span class="title">{{ label() }}</span>
        <span class="file-meta">Drag & drop or <span class="browse">browse</span> · PDF, max 200 MB</span>
      }
    </div>
    @if (error(); as e) {
      <p class="error">{{ e }}</p>
    }
  `,
  styles: `
    :host { display: block; }
    .dropzone {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.3rem;
      padding: 1.75rem 1rem;
      border: 2px dashed var(--border);
      border-radius: var(--radius);
      background: var(--surface);
      cursor: pointer;
      transition: border-color 0.15s, background 0.15s;
      text-align: center;
      &:hover, &:focus-visible, &.dragging { border-color: var(--accent, var(--primary)); background: var(--accent-soft, var(--primary-soft)); outline: none; }
      &.compact { padding: 1rem; }
      &.has-file {
        flex-direction: row;
        text-align: left;
        gap: 0.75rem;
        padding: 0.85rem 1rem;
        border-style: solid;
        cursor: default;
      }
    }
    svg { fill: currentColor; }
    .upload-icon { width: 1.75rem; height: 1.75rem; color: var(--accent, var(--primary)); }
    .pdf-icon { flex: none; width: 2rem; height: 2rem; color: #c53030; }
    .title { font-weight: 600; }
    .browse { color: var(--accent, var(--primary)); text-decoration: underline; }
    .file-info { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .file-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .file-meta { font-size: 0.8rem; color: var(--muted); }
    .btn-link { font-size: 0.8rem; color: var(--muted); }
    .remove:hover { color: #a12626; }
    .error { margin: 0.4rem 0 0; font-size: 0.8rem; color: #a12626; }
  `,
})
export class PdfDropzone {
  readonly file = model<File | null>(null);
  readonly label = input('Upload the PDF');
  readonly compact = input(false);

  protected readonly dragging = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly size = formatSize;

  private readonly fileInput = viewChild.required<ElementRef<HTMLInputElement>>('input');

  protected onPicked(e: Event): void {
    const el = e.target as HTMLInputElement;
    this.accept(el.files?.[0] ?? null);
    el.value = '';
  }

  protected onDragOver(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(true);
  }

  protected onDrop(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(false);
    this.accept(e.dataTransfer?.files?.[0] ?? null);
  }

  protected clear(): void {
    this.error.set(null);
    this.file.set(null);
    this.fileInput().nativeElement.value = '';
  }

  private accept(file: File | null): void {
    if (!file) return;
    const error = validatePdf(file);
    this.error.set(error);
    if (!error) this.file.set(file);
  }
}
