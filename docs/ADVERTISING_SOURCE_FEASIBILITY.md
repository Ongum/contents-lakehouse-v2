# Advertising source feasibility

This matrix records design intent, not confirmed collection capability. `UNKNOWN`
and `NEEDS_PROBE` mean the repository has no verified evidence for that property.

| source_name | source_type | access_method | authentication_required | artist_coverage | brand_coverage | product_coverage | campaign_coverage | creative_coverage | category_coverage | tag_coverage | historical_coverage | update_frequency | automation_stability | data_authority | expected_data_quality | rate_limit_or_access_risk | terms_or_collection_risk | recommended_role |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KOBACO AiSAC | STRUCTURED_PUBLIC_SOURCE | Public server-rendered HTML GET interface; official annual CSV/API derivative also exists | No for public archive HTML; Public Data Portal API requires application/key | AI-detected people, not commercial roles | Advertiser available; separate brand not observed | Item/product claimed by official description but not observed in sampled detail | Weak | Strong creative archive | Industry hierarchy available in official CSV; not observed in sampled detail | Strong source-native keywords and AI detections | Public UI showed 2011-2026 registration dates | Site appears ongoing; official CSV annual | HTML technically accessible but terms/access stability unsuitable for unattended collection without permission | STRUCTURED_PUBLIC_SOURCE | Strong creative metadata; weak canonical relationship authority | No published HTML rate limit; API has documented limits | AiSAC terms restrict unofficial download/capture and commercial processing | LIMITED_USE from HTML; probe the licensed Public Data Portal dataset as the preferred structured path |
| KOBACO Public Data Portal dataset 15105570 | STRUCTURED_PUBLIC_SOURCE | Full CSV download or portal-generated XML/JSON API | CSV download: no login stated; API: membership, application, and service key | None | Advertiser only; no separate brand | None | None | Title/date/duration metadata only | Three source-native industry levels | None | Not stated | Annual; next stated update 2027-06-11 | Stable government portal, but annual snapshot and no documented row ID | STRUCTURED_PUBLIC_SOURCE | Clear nine-column schema; blanks possible | API daily/per-second limits; full-file replacement semantics | KOGL Type 4: attribution, non-commercial only, no modification/derivatives | REFERENCE_ONLY; NOT_SUITABLE_FOR_PROJECT as a monetizable production dependency without separate permission |
| Official brand/company site | OFFICIAL | Public HTML or documented feed/API where available | Usually no for public pages; source-specific | Explicit named relationships only | High for own entities | Source-specific | High for stated campaign facts | Source-specific | Source-native | Source-native | Source-specific | Source-specific | Medium; layouts vary | OFFICIAL | High for statements made by the owner | Site-specific | Site-specific review required | Authoritative relationship, campaign, and date evidence |
| Official product page | OFFICIAL | Public HTML or documented product API | Usually no for public pages; source-specific | Usually none | High | High | Usually low | Usually low | High source-native category value | High source-native attributes | Current pages commonly available; history UNKNOWN | Source-specific | Medium; layouts vary | OFFICIAL | High for owned product attributes | Site-specific | Site-specific review required | Canonical product names, descriptions, source categories, and source-native tags |
| Meta Ad Library / branded-content surfaces | PLATFORM_SOURCE | API or public product surface; Korean commercial-ad coverage NEEDS_PROBE | UNKNOWN / interface-specific | NEEDS_PROBE | Potential | Potential | Partial | Potential digital creative | Low/UNKNOWN | Low/UNKNOWN | NEEDS_PROBE | UNKNOWN | NEEDS_PROBE | PLATFORM_SOURCE | NEEDS_PROBE | Access and rate behavior NEEDS_PROBE | Terms and collection scope NEEDS_PROBE | Supplementary creative/delivery evidence after a technical and terms review |
| Google News KR | NEWS_DISCOVERY | RSS search | No for current adapter | Artist-first mentions | Indirect | Indirect | Indirect | Low | Low | Keyword only | Search-index dependent | Search-index dependent | Demonstrated for small diagnostics only | MEDIA, not canonical advertising authority | Variable | Public RSS behavior may change | Search terms/service conditions apply | Legacy provisional discovery; migrate conceptually to News domain |

