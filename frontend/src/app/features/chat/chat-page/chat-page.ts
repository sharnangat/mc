import { DatePipe } from '@angular/common';
import { Component, ElementRef, OnInit, signal, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ChatResponse } from '../../../core/models';
import { ChatService } from '../../../core/services/chat.service';

interface ChatTurn {
  role: 'user' | 'ai';
  text: string;
  response?: ChatResponse;
  error?: boolean;
}

@Component({
  selector: 'app-chat-page',
  imports: [FormsModule, DatePipe],
  templateUrl: './chat-page.html',
  styleUrl: './chat-page.scss',
})
export class ChatPage implements OnInit {
  readonly turns = signal<ChatTurn[]>([]);
  readonly sending = signal(false);
  readonly loadingHistory = signal(true);
  readonly printedAt = new Date();
  draft = '';

  @ViewChild('scrollAnchor') private scrollAnchor?: ElementRef<HTMLElement>;

  constructor(private readonly chat: ChatService) {}

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
    this.printedAt.setTime(Date.now());
    window.print();
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
