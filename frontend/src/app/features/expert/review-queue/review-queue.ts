import { DatePipe } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ConsultationQuery } from '../../../core/models';
import { ExpertService } from '../../../core/services/expert.service';

@Component({
  selector: 'app-review-queue',
  imports: [RouterLink, DatePipe],
  templateUrl: './review-queue.html',
})
export class ReviewQueue implements OnInit {
  readonly queries = signal<ConsultationQuery[]>([]);
  readonly loading = signal(true);

  constructor(private readonly expertService: ExpertService) {}

  ngOnInit(): void {
    this.expertService.queue().subscribe((queries) => {
      this.queries.set(queries);
      this.loading.set(false);
    });
  }
}
