import { Component, computed, effect, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, ValidatorFn, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { DocumentTypeConfig, FieldDef, documentType, optionLabel } from '../../../../core/documents/document-types';
import { DocumentStatus, LibraryDocument, MetadataValue } from '../../../../core/documents/document.model';
import { DocumentsStore } from '../../../../core/documents/documents.store';
import { PdfDropzone, formatSize } from '../../../../shared/pdf-dropzone/pdf-dropzone';
import { DocumentTable } from '../document-table/document-table';

type UploadState = 'idle' | 'uploading' | 'done' | 'error';

export function buildMetadataForm(type: DocumentTypeConfig): FormGroup {
  const controls: Record<string, FormControl> = {};
  for (const f of type.fields) {
    const validators: ValidatorFn[] = [];
    if (f.required) validators.push(Validators.required);
    if (f.type === 'text' || f.type === 'textarea') {
      validators.push(Validators.maxLength(f.type === 'text' ? 200 : 2000));
      if (f.required) validators.push(Validators.pattern(/\S/));
    }
    if (f.type === 'number') {
      if (f.min != null) validators.push(Validators.min(f.min));
      if (f.max != null) validators.push(Validators.max(f.max));
    }
    controls[f.key] = new FormControl(f.default ?? null, validators);
  }
  return new FormGroup(controls);
}

/** Field values without empty entries (strings trimmed). */
export function cleanMetadata(raw: Record<string, unknown>): Record<string, MetadataValue> {
  const out: Record<string, MetadataValue> = {};
  for (const [k, v] of Object.entries(raw)) {
    const value = typeof v === 'string' ? v.trim() : v;
    if (value !== null && value !== undefined && value !== '') out[k] = value as MetadataValue;
  }
  return out;
}

@Component({
  selector: 'app-upload-page',
  imports: [ReactiveFormsModule, RouterLink, PdfDropzone, DocumentTable],
  templateUrl: './upload-page.html',
  styleUrl: './upload-page.scss',
})
export class UploadPage {
  private readonly store = inject(DocumentsStore);

  protected readonly type = toSignal(
    inject(ActivatedRoute).paramMap.pipe(map((p) => documentType(p.get('type')))),
    { initialValue: undefined },
  );

  // Rebuilt when the type changes (the component is reused between Books / Exams / Tests).
  protected readonly form = computed<FormGroup>(() => {
    const t = this.type();
    return t ? buildMetadataForm(t) : new FormGroup({});
  });

  protected readonly file = signal<File | null>(null);
  protected readonly correction = signal<File | null>(null);
  protected readonly visibility = signal<DocumentStatus>('PUBLISHED');

  protected readonly submitted = signal(false);
  protected readonly state = signal<UploadState>('idle');
  protected readonly progress = signal(0);
  protected readonly uploaded = signal<LibraryDocument | null>(null);
  protected readonly error = signal<string | null>(null);

  /** Bumped on every form event so the computed values below follow the reactive form. */
  private readonly formTick = signal(0);

  protected readonly typeDocuments = computed(() => {
    const t = this.type();
    return t ? (this.store.byType().get(t.key) ?? []) : [];
  });

  protected readonly missing = computed(() => {
    this.formTick();
    const t = this.type();
    if (!t) return [];
    const out: string[] = [];
    if (!this.file()) out.push('PDF file');
    for (const f of t.fields) {
      const c = this.form().get(f.key)!;
      if (c.hasError('required') || c.hasError('pattern')) out.push(f.label);
      else if (c.invalid) out.push(`${f.label} (invalid)`);
    }
    return out;
  });

  protected readonly canUpload = computed(() => this.missing().length === 0 && this.state() !== 'uploading');

  /** Title the document will get (typed for books, generated for exams / tests). */
  protected readonly previewTitle = computed(() => {
    this.formTick();
    const t = this.type();
    if (!t) return '';
    const m = cleanMetadata(this.form().getRawValue());
    return t.title(m, (key) => optionLabel(t, key, m[key]));
  });

  protected readonly visibilityChoices: { value: DocumentStatus; title: string; text: string }[] = [
    { value: 'PUBLISHED', title: 'Publish now', text: 'Visible to students right after upload.' },
    { value: 'DRAFT', title: 'Save as draft', text: 'Only admins can see it until published.' },
  ];

  protected readonly size = formatSize;

  constructor() {
    this.store.refresh();

    // `events` covers value, status and touched changes (touched → show field errors on blur).
    effect((onCleanup) => {
      const sub = this.form().events.subscribe(() => this.formTick.update((n) => n + 1));
      onCleanup(() => sub.unsubscribe());
    });

    effect(() => {
      this.type();
      this.resetForm();
      this.uploaded.set(null);
    });
  }

  protected fieldError(f: FieldDef): string | null {
    this.formTick();
    const c = this.form().get(f.key);
    if (!c || c.valid || !(c.touched || this.submitted())) return null;
    if (c.hasError('required') || c.hasError('pattern')) return 'Required';
    if (c.hasError('min')) return `Minimum ${c.getError('min').min}`;
    if (c.hasError('max')) return `Maximum ${c.getError('max').max}`;
    if (c.hasError('maxlength')) return `Too long (max ${c.getError('maxlength').requiredLength})`;
    return 'Invalid value';
  }

  protected upload(): void {
    this.submitted.set(true);
    this.form().markAllAsTouched();
    const t = this.type();
    const file = this.file();
    if (!t || !file || !this.canUpload()) return;

    this.state.set('uploading');
    this.progress.set(0);
    this.error.set(null);
    this.uploaded.set(null);

    this.store
      .upload({
        type: t.key,
        file,
        correction: t.acceptsCorrection ? this.correction() : null,
        metadata: cleanMetadata(this.form().getRawValue()),
        status: this.visibility(),
      })
      .subscribe({
        next: (e) => {
          if (e.kind === 'progress') this.progress.set(e.percent);
          else {
            this.uploaded.set(e.document);
            this.resetForm();
            this.state.set('done');
          }
        },
        error: (err: { status?: number; error?: { message?: string } }) => {
          this.error.set(
            err.status === 0 || err.status === 404
              ? 'Storage backend is not reachable yet (POST /api/admin/documents).'
              : (err.error?.message ?? 'Upload failed.'),
          );
          this.state.set('error');
        },
      });
  }

  protected resetForm(): void {
    const t = this.type();
    if (t) this.form().reset(Object.fromEntries(t.fields.map((f) => [f.key, f.default ?? null])));
    this.file.set(null);
    this.correction.set(null);
    this.visibility.set('PUBLISHED');
    this.submitted.set(false);
    this.state.set('idle');
    this.progress.set(0);
    this.error.set(null);
  }
}
