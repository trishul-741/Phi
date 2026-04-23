import { ReviewHistoryPageClient } from "../../../components/pages/review-history-page-client";
import { pickSearchParam } from "../../../lib/search-params";

export default async function ReviewHistoryPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = searchParams ? await searchParams : undefined;
  const deviceId = pickSearchParam(params?.device_id);

  return <ReviewHistoryPageClient deviceId={deviceId} />;
}
