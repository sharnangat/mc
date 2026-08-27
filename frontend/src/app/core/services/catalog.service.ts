import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';

import { API_BASE_URL } from '../config';
import { ConsultationCategory, PricingPlan } from '../models';

@Injectable({ providedIn: 'root' })
export class CatalogService {
  constructor(private readonly http: HttpClient) {}

  listConsultationCategories() {
    return this.http.get<ConsultationCategory[]>(`${API_BASE_URL}/catalog/consultation-categories`);
  }

  listPricingPlans() {
    return this.http.get<PricingPlan[]>(`${API_BASE_URL}/catalog/pricing-plans`);
  }
}
