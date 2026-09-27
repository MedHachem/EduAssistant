// One-way copy of the Python pipeline outputs into the Angular static assets.
// Reads from data/output/ (never writes there); writes gitignored copies to public/.
//
//   data/output/knowledge/*.json                 → public/knowledge/
//   data/output/page_images/*.png                → public/page-images/
//   data/output/visual_elements_review.json      → public/figures/visual_elements_review.json    (round 1, V1 seeds)
//   data/output/visual_elements_review_v3.json   → public/figures/visual_elements_review_v3.json (round 3, V3 completeness-refined)
//   data/output/figure_candidates_refined/       → public/figure_candidates_refined/ (recursive, round 1 crops)
//   data/output/figure_candidates/               → public/figure_candidates/ (recursive, seed crops for comparison)
//   data/output/figure_candidates_v3/            → public/figure_candidates_v3/ (recursive, round 3 crops)
//   data/output/final_figures/                   → public/final_figures/ (recursive, Phase 5a final figure PNGs + index.json)
//   data/output/<chapter_id>/associations/figure_knowledge.json
//                                                 → public/associations/<chapter_id>/figure_knowledge.json
//     (chapter-generic: scans every data/output/*/associations/ directory that
//     exists, rather than a fixed chapter_01 path -- see data/src/config.py's
//     associations_dir(chapter_id) and data/schema/figure_knowledge_association.md)
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = resolve(frontend, '../data/output');

const fileTargets = [
  { from: join(output, 'knowledge'), to: join(frontend, 'public/knowledge'), ext: '.json' },
  { from: join(output, 'page_images'), to: join(frontend, 'public/page-images'), ext: '.png' },
];

for (const { from, to, ext } of fileTargets) {
  rmSync(to, { recursive: true, force: true });
  mkdirSync(to, { recursive: true });
  if (!existsSync(from)) {
    console.warn(`[sync-knowledge] missing ${from} — skipped`);
    continue;
  }
  const files = readdirSync(from).filter((f) => f.endsWith(ext));
  for (const f of files) cpSync(join(from, f), join(to, f));
  console.log(`[sync-knowledge] ${files.length} file(s) ${from} → ${to}`);
}

// Figure review: single JSON reports (one per review round)...
const singleFileTargets = [
  { from: join(output, 'visual_elements_review.json'), to: join(frontend, 'public/figures/visual_elements_review.json') },
  { from: join(output, 'visual_elements_review_v3.json'), to: join(frontend, 'public/figures/visual_elements_review_v3.json') },
];

for (const { from, to } of singleFileTargets) {
  rmSync(to, { force: true });
  mkdirSync(dirname(to), { recursive: true });
  if (!existsSync(from)) {
    console.warn(`[sync-knowledge] missing ${from} — skipped`);
    continue;
  }
  cpSync(from, to);
  console.log(`[sync-knowledge] 1 file(s) ${from} → ${to}`);
}

// ...plus the (non-flat, page_NNN/ subfolder) crop directories -- copied recursively as-is.
const dirTargets = [
  { from: join(output, 'figure_candidates_refined'), to: join(frontend, 'public/figure_candidates_refined') },
  { from: join(output, 'figure_candidates'), to: join(frontend, 'public/figure_candidates') },
  { from: join(output, 'figure_candidates_v3'), to: join(frontend, 'public/figure_candidates_v3') },
  { from: join(output, 'final_figures'), to: join(frontend, 'public/final_figures') },
];

for (const { from, to } of dirTargets) {
  rmSync(to, { recursive: true, force: true });
  if (!existsSync(from)) {
    console.warn(`[sync-knowledge] missing ${from} — skipped`);
    continue;
  }
  cpSync(from, to, { recursive: true });
  console.log(`[sync-knowledge] directory ${from} → ${to}`);
}

// Figure <-> knowledge associations: one subdirectory per chapter under
// data/output/, e.g. data/output/math-4eme-tome1-ch01/associations/figure_knowledge.json.
// Scanned rather than hardcoded so a future chapter needs no change here.
const associationsOut = join(frontend, 'public/associations');
rmSync(associationsOut, { recursive: true, force: true });
if (existsSync(output)) {
  const chapterDirs = readdirSync(output).filter((name) => {
    const full = join(output, name);
    return statSync(full).isDirectory() && existsSync(join(full, 'associations', 'figure_knowledge.json'));
  });
  for (const chapterId of chapterDirs) {
    const from = join(output, chapterId, 'associations', 'figure_knowledge.json');
    const to = join(associationsOut, chapterId, 'figure_knowledge.json');
    mkdirSync(dirname(to), { recursive: true });
    cpSync(from, to);
    console.log(`[sync-knowledge] 1 file(s) ${from} → ${to}`);
  }
  if (chapterDirs.length === 0) {
    console.warn(`[sync-knowledge] no */associations/figure_knowledge.json found under ${output} — skipped`);
  }
}
