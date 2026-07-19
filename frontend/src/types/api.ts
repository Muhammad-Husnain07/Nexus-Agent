export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string;
}

export interface ApiResponse<T> {
  data?: T;
  error?: ApiError;
}
