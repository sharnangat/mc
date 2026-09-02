import { DatePipe } from '@angular/common';
import { Component, computed, ElementRef, OnDestroy, OnInit, signal, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ChatResponse } from '../../../core/models';
import { ChatService } from '../../../core/services/chat.service';

interface ChatTurn {
  role: 'user' | 'ai';
  text: string;
  response?: ChatResponse;
  error?: boolean;
}

interface ChatPair {
  question: ChatTurn;
  answer?: ChatTurn;
}

@Component({
  selector: 'app-chat-page',
  imports: [FormsModule, DatePipe],
  templateUrl: './chat-page.html',
  styleUrl: './chat-page.scss',
})
export class ChatPage implements OnInit, OnDestroy {
  readonly turns = signal<ChatTurn[]>([]);
  /** turns() grouped into question/answer pairs, so a question and its answer render (and print) as one block. */
  readonly pairs = computed<ChatPair[]>(() => {
    const t = this.turns();
    const result: ChatPair[] = [];
    for (let i = 0; i < t.length; i += 2) {
      result.push({ question: t[i], answer: t[i + 1] });
    }
    return result;
  });
  readonly sending = signal(false);
  readonly loadingHistory = signal(true);
  /** Index (in `pairs`) of the Q&A being exported alone, or null for a full-conversation export. */
  readonly printSingleIndex = signal<number | null>(null);
  readonly printedAt = new Date();
  draft = '';

  @ViewChild('scrollAnchor') private scrollAnchor?: ElementRef<HTMLElement>;

  private readonly onAfterPrint = () => this.printSingleIndex.set(null);

  constructor(private readonly chat: ChatService) {
    window.addEventListener('afterprint', this.onAfterPrint);
  }

  ngOnDestroy(): void {
    window.removeEventListener('afterprint', this.onAfterPrint);
  }

  ngOnInit(): void {
    this.chat.history().subscribe({
      next: (messages) => {
        const historyTurns = messages.flatMap((m): ChatTurn[] => [
          { role: 'user', text: m.question },
          { role: 'ai', text: m.answer.technical_conclusion, response: m.answer },
        ]);
        this.turns.update((t) => [...historyTurns, ...t]);
        this.loadingHistory.set(false);
        this.scrollSoon();
      },
      error: () => {
        this.loadingHistory.set(false);
      },
    });
  }

  send(): void {
    const message = this.draft.trim();
    if (!message || this.sending()) return;

    this.turns.update((t) => [...t, { role: 'user', text: message }]);
    this.draft = '';
    this.sending.set(true);
    this.scrollSoon();

    this.chat.send(message).subscribe({
      next: (response) => {
        this.turns.update((t) => [...t, { role: 'ai', text: response.technical_conclusion, response }]);
        this.sending.set(false);
        this.scrollSoon();
      },
      error: () => {
        this.turns.update((t) => [
          ...t,
          { role: 'ai', text: 'Something went wrong reaching the AI engine. Please try again.', error: true },
        ]);
        this.sending.set(false);
        this.scrollSoon();
      },
    });
  }

  downloadPdf(): void {
    this.printSingleIndex.set(null);
    this.printedAt.setTime(Date.now());
    setTimeout(() => window.print());
  }

  downloadTurnPdf(pairIndex: number): void {
    this.printSingleIndex.set(pairIndex);
    this.printedAt.setTime(Date.now());
    setTimeout(() => window.print());
  }

  isHiddenForSinglePrint(pairIndex: number): boolean {
    const target = this.printSingleIndex();
    return target !== null && pairIndex !== target;
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.send();
    }
  }

  private scrollSoon(): void {
    setTimeout(() => this.scrollAnchor?.nativeElement.scrollIntoView({ behavior: 'smooth' }), 50);
  }
}