## KOBACO AiSAC read-only probe plan

Use one browser session and a small number of requests. Do not crawl result pages
or persist records during the probe.

1. Record the public search page URL and whether search is server-rendered, an
   XHR/fetch call, or a documented API.
2. Capture the request method, endpoint, non-secret parameters, Korean encoding,
   filters, sort order, and pagination cursor/page fields.
3. Record response media type and whether the payload is HTML, JSON, or another
   documented format.
4. Inspect one result and one detail view to identify a stable source record ID,
   detail endpoint, advertiser, product/item, industry/category, creative media
   references, dates, and source-native AI keywords for people, objects, places,
   emotions, and scenes.
5. Search separately for `RESCENE` and `리센느`; report zero results as a valid
   outcome. Do not interpret a detected person/entity as a commercial role.
6. Record the earliest/latest visible dates, total-result behavior, robots/terms
   notices, authentication gates, throttling, and request failures.
7. Classify the interface as stable public, unstable public, authenticated, or
   unsuitable. Only a stable public or documented interface should advance to a
   fixture-based adapter proposal.

The items above were the pre-probe unknowns. The result below resolves the
public HTML mechanics and sampled fields; longitudinal identifier stability,
record mutation, reliable incremental semantics, and permitted automated use
remain unknown.

## KOBACO AiSAC probe result — 2026-09-24

The bounded read-only probe used fewer than ten archive page/detail requests,
including the two required title searches. No media was downloaded and no data
was persisted.

- Search/list transport: server-rendered HTML over `GET` at
  `/site/main/advideo/list_all_top`.
- Observed parameters: `cp`, `pageSize`, `listType`, `startDate`, `endDate`,
  `kwdVal`, `kwdWhereType`, `sortOrder`, and `sortDirection`. Search fields
  support `TITLE`, `META`, and `PRODUCTION`; the form encodes type and value into
  `kwdVal`. Pagination is one-based and exposes 12 results per page by default.
- Detail transport: server-rendered HTML over `GET` at
  `/site/main/advideo/view?advId={uuid}`. No public JSON/XHR API was required or
  observed for list/detail rendering.
- Identifiers: list and detail links share a UUID `advId`. Media/image routes
  also expose a KODEX-like identifier such as `889492H01_1_26-TH-08-304`.
  Both are source-native candidates, but cross-release immutability remains
  unconfirmed. Prefer `advId` as provisional `source_record_id` and
  `source_creative_id`; retain the KODEX-like value as a secondary identifier.
- Authentication: list, search, detail, images, and video references were visible
  without login. No CAPTCHA or visible cookie requirement appeared in the small
  probe. Hidden server session behavior is unknown.
- Access controls: no blocking or throttling occurred in the small probe, but no
  public HTML rate limit was found. AiSAC terms state that archive content may not
  be downloaded/captured outside provided functions and may not be commercially
  processed. This prevents recommending an unattended HTML collector without
  explicit KOBACO permission.
- History: a 1990-2026 date query exposed 58,176 results. The last page contained
  one record dated 2011-11-18 and records dated 2017-02-02. These are presented as
  advertisement-material registration dates, not confirmed broadcast dates.
  Old records remain searchable. Record mutation behavior is unknown. New records
  appear discoverable through registration-date windows, but reliable incremental
  semantics are unconfirmed.
- RESCENE: title searches for `리센느` and `RESCENE` across the visible
  1990-01-01 through 2026-09-24 range each returned zero results. No artist
  linkage was observed for RESCENE.

One sampled detail (`advId=5e245246-c490-46ce-8c6e-c958b62f9172`) exposed an
advertisement title, material registration date, duration, advertiser, agency,
production company, source-native keywords, an AI-detected person, detected
objects, emotion analysis, frame-image routes, and a video route. It did not
show a separate brand, product/item field, industry/category, place value,
campaign identity, or authoritative artist relationship.

