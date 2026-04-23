import { PhishingHistoryPageClient } from "../../../components/pages/phishing-history-page-client";
import { pickSearchParam, type PageSearchParams } from "../../../lib/search-params";

export default async function PhishingHistoryPage({
  searchParams,
}: {
  searchParams: Promise<PageSearchParams>;
}) {
  const resolvedSearchParams = await searchParams;
  const deviceId = pickSearchParam(resolvedSearchParams.device_id);
  return <PhishingHistoryPageClient deviceId={deviceId} />;
}
