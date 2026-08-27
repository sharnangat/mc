import { DatePipe } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { ReviewDetailResponse } from '../../../core/models';
import { ExpertService } from '../../../core/services/expert.service';

@Component({
  selector: 'app-review-detail',
  imports: [FormsModule, DatePipe],
  templateUrl: './review-detail.html',
})
export class ReviewDetail implements OnInit {
  readonly detail = signal<ReviewDetailResponse | null>(null);
  readonly loading = signal(true);
  readonly busy = signal(false);
  readonly editMode = signal(false);
  readonly errorMessage = signal<string | null>(null);
  readonly infoMessage = signal<string | null>(null);

  editedConclusion = '';
  editedReasoning = '';
  editedRecommendedAction = '';
  comment = '';

  private queryId = '';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly expertService: ExpertService
  ) {}

  ngOnInit(): void {
    this.queryId = this.route.snapshot.paramMap.get('id')!;
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.expertService.detail(this.queryId).subscribe((detail) => {
      this.detail.set(detail);
      this.loading.set(false);
      this.editMode.set(false);
    });
  }

  startEdit(): void {
    const ai = this.detail()?.ai_answer;
    this.editedConclusion = ai?.technical_conclusion ?? '';
    this.editedReasoning = ai?.technical_reasoning ?? '';
    this.editedRecommendedAction = ai?.recommended_action ?? '';
    this.editMode.set(true);
  }

  private runAction(payload: Parameters<ExpertService['submitReview']>[1], successMessage: string): void {
    this.busy.set(true);
    this.errorMessage.set(null);
    this.expertService.submitReview(this.queryId, payload).subscribe({
      next: () => {
        this.busy.set(false);
        this.infoMessage.set(successMessage);
        this.reload();
      },
      error: () => {
        this.busy.set(false);
        this.errorMessage.set('Action failed. Please try again.');
      },
    });
  }

  saveEdit(): void {
    this.runAction(
      {
        action: 'edit',
        edited_technical_conclusion: this.editedConclusion,
        edited_technical_reasoning: this.editedReasoning,
        edited_recommended_action: this.editedRecommendedAction,
      },
      'Edits saved.'
    );
  }

  approve(): void {
    const hasEdits = this.editMode();
    this.runAction(
      {
        action: 'approve',
        edited_technical_conclusion: hasEdits ? this.editedConclusion : undefined,
        edited_technical_reasoning: hasEdits ? this.editedReasoning : undefined,
        edited_recommended_action: hasEdits ? this.editedRecommendedAction : undefined,
      },
      'Approved. You can now send this to the customer.'
    );
  }

  reject(): void {
    this.runAction({ action: 'reject', comment: this.comment || undefined }, 'Query rejected.');
  }

  requestMoreInfo(): void {
    this.runAction({ action: 'request_more_info', comment: this.comment || undefined }, 'More information requested.');
  }

  rerunAnalysis(): void {
    this.runAction({ action: 'rerun_analysis' }, 'AI analysis re-run.');
  }

  addComment(): void {
    if (!this.comment.trim()) return;
    this.runAction({ action: 'comment', comment: this.comment }, 'Comment added.');
    this.comment = '';
  }

  sendToCustomer(): void {
    this.busy.set(true);
    this.errorMessage.set(null);
    this.expertService.send(this.queryId).subscribe({
      next: () => {
        this.busy.set(false);
        this.infoMessage.set('Sent to customer.');
        this.reload();
      },
      error: () => {
        this.busy.set(false);
        this.errorMessage.set('Could not send to customer.');
      },
    });
  }
}
