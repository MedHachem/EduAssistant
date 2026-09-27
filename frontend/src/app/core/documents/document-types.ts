/**
 * Declarative configuration of the official documents that can be uploaded.
 * The admin cards and upload forms are generated from this file.
 */
import { DocumentType, MetadataValue } from './document.model';

export interface SelectOption {
  value: string;
  label: string;
}

interface BaseField {
  key: string;
  label: string;
  required?: boolean;
  hint?: string;
  /** Grid span in the 2-column form (default 1). */
  span?: 1 | 2;
}

export type FieldDef =
  | (BaseField & { type: 'text'; placeholder?: string; default?: string })
  | (BaseField & { type: 'textarea'; placeholder?: string; default?: string })
  | (BaseField & { type: 'number'; placeholder?: string; min?: number; max?: number; default?: number })
  | (BaseField & { type: 'select'; options: SelectOption[]; default?: string });

export interface DocumentTypeConfig {
  key: DocumentType;
  label: string;
  singular: string;
  description: string;
  /** Where the document shows up once published. */
  studentVisibility: string;
  /** SVG path (24×24 viewBox). */
  icon: string;
  accent: string;
  accentSoft: string;
  fields: FieldDef[];
  /** A separate correction PDF can be attached. */
  acceptsCorrection: boolean;
  /** Builds the display title from the metadata when there is no "title" field. */
  title: (m: Record<string, MetadataValue>, label: (key: string) => string) => string;
}

const opts = (...values: string[]): SelectOption[] => values.map((v) => ({ value: v, label: v }));

export const SUBJECTS = opts(
  'Mathématiques',
  'Physique',
  'Chimie',
  'Sciences de la vie et de la Terre',
  'Informatique',
  'Technologie',
  'Économie',
  'Gestion',
  'Philosophie',
  'Français',
  'Arabe',
  'Anglais',
);

export const LEVELS: SelectOption[] = [
  { value: '1ere', label: '1ère année secondaire' },
  { value: '2eme', label: '2ème année secondaire' },
  { value: '3eme', label: '3ème année secondaire' },
  { value: '4eme', label: '4ème année secondaire' },
];

export const SECTIONS = opts(
  'Tronc commun',
  'Mathématiques',
  'Sciences expérimentales',
  'Sciences techniques',
  "Sciences de l'informatique",
  'Économie et gestion',
  'Lettres',
  'Sport',
);

const CURRENT_YEAR = new Date().getFullYear();
const SCHOOL_YEARS = opts(...Array.from({ length: 8 }, (_, i) => `${CURRENT_YEAR - i}-${CURRENT_YEAR - i + 1}`));
const LANGUAGES: SelectOption[] = [
  { value: 'fra', label: 'Français' },
  { value: 'ara', label: 'Arabe' },
  { value: 'eng', label: 'Anglais' },
];

const subject: FieldDef = { key: 'subject', label: 'Subject', type: 'select', options: SUBJECTS, required: true, default: 'Mathématiques' };
const level: FieldDef = { key: 'level', label: 'Level', type: 'select', options: LEVELS, required: true, default: '4eme' };
const section: FieldDef = { key: 'section', label: 'Section', type: 'select', options: SECTIONS, default: 'Mathématiques' };
const language: FieldDef = { key: 'language', label: 'Language', type: 'select', options: LANGUAGES, required: true, default: 'fra' };

