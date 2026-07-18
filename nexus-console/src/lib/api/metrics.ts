import { useQuery } from "@tanstack/react-query"
import { api } from "./"
import type { CostSummary, DailyCost, ToolUsageItem, RecentRun } from "@/lib/types"
import type { AxiosResponse } from "axios"

export function useGetDashboardMetrics(days = 7) {
  return useQuery<CostSummary>({
    queryKey: ["metrics", "summary", days],
    queryFn: () =>
      api
        .get<CostSummary>("/cost/summary", { params: { days } })
        .then((r: AxiosResponse<CostSummary>) => r.data),
  })
}

export function useGetCostTrend(days = 30) {
  return useQuery<DailyCost[]>({
    queryKey: ["metrics", "daily", days],
    queryFn: () =>
      api
        .get<DailyCost[]>("/cost/daily", { params: { days } })
        .then((r: AxiosResponse<DailyCost[]>) => r.data),
  })
}

export function useGetToolUsage(_days = 30) {
  return useQuery<ToolUsageItem[]>({
    queryKey: ["metrics", "tool-usage"],
    queryFn: async () => {
      // Backend endpoint pending — returns empty until /cost/by-tool is added
      return []
    },
  })
}

export function useGetRecentRuns(_limit = 20) {
  return useQuery<RecentRun[]>({
    queryKey: ["metrics", "recent-runs"],
    queryFn: async () => {
      // Backend endpoint pending — returns empty until /runs endpoint is added
      return []
    },
  })
}
