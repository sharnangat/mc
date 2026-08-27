import { DatePipe } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { switchMap } from 'rxjs';

import { AttachmentType, QueryDetail } from '../../../core/models';
import { PaymentService } from '../../../core/services/payment.service';
import { QueryService } from '../../../core/services/query.service';

const ATTACHMENT_TYPES: { value: AttachmentType; label: string }[] = [
  { value: 'chemical_composition', label: 'Chemical Composition' },
  { value: 'hardness_result', label: 'Hardness Result' },
  { value: 'tensile_result', label: 'Tensile Result' },
  { value: 'heat_treatment_cycle', label: 'Heat Treatment Cycle' },
  { value: 'microstructure_photo', label: 'Microstructure Photo' },
  { value: 'spectro_report', label: 'Spectro Report' },
  { value: 'test_report', label: 'Test Report' },
  { value: 'failure_photo', label: 'Failure Photo' },
  { value: 'drawing_specification', label: 'Drawing / Specification' },
  { value: 'welding_detail', label: 'Welding Detail' },
  { value: 'pwht_detail', label: 'PWHT Detail' },
  { value: 'other', label: 'Other' },
];

@Component({
  selector: 'app-query-detail',
  imports: [FormsModule, DatePipe],
  templateUrl: './query-detail.html',
})
export class QueryDetailPage implements OnInit {
  readonly attachmentTypes = ATTACHMENT_TYPES;
  readonly query = signal<QueryDetail | null>(null);
  readonly loading = signal(true);
  readonly paying = signal(false);
  readonly uploading = signal(false);
  readonly errorMessage = signal<string | null>(null);

  selectedAttachmentType: AttachmentType = 'hardness_result';
  selectedFile: File | null = null;

  private queryId = '';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly queryService: QueryService,
    private readonly paymentService: PaymentService
  ) {}

  ngOnInit(): void {
    this.queryId = this.route.snapshot.paramMap.get('id')!;
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.queryService.get(this.queryId).subscribe((q) => {
      this.query.set(q);
      this.loading.set(false);
    });
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.selectedFile = input.files?.[0] ?? null;
  }

  uploadAttachment(): void {
    if (!this.selectedFile) return;
    this.uploading.set(true);
    this.queryService.uploadAttachment(this.queryId, this.selectedAttachmentType, this.selectedFile).subscribe({
      next: () => {
        this.uploading.set(false);
        this.selectedFile = null;
        this.reload();
      },
      error: () => {
        this.uploading.set(false);
        this.errorMessage.set('Attachment upload failed.');
      },
    });
  }

  pay(): void {
    this.paying.set(true);
    this.errorMessage.set(null);

    this.paymentService
      .createOrder(this.queryId)
      .pipe(switchMap((order) => this.paymentService.confirm(this.queryId, order.gateway_order_id)))
      .subscribe({
        next: () => {
          this.paying.set(false);
          this.reload();
        },
        error: () => {
          this.paying.set(false);
          this.errorMessage.set('Payment could not be completed. Please try again.');
        },
      });
  }
}
