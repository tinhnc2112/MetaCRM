import { useQuery } from "@tanstack/react-query";

export function useAppVersion() {
  return useQuery({
    queryKey: ["app-version"],
    queryFn: async () => window.metacrm?.getAppVersion() ?? "0.1.0"
  });
}