| Observed/source field | Availability | Canonical target | Mapping quality |
| --- | --- | --- | --- |
| `advId` UUID | AVAILABLE | `source_evidence.source_record_id`; `advertisement_creative.source_creative_id` | DIRECT, pending longitudinal stability confirmation |
| KODEX-like media path ID | AVAILABLE | Secondary source identifier / media reference | DIRECT |
| Advertisement material title | AVAILABLE | `advertisement_creative.title` | DIRECT |
| Material registration date | AVAILABLE | `source_evidence.published_at` or creative date only after semantic review | NORMALIZATION_REQUIRED |
| Duration seconds | AVAILABLE | Creative technical metadata; no current dedicated canonical field | NORMALIZATION_REQUIRED |
| Advertiser name | AVAILABLE | `advertiser_organization`; evidence/source-native name | NORMALIZATION_REQUIRED |
| Separate brand | NOT OBSERVED | `brand` | NOT_AVAILABLE |
| Product/item | NOT OBSERVED in sample; official service description claims it | `product` | WEAK until an actual field is observed |
| Industry hierarchy | NOT OBSERVED in sample; official CSV documents large/mid/small industry | `product_category.source_category_text` then governed taxonomy | NORMALIZATION_REQUIRED through the official dataset |
| Keywords | AVAILABLE | `creative_tag` | NORMALIZATION_REQUIRED |
| AI-detected person name | AVAILABLE | `creative_tag` with person/entity tag type | DIRECT as a detection; WEAK for artist identity |
| AI-detected objects | AVAILABLE | `creative_tag` | DIRECT as source-native tags |
| AI-detected places | PARTIAL: section present, no value in sample | `creative_tag` | NORMALIZATION_REQUIRED |
| Emotion analysis | AVAILABLE | `creative_tag` / creative analytical metadata | NORMALIZATION_REQUIRED |
| Frame image route | AVAILABLE | Creative media reference | DIRECT reference only |
| Video route | AVAILABLE | `advertisement_creative.media_url` | DIRECT reference only; do not copy media |
| Campaign | NOT OBSERVED | `advertising_campaign` | NOT_AVAILABLE |
| Artist commercial role | NOT OBSERVED | `campaign_artist` | NOT_AVAILABLE; person detection must not infer a role |
| Detail URL and observed HTML | AVAILABLE | `source_evidence` | DIRECT for URL/provenance; raw capture requires terms approval |

Final assessment: **LIMITED_USE** for direct AiSAC HTML collection. Creative and
AI-tag usefulness are high, advertiser metadata is useful, category/product
mapping is incomplete in the sampled interface, commercial artist linkage is
not authoritative, and terms plus undocumented rate/stability behavior prevent
classification as a stable primary collector source.

No fixture was saved because the service terms prohibit unofficial download or
capture of archive materials. The next probe should target the official Public
Data Portal dataset `15105570`, which provides an annually updated AiSAC-derived
CSV with 57,511 documented rows and a licensed API path. Its license is
attribution/non-commercial/no-derivatives, so intended lakehouse use must be
checked before ingestion.

## Public Data Portal dataset 15105570 assessment — 2026-09-24

This assessment inspected only official metadata and license documentation. The
CSV and API payload were not downloaded.

### Identity and technical access

- Provider: Korea Broadcast Advertising Corporation (`한국방송광고진흥공사`).
- Dataset: `한국방송광고진흥공사_AISAC 광고소재명별 광고 정보_20260512`.
- Stable portal dataset ID: `15105570`.
- File delivery: full CSV, listed as downloadable without login.
- API delivery: portal-generated REST API in XML or JSON; membership, an
  application, and a service key are required. The portal documents daily and
  per-second limit errors but does not state the quota on the public metadata
  page.
- Encoding: not documented; remains `UNKNOWN` until a permitted sample or file
  is obtained.
- Documented rows: 57,511. Blank values may represent personal information or
  unaggregated data.
- Update frequency: annual. Dataset registration date is 2026-06-11, metadata
  modification date is 2026-06-15, the filename carries source date 2026-05-12,
  and the next scheduled registration is 2027-06-11.
- Historical coverage: not stated. A “periodic historical data” section exists,
  but specific available versions were not confirmed from the public metadata.
- Replacement/incremental behavior: the delivery is described as a registered
  original file, not an append feed. No row-level source identifier is among the
  nine documented columns. Safe incremental ingestion is therefore not
  supported by the published contract; it would require full-version comparison
  and a provider-approved identity rule.

