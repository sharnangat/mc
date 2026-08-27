import { Component, ElementRef, signal, ViewChild } from '@angular/core';
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
  imports: [FormsModule],
  templateUrl: './chat-page.html',
  styleUrl: './chat-page.scss',
})
export class ChatPage {
  readonly turns = signal<ChatTurn[]>([]);
  readonly sending = signal(false);
  draft = '';

  @ViewChild('scrollAnchor') private scrollAnchor?: ElementRef<HTMLElement>;

  constructor(private readonly chat: ChatService) {}

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
