import { ReportPageClient } from "../../../components/pages/report-page-client";
import { pickSearchParam, type PageSearchParams } from "../../../lib/search-params";

export default async function ReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ scanId: string }>;
  searchParams: Promise<PageSearchParams>;
}) {
  const resolvedParams = await params;
  const resolvedSearchParams = await searchParams;
  const deviceId = pickSearchParam(resolvedSearchParams.device_id);
  return <ReportPageClient scanId={resolvedParams.scanId} deviceId={deviceId} />;
}
