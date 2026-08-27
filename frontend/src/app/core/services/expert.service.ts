import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';

import { API_BASE_URL } from '../config';
import { ConsultationQuery, ExpertReview, FinalAnswer, ReviewDetailResponse } from '../models';

export interface ReviewActionRequest {
  action: 'approve' | 'edit' | 'reject' | 'request_more_info' | 'rerun_analysis' | 'comment';
  edited_technical_conclusion?: string;
  edited_technical_reasoning?: string;
  edited_recommended_action?: string;
  comment?: string;
}

@Injectable({ providedIn: 'root' })
export class ExpertService {
  constructor(private readonly http: HttpClient) {}

  queue() {
    return this.http.get<ConsultationQuery[]>(`${API_BASE_URL}/expert/queries`);
  }

  detail(queryId: string) {
    return this.http.get<ReviewDetailResponse>(`${API_BASE_URL}/expert/queries/${queryId}`);
  }

  submitReview(queryId: string, payload: ReviewActionRequest) {
    return this.http.post<ExpertReview>(`${API_BASE_URL}/expert/queries/${queryId}/review`, payload);
  }

  send(queryId: string) {
    return this.http.post<FinalAnswer>(`${API_BASE_URL}/expert/queries/${queryId}/send`, {});
  }
}
