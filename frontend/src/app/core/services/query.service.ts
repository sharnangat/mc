import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';

import { API_BASE_URL } from '../config';
import { AttachmentType, ConsultationQuery, QueryDetail } from '../models';

export interface QueryCreateRequest {
  consultation_category_id: string;
  pricing_plan_id: string;
  question_text: string;
  priority?: 'normal' | 'high' | 'urgent';
}

@Injectable({ providedIn: 'root' })
export class QueryService {
  constructor(private readonly http: HttpClient) {}

  create(payload: QueryCreateRequest) {
    return this.http.post<ConsultationQuery>(`${API_BASE_URL}/queries`, payload);
  }

  list() {
    return this.http.get<ConsultationQuery[]>(`${API_BASE_URL}/queries`);
  }

  get(id: string) {
    return this.http.get<QueryDetail>(`${API_BASE_URL}/queries/${id}`);
  }

  uploadAttachment(queryId: string, attachmentType: AttachmentType, file: File) {
    const form = new FormData();
    form.append('attachment_type', attachmentType);
    form.append('file', file);
    return this.http.post(`${API_BASE_URL}/queries/${queryId}/attachments`, form);
  }
}
