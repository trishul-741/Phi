import { SafeReportedPageClient } from "../../../components/pages/safe-reported-page-client";
import { pickSearchParam, type PageSearchParams } from "../../../lib/search-params";

export default async function SafeReportedPage({
  searchParams,
}: {
  searchParams: Promise<PageSearchParams>;
}) {
  const resolvedSearchParams = await searchParams;
  const deviceId = pickSearchParam(resolvedSearchParams.device_id);
  return <SafeReportedPageClient deviceId={deviceId} />;
}
