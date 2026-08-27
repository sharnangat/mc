import { DatePipe } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ConsultationQuery } from '../../../core/models';
import { QueryService } from '../../../core/services/query.service';

@Component({
  selector: 'app-query-list',
  imports: [RouterLink, DatePipe],
  templateUrl: './query-list.html',
})
export class QueryList implements OnInit {
  readonly queries = signal<ConsultationQuery[]>([]);
  readonly loading = signal(true);

  constructor(private readonly queryService: QueryService) {}

  ngOnInit(): void {
    this.queryService.list().subscribe((queries) => {
      this.queries.set(queries);
      this.loading.set(false);
    });
  }
}
