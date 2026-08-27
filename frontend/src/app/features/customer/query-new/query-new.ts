import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { forkJoin } from 'rxjs';

import { ConsultationCategory, PricingPlan } from '../../../core/models';
import { CatalogService } from '../../../core/services/catalog.service';
import { QueryService } from '../../../core/services/query.service';

@Component({
  selector: 'app-query-new',
  imports: [FormsModule],
  templateUrl: './query-new.html',
})
export class QueryNew implements OnInit {
  readonly categories = signal<ConsultationCategory[]>([]);
  readonly plans = signal<PricingPlan[]>([]);
  readonly submitting = signal(false);
  readonly errorMessage = signal<string | null>(null);

  categoryId = '';
  planId = '';
  questionText = '';
  priority: 'normal' | 'high' | 'urgent' = 'normal';

  constructor(
    private readonly catalog: CatalogService,
    private readonly queryService: QueryService,
    private readonly router: Router
  ) {}

  ngOnInit(): void {
    forkJoin({
      categories: this.catalog.listConsultationCategories(),
      plans: this.catalog.listPricingPlans(),
    }).subscribe(({ categories, plans }) => {
      this.categories.set(categories);
      this.plans.set(plans);
      this.categoryId = categories[0]?.id ?? '';
      this.planId = plans[0]?.id ?? '';
    });
  }

  submit(): void {
    if (!this.categoryId || !this.planId || !this.questionText.trim()) return;

    this.errorMessage.set(null);
    this.submitting.set(true);

    this.queryService
      .create({
        consultation_category_id: this.categoryId,
        pricing_plan_id: this.planId,
        question_text: this.questionText.trim(),
        priority: this.priority,
      })
      .subscribe({
        next: (query) => this.router.navigate(['/queries', query.id]),
        error: () => {
          this.submitting.set(false);
          this.errorMessage.set('Could not submit the query. Please try again.');
        },
      });
  }
}
