import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';

import { API_BASE_URL } from '../config';
import { ChatMessage, ChatResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class ChatService {
  constructor(private readonly http: HttpClient) {}

  history() {
    return this.http.get<ChatMessage[]>(`${API_BASE_URL}/chat`);
  }

  send(message: string) {
    return this.http.post<ChatResponse>(`${API_BASE_URL}/chat`, { message });
  }
}
