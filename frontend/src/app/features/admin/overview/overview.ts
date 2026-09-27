import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-admin-overview',
  imports: [RouterLink],
  template: `
    <header class="page-header">
      <h1>Admin dashboard</h1>
      <p>Manage the content that feeds EduAssistant.</p>
    </header>
    <div class="grid">
      <section class="card">
        <h2>Data injection</h2>
        <p>Upload official books, exams and tests. Published books appear in the student space as courses.</p>
        <a routerLink="../data-injection" class="btn-primary">Open data injection</a>
      </section>
      <section class="card">
        <h2>Build AI pipeline</h2>
        <p>OCR, image validation, Knowledge Base review and RAG indexing of the uploaded documents.</p>
        <a routerLink="../ai-pipeline/knowledge-base" class="btn-secondary">Open Knowledge Base</a>
      </section>
    </div>
  `,
  styles: `
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1rem;
      max-width: 1000px;
    }
    h2 {
      margin-top: 0;
    }
    a {
      display: inline-block;
      text-decoration: none;
    }
  `,
})
export class Overview {}