export const DOCUMENT_TYPES: DocumentTypeConfig[] = [
  {
    key: 'book',
    label: 'Official Books',
    singular: 'book',
    description: 'Official textbooks (manuels scolaires) from the national curriculum.',
    studentVisibility: 'Published books appear in the student space as courses.',
    icon: 'M18 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2zM6 4h5v8l-2.5-1.5L6 12z',
    accent: '#4f46e5',
    accentSoft: '#eef2ff',
    fields: [
      { key: 'title', label: 'Book title', type: 'text', required: true, span: 2, placeholder: 'Mathématiques 4ème année secondaire — Tome 1' },
      subject,
      level,
      section,
      { key: 'tome', label: 'Volume (tome)', type: 'number', min: 1, max: 5, placeholder: '1' },
      { key: 'edition', label: 'Edition year', type: 'number', min: 1990, max: CURRENT_YEAR, placeholder: String(CURRENT_YEAR) },
      language,
      { key: 'description', label: 'Description', type: 'textarea', span: 2, placeholder: 'Short description shown to students (optional).' },
    ],
    acceptsCorrection: false,
    title: (m) => (m['title'] != null ? String(m['title']) : ''),
  },
  {
    key: 'exam',
    label: 'Official Exams',
    singular: 'exam',
    description: 'National exams: baccalauréat (principale & contrôle) and national concours.',
    studentVisibility: 'Published exams will be available to students for practice.',
    icon: 'M12 3 1 9l11 6 9-4.9V17h2V9zm-6.8 9.2V16c0 1.7 3 3.5 6.8 3.5s6.8-1.8 6.8-3.5v-3.8L12 16z',
    accent: '#15803d',
    accentSoft: '#e8f5ec',
    fields: [
      {
        key: 'examType',
        label: 'Exam',
        type: 'select',
        required: true,
        default: 'bac',
        options: [
          { value: 'bac', label: 'Baccalauréat' },
          { value: 'concours9', label: 'Concours 9ème année de base' },
          { value: 'concours6', label: 'Concours 6ème année primaire' },
        ],
      },
      { key: 'year', label: 'Year', type: 'number', required: true, min: 1990, max: CURRENT_YEAR, default: CURRENT_YEAR },
      {
        key: 'session',
        label: 'Session',
        type: 'select',
        required: true,
        default: 'principale',
        options: [
          { value: 'principale', label: 'Session principale' },
          { value: 'controle', label: 'Session de contrôle' },
        ],
      },
      { ...section, required: true },
      subject,
      { key: 'duration', label: 'Duration (h)', type: 'number', min: 1, max: 6, placeholder: '4' },
      { key: 'coefficient', label: 'Coefficient', type: 'number', min: 1, max: 6, placeholder: '4' },
      language,
    ],
    acceptsCorrection: true,
    title: (m, label) => `${label('examType')} ${m['year']} · ${label('session')} · ${label('section')} · ${label('subject')}`,
  },
  {
    key: 'test',
    label: 'Official Tests',
    singular: 'test',
    description: 'School tests: devoirs de contrôle, devoirs de synthèse and mock exams.',
    studentVisibility: 'Published tests will be available to students for practice.',
    icon: 'M9 2h6a1 1 0 0 1 1 1v1h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2V3a1 1 0 0 1 1-1zm1 2v2h4V4zm-2.3 9.3 1.4-1.4L11 13.8l3.9-3.9 1.4 1.4-5.3 5.3z',
    accent: '#b45309',
    accentSoft: '#fdf3e4',
    fields: [
      {
        key: 'testType',
        label: 'Test type',
        type: 'select',
        required: true,
        default: 'synthese',
        options: [
          { value: 'controle', label: 'Devoir de contrôle' },
          { value: 'synthese', label: 'Devoir de synthèse' },
          { value: 'blanc', label: 'Examen blanc' },
        ],
      },
      {
        key: 'trimester',
        label: 'Trimester',
        type: 'select',
        required: true,
        default: '1',
        options: [
          { value: '1', label: 'Trimestre 1' },
          { value: '2', label: 'Trimestre 2' },
          { value: '3', label: 'Trimestre 3' },
        ],
      },
      subject,
      level,
      section,
      { key: 'schoolYear', label: 'School year', type: 'select', required: true, options: SCHOOL_YEARS, default: SCHOOL_YEARS[0].value },
      { key: 'school', label: 'School', type: 'text', placeholder: 'Lycée …' },
      { key: 'duration', label: 'Duration (min)', type: 'number', min: 15, max: 300, placeholder: '120' },
      language,
    ],
    acceptsCorrection: true,
    title: (m, label) => `${label('testType')} · ${label('trimester')} · ${label('subject')} · ${m['schoolYear']}`,
  },
];

export function documentType(key: string | null | undefined): DocumentTypeConfig | undefined {
  return DOCUMENT_TYPES.find((t) => t.key === key);
}

/** Display label of a select value (e.g. level "4eme" → "4ème année secondaire"). */
export function optionLabel(type: DocumentTypeConfig, key: string, value: MetadataValue | null | undefined): string {
  if (value == null) return '';
  const f = type.fields.find((x) => x.key === key);
  return f?.type === 'select' ? (f.options.find((o) => o.value === value)?.label ?? String(value)) : String(value);
}

export function levelLabel(value: string | null): string {
  return LEVELS.find((l) => l.value === value)?.label ?? value ?? '';
}
