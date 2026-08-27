import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { PricingPlan } from '../../../core/models';
import { AdminService } from '../../../core/services/admin.service';
import { CatalogService } from '../../../core/services/catalog.service';

@Component({
  selector: 'app-pricing',
  imports: [FormsModule],
  templateUrl: './pricing.html',
})
export class Pricing implements OnInit {
  readonly plans = signal<PricingPlan[]>([]);
  readonly loading = signal(true);
  readonly savingId = signal<string | null>(null);
  drafts: Record<string, string> = {};

  constructor(
    private readonly catalog: CatalogService,
    private readonly admin: AdminService
  ) {}

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.catalog.listPricingPlans().subscribe((plans) => {
      this.plans.set(plans);
      this.drafts = Object.fromEntries(plans.map((p) => [p.id, p.price_inr]));
      this.loading.set(false);
    });
  }

  save(plan: PricingPlan): void {
    const newPrice = this.drafts[plan.id];
    if (!newPrice || newPrice === plan.price_inr) return;

    this.savingId.set(plan.id);
    this.admin.updatePricingPlan(plan.id, { price_inr: newPrice }).subscribe(() => {
      this.savingId.set(null);
      this.reload();
    });
  }
}
