import { parseArgs, toCsv, writeText } from "./lib.mjs";

const args = parseArgs();
const count = Number(args.count ?? 1500);
const output = args.output ?? "qa/datasets/raw/synthetic-suspicious.csv";

const brands = ["paypal", "microsoft", "apple", "google", "amazon", "netflix", "linkedin", "bank", "wallet"];
const actions = ["login", "verify", "update", "secure", "password-reset", "billing", "account", "security"];
const domains = ["example.com", "example.net", "example.org"];
const paths = ["/login", "/verify", "/account", "/security", "/billing", "/password"];

function rowAt(index) {
  if (index % 10 === 0) {
    return {
      url: `http://192.168.${Math.floor(index / 255) % 255}.${(index % 254) + 1}/login.php`,
      label: "suspicious_synthetic",
      source: "synthetic",
      category: "lexical",
      subcategory: "ip_hostname",
      should_browser_test: "false",
      should_stage2_test: "true",
      notes: "Private-IP lexical fixture; do not host or browse as phishing.",
    };
  }

  const brand = brands[index % brands.length];
  const action = actions[Math.floor(index / brands.length) % actions.length];
  const domain = domains[index % domains.length];
  const path = paths[index % paths.length];
  const glue = index % 2 === 0 ? "-" : ".";
  return {
    url: `http://${brand}${glue}${action}${glue}qa-${index}.${domain}${path}`,
    label: "suspicious_synthetic",
    source: "synthetic",
    category: "lexical",
    subcategory: brand === "bank" ? "credential_lure_terms" : "brand_impersonation",
    should_browser_test: "false",
    should_stage2_test: "true",
    notes: "Reserved-domain synthetic URL. Safe for API testing only.",
  };
}

const rows = Array.from({ length: count }, (_, index) => rowAt(index));
const headers = ["url", "label", "source", "category", "subcategory", "should_browser_test", "should_stage2_test", "notes"];
await writeText(output, `${toCsv(rows, headers)}\n`);
console.log(`Wrote ${rows.length} synthetic suspicious rows to ${output}`);
