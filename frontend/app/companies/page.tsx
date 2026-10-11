import { PlaceholderScreen } from "@/components/shell/PlaceholderScreen";

export default function CompaniesPage() {
  return (
    <PlaceholderScreen
      title="Companies"
      description="Per-ticker financial dashboard · 5Y history · competitive context"
      nextUp="Pull /system/status + /research/report cached JSON per ticker, render Recharts time series for revenue / margins / FCF, and a competitors sub-tab."
    />
  );
}
