import { ReportByUrlPageClient } from "../../../components/pages/report-by-url-page-client";
import { pickSearchParam, type PageSearchParams } from "../../../lib/search-params";

export default async function ReportByUrlPage({
  searchParams,
}: {
  searchParams: Promise<PageSearchParams>;
}) {
  const resolvedSearchParams = await searchParams;
  const url = pickSearchParam(resolvedSearchParams.url) ?? "";
  const deviceId = pickSearchParam(resolvedSearchParams.device_id);
  return <ReportByUrlPageClient url={url} deviceId={deviceId} />;
}
