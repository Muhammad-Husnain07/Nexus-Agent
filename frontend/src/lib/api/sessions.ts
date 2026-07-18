import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "./"
import type {
  SessionRead,
  SessionList,
  SessionCreate,
  SessionUpdate,
  ForkRequest,
  MessageList,
} from "@/lib/types"
import type { AxiosResponse } from "axios"

interface GetSessionsParams {
  page?: number
  page_size?: number
  status?: string
}

interface UpdateContext {
  previousSessions: SessionList | undefined
}

interface ArchiveContext {
  previous: SessionList | undefined
}

export function useGetSessions(params?: GetSessionsParams) {
  return useQuery<SessionList>({
    queryKey: ["sessions", params],
    queryFn: () =>
      api
        .get<SessionList>("/sessions", {
          params: {
            page: params?.page ?? 1,
            page_size: params?.page_size ?? 20,
            ...(params?.status ? { status: params.status } : {}),
          },
        })
        .then((r: AxiosResponse<SessionList>) => r.data),
    placeholderData: (prev) => prev,
  })
}

export function useGetSession(sessionId: string | null) {
  return useQuery<SessionRead>({
    queryKey: ["sessions", sessionId],
    queryFn: () => api.get<SessionRead>(`/sessions/${sessionId}`).then((r: AxiosResponse<SessionRead>) => r.data),
    enabled: !!sessionId,
  })
}

export function useGetMessages(sessionId: string | null, params?: { page?: number }) {
  return useQuery<MessageList>({
    queryKey: ["sessions", sessionId, "messages", params],
    queryFn: () =>
      api
        .get<MessageList>(`/sessions/${sessionId}/messages`, {
          params: { page: params?.page ?? 1, page_size: 50 },
        })
        .then((r: AxiosResponse<MessageList>) => r.data),
    enabled: !!sessionId,
  })
}

export function useCreateSession() {
  const queryClient = useQueryClient()

  return useMutation<SessionRead, Error, SessionCreate>({
    mutationFn: (data) => api.post<SessionRead>("/sessions", data).then((r: AxiosResponse<SessionRead>) => r.data),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] })
    },
  })
}

export function useUpdateSession() {
  const queryClient = useQueryClient()

  return useMutation<SessionRead, Error, { id: string; data: SessionUpdate }, UpdateContext>({
    mutationFn: ({ id, data }) =>
      api.patch<SessionRead>(`/sessions/${id}`, data).then((r: AxiosResponse<SessionRead>) => r.data),
    onMutate: async ({ id, data }) => {
      await queryClient.cancelQueries({ queryKey: ["sessions"] })
      const key = ["sessions", { page: 1, page_size: 20 }]
      const previousSessions = queryClient.getQueryData<SessionList>(key)
      if (previousSessions) {
        queryClient.setQueryData<SessionList>(key, {
          ...previousSessions,
          items: previousSessions.items.map((s) => (s.id === id ? { ...s, ...data } : s)),
        })
      }
      queryClient.setQueryData<SessionRead>(["sessions", id], (old) => (old ? { ...old, ...data } : old))
      return { previousSessions }
    },
    onError: (_err, _vars, context) => {
      if (context?.previousSessions) {
        queryClient.setQueryData(["sessions", { page: 1, page_size: 20 }], context.previousSessions)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] })
    },
  })
}

export function useArchiveSession() {
  const queryClient = useQueryClient()

  return useMutation<void, Error, string, ArchiveContext>({
    mutationFn: (id) => api.delete(`/sessions/${id}`),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ["sessions"] })
      const key = ["sessions", { page: 1, page_size: 20 }]
      const previous = queryClient.getQueryData<SessionList>(key)
      if (previous) {
        queryClient.setQueryData<SessionList>(key, {
          ...previous,
          items: previous.items.filter((s) => s.id !== id),
          total: previous.total - 1,
        })
      }
      return { previous }
    },
    onError: (_err, _id, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["sessions", { page: 1, page_size: 20 }], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] })
    },
  })
}

export function useForkSession() {
  const queryClient = useQueryClient()

  return useMutation<SessionRead, Error, { id: string; data: ForkRequest }>({
    mutationFn: ({ id, data }) =>
      api
        .post<SessionRead>(`/sessions/${id}/fork`, data)
        .then((r: AxiosResponse<SessionRead>) => r.data),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] })
    },
  })
}
