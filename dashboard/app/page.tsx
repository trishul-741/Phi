import { OverviewPageClient } from "../components/pages/overview-page-client";
import { pickSearchParam, type PageSearchParams } from "../lib/search-params";

export default function OverviewPage({
  searchParams,
}: {
  searchParams: Promise<PageSearchParams>;
}) {
  return (
    <OverviewPageClientWrapper searchParams={searchParams} />
  );
}

async function OverviewPageClientWrapper({
  searchParams,
}: {
  searchParams: Promise<PageSearchParams>;
}) {
  const resolvedSearchParams = await searchParams;
  const deviceId = pickSearchParam(resolvedSearchParams.device_id);
  return <OverviewPageClient deviceId={deviceId} />;
}
