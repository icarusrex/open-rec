# OpenREC public resource hub

## Intent and scope
Build the website requested in the earlier OpenREC discussion: a Portugal-first resource for people starting, joining, or operating energy communities. The project lives at openrec.viableplanet.eu, hosted on the user's Cloudflare account, with source in website/ in icarusrex/open-rec. Use the Lazarchick palette: charcoal #111411, cream #F5F1E8, amber #EDBC54, teal #86BBAA, muted #B6B9AE.

The user explicitly requested implementation from the previous discussion. Execute in this chat. Do not reopen design approval stages. The newly pasted research report is unrelated; use primary-source verification and disclose the missing completed OpenREC report.

## Experience
Six accessible static pages: overview, Portuguese starter guide, community directory, legislation baseline, tools directory, and OpenREC project/support. Use a custom illustrated village, editorial typography, restrained motion, responsive layouts, and clear links between the visitor's next steps. Directory search combines text, geography, and category/status filters. Detail disclosures expose evidence and unknowns. JSON downloads provide reusable records. Guide progress is stored only in the browser, with graceful handling of blocked storage, reset, export, and print.

## Content contract
Every material record links directly to its primary source and records a verification date. Publication/update dates remain null when undisclosed. Keep reported status separate from independent verification. Include a curated starter set, never imply exhaustive coverage. ACC, CER, CCE, and ACI are distinct. Legislation is a manually curated baseline, not a live change-monitoring service; original acts do not prove absence of amendments. No invented savings, joining availability, certification, dates, or pricing. Link to existing EU directories without redistributing their databases.

Position OpenREC as the Apache-2.0 one-home prototype documented in the repository. Price/forecast coordination, OpenADR signaling, Home Assistant bridge and paired reporting are implemented; community onboarding, network-data imports, member statements and sharing-coefficient export are planned. Device behavior remains in Home Assistant. No claim of complete community management or independent certification.

## Architecture
No production dependencies. Node builds complete HTML from shared templates and tracked JSON; progressive enhancement adds filtering and browser-local checklist progress. Pure helper functions support meaningful tests. Generated dist is ignored, contains the six routes, 404, local assets, source JSON, sitemap and robots. Cloudflare Pages receives only dist. No accounts, forms collecting personal data, analytics, or third-party runtime scripts.

## Verification and delivery
Test combined filters, diacritics, empty results, invalid dates/links, unique records, safe rendering, checklist corruption/storage denial, and generated local links. Browser-check desktop/mobile pages, keyboard controls, detail panels, search/reset/download, checklist persistence and print. Create a draft GitHub PR through the connected GitHub plugin. Publish the tested static site on Cloudflare and attach the requested hostname if access permits. Report any unresolved domain or research gaps honestly.
