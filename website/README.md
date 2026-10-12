# OpenREC website

Portugal-first public resource hub for starting energy communities. Six static pages with progressive enhancement, no production dependencies, accounts or analytics.

## Build and preview

Use Node 22 or newer:

```sh
cd website
npm test
npm run build
python3 -m http.server 4187 --directory dist --bind 127.0.0.1
```

Open http://127.0.0.1:4187/. The generated `dist/` is ignored. The test suite builds the site and checks local routes/assets, accessible structure, record identities and source links, combined search, escaping and checklist storage failures. Browser testing remains necessary for visual and interaction changes.

## Content

`data/` holds communities, legislation, tools, support resources and the starter checklist. Records have stable IDs, direct source links and a `checked_at` date. `source_published_at` and `source_updated_at` are `null` when unknown. Never substitute the research date for a source's publication date.

The E-Redes January 2026 document uses `date_precision: "month"`; its ISO ordering date must not be displayed as an exact day. Original legislation records are adoption baselines, with current consolidated provisions requiring review. This is not an automated legislation monitor or an exhaustive community register.

Add only original, sourced summaries. Do not copy third-party datasets without verified permission. Record organiser/provider-reported evidence separately from independent verification. Unknown membership, savings, registration, pricing and joining availability remain unknown. Use GitHub issues for corrections; the site does not submit those issues for visitors.

## Hosting

Deploy only `dist/` to Cloudflare Pages. The initial deployment uses direct upload:

```sh
npm run build
npx wrangler pages deploy dist --project-name openrec --branch main
```

The project must exist before upload. Confirm the deployed URL returned by Cloudflare, and configure `openrec.viableplanet.eu` under the project's custom domains. Canonical URLs and sitemap target that hostname. Future source changes require another deployment; this launch does not configure automatic production deployment or new Cloudflare credentials in GitHub.

The website GitHub workflow tests and uploads a static build artifact. It does not alter the application's Python, VTN, database or Home Assistant runtime.

## Privacy

The starter checklist stores only selected step IDs in local storage. It can be reset, downloaded or printed. Blocked storage falls back to in-memory progress. Hosting may process normal request logs. External sources open in new tabs; their own policies apply.

## Maintenance

- Before applying rules to a project, check the consolidated legislation, DGEG, ERSE and the network operator.
- Review legal and support records monthly, and before displaying an opportunity as open.
- Recheck community/provider activity quarterly, immediately when an error is reported, and before making outcome claims.
- At review, record what the source actually supports, update the date, and retain explicit unknowns.
- When a source disappears or activity cannot be established, label the uncertainty or remove the unsupported claim. Do not silently refresh the check date.

Initial evidence cutoff: 12 October 2026. The supplied Portugal report informed the expanded launch collection after primary-source verification. Corrections and excluded claims are recorded in `docs/website-research-audit.md`. The initial unrelated attachment was not used as OpenREC evidence. A larger directory and audited operating outcomes remain editorial expansion.
