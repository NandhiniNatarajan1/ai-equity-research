import { PlaceholderScreen } from "@/components/shell/PlaceholderScreen";

export default function ObservabilityPage() {
  return (
    <PlaceholderScreen
      title="Agent Observability"
      description="Aggregated metrics across all agent runs · latency, token cost, failure rates"
      nextUp="Add a GET /system/metrics endpoint that aggregates agent_runs (by status, by ticker, latency percentiles), then plot with Recharts here."
    />
  );
}
