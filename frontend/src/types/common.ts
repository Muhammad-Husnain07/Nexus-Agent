export interface PaginationParams {
  page?: number;
  page_size?: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface FilterParams {
  search?: string;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  [key: string]: unknown;
}
