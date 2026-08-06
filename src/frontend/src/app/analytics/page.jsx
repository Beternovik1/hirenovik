import AnalyticsHeader from "@/components/analytics/AnalyticsHeader";
import SalaryByRoleChart from "@/components/analytics/SalaryByRoleChart";
import IndustryDemandTable from "@/components/analytics/IndustryDemandTable";

export const metadata = {
  title: "Market Intelligence · Hirenovik",
};

export default function AnalyticsPage() {
  return (
    <div className="space-y-8">
      <AnalyticsHeader />
      <SalaryByRoleChart />
      <IndustryDemandTable />
    </div>
  );
}
