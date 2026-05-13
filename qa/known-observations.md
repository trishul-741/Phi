# PhishGuard QA Observations

## Synthetic Sample Trial

Command sequence:

```powershell
npm run qa:generate-synthetic -- --count 12 --output qa/datasets/raw/synthetic-sample.csv
npm run qa:normalize -- --input qa/datasets/raw/synthetic-sample.csv --output qa/datasets/normalized/synthetic-sample.csv
npm run qa:batch -- --input qa/datasets/normalized/synthetic-sample.csv --workers 4 --output qa/results/jsonl/synthetic-sample.jsonl --summary qa/results/jsonl/synthetic-sample.summary.json
npm run qa:metrics -- --input qa/results/jsonl/synthetic-sample.jsonl --output qa/reports/synthetic-sample.metrics.json
npm run qa:report -- --metrics qa/reports/synthetic-sample.metrics.json --output qa/reports/synthetic-sample-report.md
```

Result:

- Total synthetic rows: 12.
- True positives: 10.
- False negatives: 2.
- Precision: 100%.
- Recall: 83.33%.
- Top reasons: `brand_impersonation`, `ip_hostname`, `whitelist_bypass`.

Observation:

The synthetic sample still produced two risky rows that ended as safe because `whitelist_bypass` fired. This is not enough data to judge production behavior, but it is a useful QA signal. During the 10k-20k evaluation, inspect every synthetic false negative where:

- `label != safe`
- `decision == safe`
- `reason == whitelist_bypass`

Potential follow-up:

- Add a stricter reserved-domain QA guard.
- Ensure SafeFilter does not bypass strong lexical evidence for `example.com`, `example.net`, and `example.org` fixtures.
- Keep broad whitelist behavior for legitimate top domains, but require no strong lexical risk before bypassing.
