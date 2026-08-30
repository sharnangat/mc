import { DatePipe } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { DocumentType, KnowledgeDocument } from '../../../core/models';
import { AdminService } from '../../../core/services/admin.service';

const DOCUMENT_TYPES: DocumentType[] = [
  'standard',
  'handbook',
  'internal_report',
  'customer_document',
  'lab_procedure',
  'heat_treatment_procedure',
  'welding_procedure',
  'material_specification',
  'research_paper',
  'other',
];

@Component({
  selector: 'app-documents',
  imports: [FormsModule, DatePipe],
  templateUrl: './documents.html',
})
export class Documents implements OnInit {
  readonly documentTypes = DOCUMENT_TYPES;
  readonly documents = signal<KnowledgeDocument[]>([]);
  readonly loading = signal(true);
  readonly uploading = signal(false);
  readonly errorMessage = signal<string | null>(null);
  readonly ingestOpenFor = signal<string | null>(null);
  readonly ingesting = signal(false);
  readonly ingestingId = signal<string | null>(null);

  title = '';
  documentType: DocumentType = 'handbook';
  standardName = '';
  licenceStatus = 'internal';
  accessPermission = 'restricted';
  file: File | null = null;
  ingestText = '';

  constructor(private readonly admin: AdminService) {}

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.admin.listDocuments().subscribe((docs) => {
      this.documents.set(docs);
      this.loading.set(false);
    });
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.file = input.files?.[0] ?? null;
  }

  upload(): void {
    if (!this.title.trim() || !this.file) return;
    this.uploading.set(true);
    this.errorMessage.set(null);

    this.admin
      .uploadDocument({
        title: this.title.trim(),
        document_type: this.documentType,
        standard_name: this.standardName || undefined,
        licence_status: this.licenceStatus,
        access_permission: this.accessPermission,
        file: this.file,
      })
      .subscribe({
        next: () => {
          this.uploading.set(false);
          this.title = '';
          this.standardName = '';
          this.file = null;
          this.reload();
        },
        error: (err) => {
          this.uploading.set(false);
          const detail = err?.error?.detail;
          const status = err?.status;
          if (status === 413) {
            this.errorMessage.set('Upload failed: file is too large (max 300 MB).');
          } else if (typeof detail === 'string') {
            this.errorMessage.set(detail);
          } else {
            this.errorMessage.set('Upload failed.');
          }
        },
      });
  }

  toggleEnabled(doc: KnowledgeDocument): void {
    this.admin.setEnabled(doc.id, !doc.is_enabled_for_ai).subscribe(() => this.reload());
  }

  remove(doc: KnowledgeDocument): void {
    if (!confirm(`Delete "${doc.title}"? This cannot be undone.`)) return;
    this.admin.deleteDocument(doc.id).subscribe(() => this.reload());
  }

  ingestFromFile(doc: KnowledgeDocument): void {
    this.errorMessage.set(null);
    this.ingestingId.set(doc.id);
    this.admin.ingestDocument(doc.id).subscribe({
      next: () => {
        this.ingestingId.set(null);
        this.reload();
      },
      error: (err) => {
        this.ingestingId.set(null);
        this.errorMessage.set(err?.error?.detail ?? 'Ingestion from file failed.');
      },
    });
  }

  openIngest(doc: KnowledgeDocument): void {
    this.ingestText = '';
    this.ingestOpenFor.set(doc.id);
  }

  submitIngest(doc: KnowledgeDocument): void {
    if (!this.ingestText.trim()) return;
    this.ingesting.set(true);
    this.admin.ingestDocument(doc.id, this.ingestText.trim()).subscribe({
      next: () => {
        this.ingesting.set(false);
        this.ingestOpenFor.set(null);
        this.reload();
      },
      error: () => {
        this.ingesting.set(false);
        this.errorMessage.set('Ingestion failed.');
      },
    });
  }
}
