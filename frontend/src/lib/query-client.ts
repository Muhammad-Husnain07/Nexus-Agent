import { QueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        if (failureCount >= 3) return false
        const status = (error as { response?: { status?: number } })?.response?.status
        if (status && status >= 400 && status < 500) return false
        return true
      },
      refetchOnWindowFocus: false,
    },
    mutations: {
      onError: (error) => {
        const msg = (error as { response?: { data?: { message?: string } } })?.response?.data?.message || "An unexpected error occurred"
        toast.error(msg)
      },
    },
  },
})