Documented columns are `광고소재명`, `광고소재등록일`, `광고소재초수`,
`대업종 분류`, `중업종 분류`, `소업종 분류`, `광고주명`, `광고회사명`, and
`광고제작사`.

### Blocking license decision

Both file and API listings specify Korean Open Government License Type 4:
attribution required, commercial use prohibited, and modification/derivative
works prohibited. Official KOGL guidance states that Type 4 is limited to
non-commercial use; direct or indirect use related to profit is prohibited;
format as well as content changes and derivative works are prohibited. Separate
permission may allow commercial use.

Classification: **NOT_SUITABLE_FOR_PROJECT** as a production dependency under
the published license. The project may be monetized, and canonical normalization,
entity resolution, category mapping, and Gold aggregation appear to be changes
or derivative processing. Whether a narrowly internal, non-commercial factual
index could be maintained without creating a derivative is not sufficiently
clear to rely on. Written permission or a different license from KOBACO would be
required before ingestion. Attribution alone does not cure the commercial-use
or no-derivatives restrictions. Redistribution of transformed rows or marts is
therefore not recommended.

### Canonical mapping if separately licensed

| Source field | Canonical destination | Quality |
| --- | --- | --- |
| 광고소재명 | `advertisement_creative.title` | DIRECT |
| 광고소재등록일 | `advertisement_creative.first_observed_at` or `published_at` only after semantics are confirmed | NORMALIZATION_REQUIRED |
| 광고소재초수 | Creative technical metadata; current model has no duration column | WEAK |
| 대업종 분류 | `product_category.source_category_text` / external source taxonomy level 1 | NORMALIZATION_REQUIRED |
| 중업종 분류 | External source taxonomy level 2 | NORMALIZATION_REQUIRED |
| 소업종 분류 | External source taxonomy level 3 | NORMALIZATION_REQUIRED |
| 광고주명 | Source-native organization assertion for `advertiser_organization` | NORMALIZATION_REQUIRED |
| 광고회사명 | `source_evidence` metadata or a future agency role, not advertiser/brand | WEAK |
| 광고제작사 | `source_evidence` metadata or a future production-company role | WEAK |
| Dataset ID/version/file metadata | `source_evidence` | DIRECT |

The advertiser field must not create a brand automatically. Industry levels are
a source taxonomy and must not become canonical product categories without an
explicit mapping. The dataset cannot establish `brand`, `product`, `artist`,
commercial artist role, campaign, campaign dates, creative tags, product tags,
media assets, or market. It therefore rates: creative metadata `PARTIAL`,
advertiser identity `PARTIAL`, industry/category `SUPPLEMENTARY`, and product,
artist relationship, campaign, and tags `UNSUPPORTED`.

Final source role: **REFERENCE_ONLY**. Do not collect it into production Bronze
or use it as a canonical dependency unless KOBACO grants separate permission
that covers commercial use, normalization, derived tables, and redistribution.

### Next Official Brand/Company probe contract

The next probe should use one public official company or brand newsroom and
must establish an explicit evidence chain:

```text
official source URL + source record ID + publication/observation date
    → canonical artist ID (group or person explicitly named)
    → canonical organization/brand assertion
    → controlled relationship role
    → campaign or named commercial initiative
    → announced/effective start and end dates when stated
```

Acceptance requires public read access; stable URL or native record identifier;
official ownership of the domain; explicit artist and brand names; explicit
`MODEL`, `AMBASSADOR`, `ENDORSEMENT`, `SPONSORED_CONTENT`, `COLLABORATION`, or
`EVENT_PARTNERSHIP` wording; campaign/product context; publication date; and
terms permitting internal storage, normalization, derived analytics, and the
project’s possible commercial use. Missing effective dates may remain null, but
must not be inferred from publication date. The probe must separately record
page mutability, archive/history behavior, structured metadata, pagination,
authentication, rate limits, and allowed attribution/redistribution. No
collector should be implemented until these authority and usage conditions pass.

## Official Brand/Company source probe — 2026-09-24

This bounded, read-only probe examined four public RESCENE examples. Search and
news pages were used only to locate official evidence; no article body, image,
video, or response was saved. A public page is evidence of a fact, not a license
to reproduce the page.

### Observed evidence

