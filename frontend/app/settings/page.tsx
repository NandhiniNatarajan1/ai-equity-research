import { PlaceholderScreen } from "@/components/shell/PlaceholderScreen";

export default function SettingsPage() {
  return (
    <PlaceholderScreen
      title="Settings"
      description="Model configuration, API keys, embedding provider"
      nextUp="Expose read-only /system/config (model, embedding provider, LangSmith on/off) and let the user swap route-model split or peer list defaults."
    />
  );
}
