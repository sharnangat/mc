export interface User {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  company_name: string | null;
  is_active: boolean;
  roles: string[];
}

export interface ConsultationCategory {
  id: string;
  code: string;
  name: string;
  description: string | null;
  sort_order: number;
}

export interface PricingPlan {
  id: string;
  code: string;
  name: string;
  description: string | null;
  price_inr: string;
  consultation_category_id: string | null;
  is_active?: boolean;
}

export type AttachmentType =
  | 'chemical_composition'
  | 'hardness_result'
  | 'tensile_result'
  | 'heat_treatment_cycle'
  | 'microstructure_photo'
  | 'spectro_report'
  | 'test_report'
  | 'failure_photo'
  | 'drawing_specification'
  | 'welding_detail'
  | 'pwht_detail'
  | 'other';

export interface Attachment {
  id: string;
  attachment_type: AttachmentType;
  file_name: string;
  uploaded_at: string;
}

export type QueryStatus =
  | 'pending_payment'
  | 'paid'
  | 'ai_processing'
  | 'draft_ready'
  | 'under_expert_review'
  | 'more_info_requested'
  | 'approved'
  | 'rejected'
  | 'sent'
  | 'closed';

export interface ConsultationQuery {
  id: string;
  query_code: string | null;
  customer_id: string;
  consultation_category_id: string;
  pricing_plan_id: string;
  question_text: string;
  priority: 'normal' | 'high' | 'urgent';
  status: QueryStatus;
  assigned_expert_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface QueryDetail extends ConsultationQuery {
  attachments: Attachment[];
  final_answer: FinalAnswer | null;
}

export interface AIAnswerSource {
  id: string;
  document_id: string;
  document_title?: string | null;
  relevance_score: string | null;
  cited_text: string | null;
  page_number: number | null;
  section: string | null;
  clause_number: string | null;
}

export interface AIAnswer {
  id: string;
  query_id: string;
  model_name: string;
  model_version: string;
  technical_conclusion: string | null;
  technical_reasoning: string | null;
  recommended_action: string | null;
  insufficient_information: boolean;
  status: string;
  created_at: string;
  sources: AIAnswerSource[];
}

export interface ExpertReview {
  id: string;
  query_id: string;
  expert_id: string;
  action: string;
  comment: string | null;
  created_at: string;
}

export interface FinalAnswer {
  id: string;
  query_id: string;
  final_technical_conclusion: string;
  final_technical_reasoning: string | null;
  final_recommended_action: string | null;
  references_json: unknown;
  sent_at: string | null;
  sent_via: string[];
}

export interface ReviewDetailResponse {
  query: ConsultationQuery;
  attachments: Attachment[];
  ai_answer: AIAnswer | null;
  reviews: ExpertReview[];
}

export interface CreateOrderResponse {
  payment_id: string;
  gateway: string;
  gateway_order_id: string;
  amount_inr: string;
  currency: string;
}

export interface Payment {
  id: string;
  query_id: string;
  amount_inr: string;
  currency: string;
  gateway: string;
  status: string;
  paid_at: string | null;
  created_at: string;
}

export type DocumentType =
  | 'standard'
  | 'handbook'
  | 'internal_report'
  | 'customer_document'
  | 'lab_procedure'
  | 'heat_treatment_procedure'
  | 'welding_procedure'
  | 'material_specification'
  | 'research_paper'
  | 'other';

export interface ChatSource {
  document_id: string;
  document_title: string;
  page_number: number | null;
  relevance_score: string | null;
  cited_text: string | null;
}

export interface ChatResponse {
  technical_conclusion: string;
  technical_reasoning: string | null;
  recommended_action: string | null;
  insufficient_information: boolean;
  sources: ChatSource[];
}

export interface ChatMessage {
  id: string;
  question: string;
  answer: ChatResponse;
  created_at: string;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  document_type: DocumentType;
  standard_name: string | null;
  edition_year: number | null;
  revision: string | null;
  source_owner: string | null;
  licence_status: string;
  access_permission: string;
  is_enabled_for_ai: boolean;
  indexing_status: string;
  uploaded_at: string;
  last_indexed_at: string | null;
}