| Official source | Page and native identity | Explicit facts observed | Date semantics | Authority result | Collection-rights result |
| --- | --- | --- | --- | --- | --- |
| Dong-A Otsuka newsroom | Server-rendered `GET` detail, `board_content.asp?idx=672&t_name=BOARD13`; `idx=672` is a usable source-native page key | Organization `Dong-A Otsuka`; brand `Narangd Cider`; group `RESCENE`; explicit selection as brand `MODEL`; subsequent content and sales-measurement context | Publication `2026-08-27`; metric window `2026-07-21` through `2026-08-21`; advertisement published `2026-08-07`. No contract start/end stated | **HIGH** for the facts asserted by the company; verification-ready for group `MODEL` with null effective start/end | **REQUIRES_CLARIFICATION**. Public viewing is allowed, but the consumer terms do not grant automated capture, normalization, commercial reuse, or redistribution of page content |
| Domino's Korea newsroom | Server-rendered `GET` detail, `/bbs/newsView?idx=3230`; numeric `idx=3230`; archive `/bbs/newsList?type=P` | Brand `Domino's Pizza`; group `RESCENE`; explicit new brand-exclusive `MODEL`; TV commercial and new-product context | Publication `2026-07-13`; source says the commercial/product would appear on July 16. It does not state the model contract's effective start/end | **HIGH** for group `MODEL`; verification-ready with unknown effective dates | **REQUIRES_CLARIFICATION**. The public service terms and copyright notice are not an affirmative data-reuse license; keep only factual metadata unless permission is confirmed |
| MLB Korea official promotion | Public campaign/collection detail `/display/promotions/collection/1937`; numeric collection ID `1937`; HTML metadata is readable without login, while some presentation is client-rendered | Brand `MLB`; group `RESCENE`; named `26FW HEADWEAR` collection and RESCENE-led presentation | No publication date or effective campaign dates were observed | **MEDIUM**. Brand control and campaign participation are explicit, but `MODEL` or another controlled commercial role is not stated on the official page; keep at `OFFICIAL_SOURCE_FOUND` | **RESTRICTED** for copied content and commercial reuse without approval. Terms reserve site-created content and prohibit reproduction, transmission, publication, distribution, and commercial use without prior consent. Factual indexing still needs a scoped legal/terms review |
| Biodance official Kakao channel | Public brand-controlled channel post `pf.kakao.com/_xfcSTs/114258758`; post ID `114258758`; platform-hosted rather than a Biodance-owned domain | Brand `Biodance`; person `Woni` of RESCENE; explicit `AMBASSADOR`; `My First Collagen` campaign; collagen serum, mist, and mask context | No reliable exact publication date or relationship effective dates were exposed in the inspected page | **MEDIUM-HIGH** after confirming the channel is the brand's official channel; sufficient for the person-level `AMBASSADOR` assertion, not a group relationship | **REQUIRES_CLARIFICATION**. Public visibility and brand control do not grant automated archival, transformation, commercial use, or redistribution rights under the platform terms |

The first three facts concern the RESCENE group. The Biodance fact concerns
`Woni` as a person and must not be expanded to the group or other members.

### Access, archives, and repeatability

| Source pattern | Search/archive behavior | Authentication / session | Pagination and history | Automation assessment |
| --- | --- | --- | --- | --- |
| Dong-A Otsuka board | Public HTML list and detail; list exposes a search form | None observed for news pages; no cookie dependency observed in the small probe | `page` query parameter, numbered archive; historical pages remain visible | Technically simple and repeatable by list-page polling, but permission and rate policy are not published |
| Domino's newsroom | Public HTML list/detail and search form | None observed for press pages | List reports total records and uses numeric detail IDs; page/search controls are visible | Technically simple and stable enough for a source-specific adapter after rights clarification |
| MLB Korea promotions | Public promotion index/detail; promotion index offers `Load more` and the site has search | None for viewed campaign pages | Cursor/API mechanics behind `Load more` were not inspected; historical retention and mutation behavior are `UNKNOWN` | A numeric detail route is repeatable, but discovery/pagination needs a small adapter probe and commercial collection is restricted without approval |
| Official Kakao channel | Public channel/post pages, heavily platform-managed | No login required for the inspected post; cookie/session dependence for enumeration is `UNKNOWN` | Search, archive pagination, retention, and rate limits are `UNKNOWN` | Useful as manually confirmed evidence; unsuitable as the first unattended official-source adapter until platform access and terms are clarified |

No source published an API or explicit collection rate limit in the inspected
interfaces. No blocking, CAPTCHA, or authentication challenge was observed in
the bounded page reads. That does not establish permission or unattended-access
stability.

### Canonical mapping

| Official fact | Canonical destination | Mapping quality |
| --- | --- | --- |
| Company legal/operating name | `advertiser_organization` | `DIRECT` as a source assertion; entity resolution still required |
| Owned brand name | `brand` and its organization relationship | `DIRECT` when the official page identifies both; otherwise `NORMALIZATION_REQUIRED` |
| Named product or menu item | `product` and `campaign_product` | `DIRECT` when named; product/brand resolution required |
| Official source category or product wording | `product_category.source_category_text` | `NORMALIZATION_REQUIRED`; never promote automatically to the governed taxonomy |
| Explicit group/person name | canonical `artist.artist_id` through existing alias/identifier resolution | `NORMALIZATION_REQUIRED`; group and person identities stay separate |
| Explicit `MODEL` / `AMBASSADOR` wording | `campaign_artist.participation_role` | `DIRECT` after canonical artist and campaign resolution |
| Named initiative or campaign | `advertising_campaign` | `DIRECT` for the name/context, but canonical campaign identity still requires later resolution |
| Official page URL and native ID | `source_evidence.source_url` and `source_record_id` | `DIRECT` |
| Page publication date | `source_evidence.published_at` | `DIRECT`; never substitute for campaign start |
| Stated launch, measurement, or promotion dates | matching campaign, metric, or evidence date fields | `DIRECT` only for the stated semantic |
| Images, video, and page copy | external reference only | `NOT_FOR_COPYING` without a separate license or permission |

### Source decision and future Bronze boundary

Official company newsrooms are **SUITABLE_PRIMARY_AUTHORITY_SOURCES** for facts
the company explicitly asserts. Official brand campaign/product pages are
**SUITABLE_PRIMARY_AUTHORITY_SOURCES** for owned campaign and product facts but
may be insufficient for a controlled artist role. Verified official social
accounts are **SUITABLE_SUPPLEMENTARY_AUTHORITY_SOURCES** when the controlling
brand identity is established. Media reports remain discovery-only.

The reusable collector should share HTTP safety, observation timestamps, URL
normalization, hashing, create-only storage, and evidence validation. Each domain
still needs a small adapter for list discovery, pagination, native IDs, date
parsing, and factual-field extraction. Do not build one generic CSS selector or
copy full pages.

If rights are cleared, future Bronze should contain only the minimum reproducible
factual record: source name/type/domain, canonical URL, native page ID,
publication date as stated, observation time, request URL and non-secret request
metadata, content hash, short factual assertions or field-level excerpts, and
references to externally hosted media. Full copyrighted page text, images, and
video should remain outside the lakehouse unless separately licensed.

The controlled evidence path is:

```text
discovery candidate
    -> official domain/channel ownership check
    -> immutable minimal official-source observation
    -> explicit fact extraction (artist, brand, role, campaign, dates)
    -> canonical entity resolution
    -> campaign_artist plus field-level source_evidence
```

Before production collection, obtain or document permission for automated
access, internal factual storage, normalization, derived analytics, possible
commercial use, attribution, and redistribution for each domain. The next
technical probe should be the Dong-A Otsuka newsroom: it has the strongest
existing canonical example, stable numeric detail IDs, public archive pages,
and explicit organization/brand/group/role/date facts. That probe should remain
fixture-only until the rights questions are resolved.

### Fixture-tested implementation status

The first reusable framework now has fixture-tested Dong-A Otsuka and Domino
news adapters. It reuses the bounded HTTP acquisition layer, normalizes only
explicit relationship wording, validates temporal ordering and provenance, and
prepares a minimal factual Bronze envelope without writing it. Sanitized fixtures
contain only the DOM fragments and factual wording required by parser tests; they
are not archived source pages. Dong-A `idx=672` remains compatible with the
existing Narangd Silver transformation. No live official-source collection or
Domino canonical write is enabled, because the collection-rights questions above
remain unresolved.
