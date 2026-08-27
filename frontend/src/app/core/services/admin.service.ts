import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';

import { API_BASE_URL } from '../config';
import { DocumentType, KnowledgeDocument, PricingPlan } from '../models';

export interface DocumentUploadForm {
  title: string;
  document_type: DocumentType;
  standard_name?: string;
  licence_status: string;
  access_permission: string;
  file: File;
}

@Injectable({ providedIn: 'root' })
export class AdminService {
  constructor(private readonly http: HttpClient) {}

  listDocuments() {
    return this.http.get<KnowledgeDocument[]>(`${API_BASE_URL}/admin/documents`);
  }

  uploadDocument(form: DocumentUploadForm) {
    const data = new FormData();
    data.append('title', form.title);
    data.append('document_type', form.document_type);
    if (form.standard_name) data.append('standard_name', form.standard_name);
    data.append('licence_status', form.licence_status);
    data.append('access_permission', form.access_permission);
    data.append('file', form.file);
    return this.http.post<KnowledgeDocument>(`${API_BASE_URL}/admin/documents`, data);
  }

  setEnabled(documentId: string, enabled: boolean) {
    return this.http.patch<KnowledgeDocument>(`${API_BASE_URL}/admin/documents/${documentId}`, {
      is_enabled_for_ai: enabled,
    });
  }

  deleteDocument(documentId: string) {
    return this.http.delete(`${API_BASE_URL}/admin/documents/${documentId}`);
  }

  /** Omit contentText to auto-extract from the stored file (PDF/TXT); pass it to override with pasted text. */
  ingestDocument(documentId: string, contentText?: string) {
    const data = new FormData();
    if (contentText) data.append('content_text', contentText);
    return this.http.post<KnowledgeDocument>(`${API_BASE_URL}/admin/documents/${documentId}/ingest`, data);
  }

  updatePricingPlan(planId: string, changes: Partial<Pick<PricingPlan, 'name' | 'description' | 'price_inr'>> & { is_active?: boolean }) {
    return this.http.patch<PricingPlan>(`${API_BASE_URL}/admin/pricing-plans/${planId}`, changes);
  }
}
