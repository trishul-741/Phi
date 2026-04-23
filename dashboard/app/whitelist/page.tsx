import { WhitelistPageClient } from "../../components/pages/whitelist-page-client";
import { pickSearchParam, type PageSearchParams } from "../../lib/search-params";

export default async function WhitelistPage({
  searchParams,
}: {
  searchParams: Promise<PageSearchParams>;
}) {
  const resolvedSearchParams = await searchParams;
  const deviceId = pickSearchParam(resolvedSearchParams.device_id);
  return <WhitelistPageClient deviceId={deviceId} />;
}
