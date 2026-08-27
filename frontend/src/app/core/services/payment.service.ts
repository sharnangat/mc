import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';

import { API_BASE_URL } from '../config';
import { CreateOrderResponse, Payment } from '../models';

@Injectable({ providedIn: 'root' })
export class PaymentService {
  constructor(private readonly http: HttpClient) {}

  createOrder(queryId: string) {
    return this.http.post<CreateOrderResponse>(`${API_BASE_URL}/payments/${queryId}/create-order`, {});
  }

  /** Mock confirmation - a real integration would collect gateway_payment_id/signature from the Razorpay checkout widget. */
  confirm(queryId: string, gatewayOrderId: string) {
    return this.http.post<Payment>(`${API_BASE_URL}/payments/${queryId}/confirm`, {
      gateway_order_id: gatewayOrderId,
      gateway_payment_id: `pay_mock_${Date.now()}`,
    });
  }
}
