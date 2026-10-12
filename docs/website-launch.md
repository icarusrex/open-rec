# OpenREC website launch record

## Scope
Six static pages in `website/`, using the charcoal, cream, amber and teal palette from lazarchick.com. Public resources lead the experience; the software is accurately described as a one-home prototype. Directory source data is downloadable JSON.

## Evidence limitations
The first attachment covered unrelated global topics. The subsequent Portugal report was integrated after checking its claims against primary sources. The launch set contains nine community/cooperative examples (seven Portuguese), nine tools/services, six legal/guidance records, eight resources and two case studies. It is explicitly a starter set. The 2026 amendment, SANJOTEC, AIA, Vila Verde and Miranda do Douro were added. See `website-research-audit.md` for corrections.

The policy page is a manually curated baseline. It does not continuously detect amendments. Full current-consolidated-law analysis, a 10–15-record Portuguese community directory, independently audited operating outcomes and a comprehensive open-funding-call database remain editorial work. The site links existing official directories instead of copying their datasets.

## Verification
- Eight website tests passed: generated routes/local links, source record validity, accent-insensitive combined search, empty results, escaping and malformed/blocked storage.
- Desktop home inspected at the default browser viewport.
- All six pages checked at a 390-pixel mobile viewport with no horizontal overflow.
- Mobile menu and navigation, tool-category filtering, community text/geography filtering, no-results/reset and source disclosure checked in browser.
- Checklist marking survived reload; progress reset was verified.
- Core content and navigation are rendered into HTML before JavaScript enhancement.
- Independent read-only review found no important reproducible code blockers and confirmed sampled primary-source claims.

## Deployment
Cloudflare Pages project: `openrec`, production branch label `main`, direct-upload deployment. Public site: https://openrec.viableplanet.eu/; fallback: https://openrec.pages.dev/. Cloudflare created the CNAME `openrec` to `openrec.pages.dev`; HTTPS returned 200 on the custom hostname. Source review: https://github.com/icarusrex/open-rec/pull/2 (draft). The existing application runtime and main branch are preserved. Future edits require explicit Pages upload; automatic deployment is not configured.
