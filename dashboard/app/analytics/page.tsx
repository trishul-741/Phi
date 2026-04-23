import { AnalyticsPageClient } from "../../components/pages/analytics-page-client";
import { pickSearchParam, type PageSearchParams } from "../../lib/search-params";

export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<PageSearchParams>;
}) {
  const resolvedSearchParams = await searchParams;
  const deviceId = pickSearchParam(resolvedSearchParams.device_id);
  return <AnalyticsPageClient deviceId={deviceId} />;
}
