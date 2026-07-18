import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "./"
import { useGetSessions } from "./sessions"
import type { ApprovalRead, ApprovalAction } from "@/lib/types"
import type { AxiosResponse } from "axios"

export function useDecideApproval() {
  const queryClient = useQueryClient()

  return useMutation<
    { status: string; approval_id: string; decision: string },
    Error,
    { approvalId: string; data: ApprovalAction }
  >({
    mutationFn: ({ approvalId, data }) =>
      api
        .post(`/approvals/${approvalId}/decide`, data)
        .then((r: AxiosResponse<{ status: string; approval_id: string; decision: string }>) => r.data),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["approvals"] })
    },
  })
}

export function useGetAllPendingApprovals() {
  const { data: sessionsData } = useGetSessions({ page_size: 100, status: "active" })

  return useQuery<ApprovalRead[]>({
    queryKey: ["approvals", "pending", "all"],
    queryFn: async () => {
      if (!sessionsData?.items?.length) return []

      const results: ApprovalRead[] = []
      const seen = new Set<string>()

      for (const session of sessionsData.items) {
        try {
          const res = await api.get<ApprovalRead[]>(`/approvals/pending/${session.id}`)
          for (const item of res.data) {
            if (!seen.has(item.id)) {
              seen.add(item.id)
              results.push(item)
            }
          }
        } catch {
          // skip sessions that fail
        }
      }

      return results
    },
    enabled: !!sessionsData?.items?.length,
    refetchInterval: 15_000,
  })
}

export function useGetSessionPendingApprovals(sessionId: string | null) {
  return useQuery<ApprovalRead[]>({
    queryKey: ["approvals", "pending", sessionId],
    queryFn: () =>
      api.get<ApprovalRead[]>(`/approvals/pending/${sessionId}`).then((r: AxiosResponse<ApprovalRead[]>) => r.data),
    enabled: !!sessionId,
  })
}
