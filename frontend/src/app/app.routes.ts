import { Routes } from '@angular/router';
import { authGuard, roleGuard } from './core/auth/auth.guard';
import { PIPELINE_STAGES } from './features/admin/ai-pipeline/pipeline-stages';
import { FigureReviewRound } from './features/admin/figure-review/figure-review';

const pipelineStage = () => import('./features/admin/ai-pipeline/pipeline-stage').then((m) => m.PipelineStage);
const figureReview = () => import('./features/admin/figure-review/figure-review').then((m) => m.FigureReview);
const figureAssociation = () => import('./features/admin/figure-association/figure-association').then((m) => m.FigureAssociation);
const ragAsk = () => import('./features/admin/ai-pipeline/rag-ask/rag-ask').then((m) => m.RagAsk);

const FIGURE_REVIEW_ROUND_3: FigureReviewRound = {
  reviewFile: 'visual_elements_review_v3.json',
  chapterIdSuffix: '-v3',
  roundLabel: 'Round 3 — completeness-refined (V3)',
};

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'login' },
  {
    path: 'login',
    loadComponent: () => import('./features/auth/login/login').then((m) => m.Login),
  },
  {
    path: 'admin',
    canActivate: [authGuard, roleGuard('ADMIN')],
    loadComponent: () =>
      import('./features/admin/admin-layout/admin-layout').then((m) => m.AdminLayout),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'overview' },
      {
        path: 'overview',
        title: 'Admin · Overview',
        loadComponent: () => import('./features/admin/overview/overview').then((m) => m.Overview),
      },

      // ---- Data Injection ----
      {
        path: 'data-injection',
        title: 'Admin · Data injection',
        loadComponent: () =>
          import('./features/admin/data-injection/data-injection').then((m) => m.DataInjection),
      },
      {
        path: 'data-injection/:type',
        title: 'Admin · Upload',
        loadComponent: () =>
          import('./features/admin/data-injection/upload/upload-page').then((m) => m.UploadPage),
      },

      // ---- Build AI Pipeline ----
      { path: 'ai-pipeline', pathMatch: 'full', redirectTo: 'ai-pipeline/ocr' },
      { path: 'ai-pipeline/ocr', title: 'Admin · OCR', loadComponent: pipelineStage, data: { stage: PIPELINE_STAGES.ocr } },
      {
        path: 'ai-pipeline/image-validation',
        title: 'Admin · Figure Review',
        loadComponent: figureReview,
      },
      {
        path: 'ai-pipeline/image-validation-v3',
        title: 'Admin · Figure Review (Round 3)',
        loadComponent: figureReview,
        data: { round: FIGURE_REVIEW_ROUND_3 },
      },
      {
        path: 'ai-pipeline/knowledge-base',
        title: 'Admin · Knowledge Base',
        loadComponent: () =>
          import('./features/admin/knowledge-review/knowledge-review').then((m) => m.KnowledgeReview),
      },
      {
        path: 'ai-pipeline/figure-association',
        title: 'Admin · Figure ↔ Knowledge',
        loadComponent: figureAssociation,
      },
      { path: 'ai-pipeline/rag', title: 'Admin · RAG', loadComponent: ragAsk },

      // Former URLs
      { path: 'data-pipeline', redirectTo: 'data-injection' },
      { path: 'knowledge-review', redirectTo: 'ai-pipeline/knowledge-base' },
    ],
  },
  {
    path: 'app',
    canActivate: [authGuard, roleGuard('CLIENT')],
    loadComponent: () =>
      import('./features/client/client-layout/client-layout').then((m) => m.ClientLayout),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'courses' },
      {
        path: 'courses',
        title: 'EduAssistant · Mes cours',
        loadComponent: () => import('./features/client/courses/courses-page').then((m) => m.CoursesPage),
      },
      {
        path: 'courses/:id',
        title: 'EduAssistant · Cours',
        loadComponent: () => import('./features/client/courses/course-viewer').then((m) => m.CourseViewer),
      },
      {
        path: 'chat',
        title: 'EduAssistant · Professeur IA',
        loadChildren: () => import('./features/client/chat/chat.routes').then((m) => m.chatRoutes),
      },
    ],
  },
  { path: '**', redirectTo: 'login' },
];
