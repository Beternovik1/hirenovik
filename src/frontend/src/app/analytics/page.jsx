import AnalyticsHeader from "@/components/analytics/AnalyticsHeader";
import SalaryByRoleChart from "@/components/analytics/SalaryByRoleChart";

export const metadata = {
  title: "Market Intelligence · Hirenovik",
};

export default function AnalyticsPage() {
  return (
    <div className="space-y-8">
      <AnalyticsHeader />
      <SalaryByRoleChart />
    </div>
  );
}
