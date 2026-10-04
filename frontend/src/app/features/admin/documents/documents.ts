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
  readonly selectedFiles = signal<File[]>([]);
  private fileInput: HTMLInputElement | null = null;
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
    this.fileInput = input;
    const files = input.files ? Array.from(input.files) : [];
    this.selectedFiles.set(files);
    if (!this.title.trim() && files.length === 1) {
      this.title = files[0].name.replace(/\.[^.]+$/, '');
    }
  }

  upload(): void {
    const files = this.selectedFiles();
    if (files.length === 0 || this.uploading()) return;
    this.uploading.set(true);
    this.errorMessage.set(null);
    this.uploadAt(files, 0);
  }

  private uploadAt(files: File[], index: number): void {
    if (index >= files.length) {
      this.uploading.set(false);
      this.title = '';
      this.standardName = '';
      this.selectedFiles.set([]);
      if (this.fileInput) this.fileInput.value = '';
      this.reload();
      return;
    }

    const file = files[index];
    const title = files.length === 1 && this.title.trim() ? this.title.trim() : file.name.replace(/\.[^.]+$/, '');
    this.admin
      .uploadDocument({
        title,
        document_type: this.documentType,
        standard_name: this.standardName || undefined,
        licence_status: this.licenceStatus,
        access_permission: this.accessPermission,
        file,
      })
      .subscribe({
        next: () => this.uploadAt(files, index + 1),
        error: (err) => {
          this.uploading.set(false);
          this.reload();
          const detail = err?.error?.detail;
          const status = err?.status;
          const name = file.name;
          if (status === 413) {
            this.errorMessage.set(`Upload failed for ${name}: file is too large (max 1 GB).`);
          } else if (typeof detail === 'string') {
            this.errorMessage.set(`${name}: ${detail}`);
          } else {
            this.errorMessage.set(`Upload failed for ${name}.`);
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
