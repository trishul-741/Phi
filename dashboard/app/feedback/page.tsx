import { FeedbackPageClient } from "../../components/pages/feedback-page-client";
import { pickSearchParam, type PageSearchParams } from "../../lib/search-params";

export default async function FeedbackPage({
  searchParams,
}: {
  searchParams: Promise<PageSearchParams>;
}) {
  const resolvedSearchParams = await searchParams;
  const deviceId = pickSearchParam(resolvedSearchParams.device_id);
  return <FeedbackPageClient deviceId={deviceId} />;
}
