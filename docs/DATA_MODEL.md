# RESCENE YouTube MVP Data Model

## Scope

This model supports the current local MVP: RESCENE, its relevant YouTube
channels and videos, hourly video metrics, and artist events used to give
metric changes context. The artist model also defines the minimal future-facing
structure needed for groups, people, historical membership, and shared events;
no external artist or event ingestion is implemented yet. Advertising Silver
supports the current Narangd evidence and normalized comparison dimensions;
other platforms and machine-learning features remain out of scope. All timestamps
in this model are stored in UTC.

## Core entities

### `artist`

One canonical row per group or person. Keeping both in the same entity provides
stable internal identities for relationships, events, and content ownership
without embedding names in downstream records.

| Column | Type | Rule |
| --- | --- | --- |
| `artist_id` | string | Primary key; stable internal ID |
| `artist_name` | string | Required canonical display name |
| `artist_type` | string | Required controlled value: `GROUP` or `PERSON` |

`artist_id` is generated internally and must not change when the display name
changes. The current YouTube MVP initially contains the RESCENE group; person
rows can be added later without changing the YouTube schema.

### `artist_external_identifier`

External identities are stored as repeatable source-specific rows rather than
columns on `artist`. This permits Wikidata, MusicBrainz, and future sources to
coexist without declaring any one source authoritative.

| Column | Type | Rule |
| --- | --- | --- |
| `artist_id` | string | Foreign key to `artist.artist_id`; part of primary key |
| `source_system` | string | Source namespace, such as `wikidata` or `musicbrainz`; part of primary key |
| `external_id` | string | Identifier assigned by that source; part of primary key |
| `source_url` | string, nullable | Human-verifiable source reference |

The composite primary key (`artist_id`, `source_system`, `external_id`) allows
multiple identifiers and preserves disagreement between sources. Resolution
and confidence rules are deferred until external ingestion is designed.

### `artist_relationship`

One row per directed, time-bounded relationship between two artists.

| Column | Type | Rule |
| --- | --- | --- |
| `relationship_id` | string | Primary key; stable internal ID |
| `from_artist_id` | string | Foreign key to `artist.artist_id` |
| `to_artist_id` | string | Foreign key to `artist.artist_id` |
| `relationship_type` | string | Required controlled value; initially supports `MEMBER_OF` |
| `start_date` | date, nullable | First known active date, when available |
| `end_date` | date, nullable | Last known active date; null means open-ended or unknown |
| `source_name` | string, nullable | Name of the supporting source |
| `source_url` | string, nullable | Human-verifiable source reference |

A membership is represented directionally as
`PERSON -> MEMBER_OF -> GROUP`. Historical changes create new or closed
relationship rows; they do not overwrite prior membership periods. Exact rules
for uncertain dates and overlapping claims should be set before ingestion.

### `youtube_channel`

One row per YouTube channel included in the RESCENE dataset.

| Column | Type | Rule |
| --- | --- | --- |
| `channel_id` | string | Primary key; YouTube channel ID |
| `artist_id` | string | Foreign key to `artist.artist_id` |
| `channel_title` | string | Latest normalized channel title |
| `is_official` | boolean | Whether this is an official RESCENE channel |
| `source_updated_at` | timestamp, nullable | Update time supplied by YouTube, when available |

The YouTube channel ID is already a stable source identifier, so an additional
surrogate key is unnecessary. `artist_id` means “tracked for this artist,” not
ownership; `is_official` distinguishes official and external channels.

**Modeling review note:** The direct `youtube_channel.artist_id` relationship
is appropriate for the current RESCENE MVP because it represents “tracked for
this artist,” not strict channel ownership. If personal artist channels,
third-party or media channels, or channels relevant to multiple artists are
introduced, a future `artist_channel_relationship` bridge may supplement or
replace this direct relationship. Possible relationship types could include
`OFFICIAL`, `PERSONAL`, `TRACKED`, or others; this taxonomy is intentionally not
finalized, and the bridge is not part of the current schema.

### `youtube_video`

One row per collected YouTube video.

| Column | Type | Rule |
| --- | --- | --- |
| `video_id` | string | Primary key; YouTube video ID |
| `channel_id` | string | Foreign key to `youtube_channel.channel_id` |
| `title` | string | Latest normalized video title |
| `description` | string, nullable | YouTube video description |
| `channel_title` | string, nullable | Channel title returned with the video |
| `tags` | array<string>, nullable | YouTube tags when supplied |
| `category_id` | string, nullable | YouTube category identifier |
| `duration` | string, nullable | Original ISO 8601 duration from YouTube |
| `caption` | boolean, nullable | Whether YouTube reports captions for the video |
| `definition` | string, nullable | YouTube definition value, such as `hd` or `sd` |
| `published_at` | timestamp | YouTube publication time |
| `source_updated_at` | timestamp, nullable | Update time supplied by YouTube, when available |

Video metadata is kept once here. Changing metrics do not belong in this table.
`category_id` is YouTube's source taxonomy and is not an analytical
`content_type`. A future `content_type` could classify videos as music videos,
Shorts, dance practices, behind-the-scenes content, and similar formats, but
that classification is not part of this milestone.

### `video_metrics_snapshot`

One row per video observation. Collection runs hourly by default, but the table
stores the actual observation time so delayed runs and multiple observations in
one UTC calendar day are preserved.

| Column | Type | Rule |
| --- | --- | --- |
| `video_id` | string | Foreign key to `youtube_video.video_id`; part of primary key |
| `observed_at` | timestamp | Actual UTC collection time; part of primary key |
| `view_count` | bigint | Non-negative cumulative count |
| `like_count` | bigint, nullable | Non-negative cumulative count when exposed by YouTube |
| `comment_count` | bigint, nullable | Non-negative cumulative count when exposed by YouTube |

The composite primary key (`video_id`, `observed_at`) uniquely identifies an
observation without rounding it to an hourly boundary. A retry of the same
observation upserts that row, while a later observation is retained. Nullable
counts distinguish an unavailable value from a real zero.

### `artist_event`

One canonical row per activity or occurrence. Artist participation is stored
separately so one event can be shared without duplication.

| Column | Type | Rule |
| --- | --- | --- |
| `event_id` | string | Primary key; stable internal ID |
| `event_type` | string | Required event category |
| `event_name` | string | Required short description |
| `start_at` | timestamp, nullable | UTC start timestamp or normalized date boundary when known |
| `start_precision` | string, nullable | `timestamp` or `date`; null when start is unknown |
| `end_at` | timestamp, nullable | UTC end timestamp or normalized date boundary when known |
| `end_precision` | string, nullable | `timestamp` or `date`; null when end is unknown |
| `source_name` | string, nullable | Name of the supporting source |
| `source_url` | string, nullable | Human-verifiable source reference |

Future event types may include `release`, `comeback`, `performance`, media
appearance, concert, and collaboration. These are examples, not a finalized
taxonomy. Precision fields prevent a date-only event from being interpreted as
an exact midnight occurrence.

### `event_artist`

Many-to-many link between events and participating artists.

| Column | Type | Rule |
| --- | --- | --- |
| `event_id` | string | Foreign key to `artist_event.event_id`; part of primary key |
| `artist_id` | string | Foreign key to `artist.artist_id`; part of primary key |
| `participation_role` | string, nullable | Optional role without a finalized taxonomy |

The composite primary key (`event_id`, `artist_id`) supports group-level,
person-level, and multi-artist events without copying the event row.

## Advertising Silver

`advertiser_organization`, `brand`, `product`, `advertising_campaign`,
`campaign_product`, `campaign_source`, and `campaign_market_metric` retain their
existing identities. `advertising_campaign.relationship_type` is nullable for
backward compatibility; `campaign_artist.participation_role` is authoritative.
A campaign with no `campaign_artist` row is a valid non-artist campaign.

`product_category` is a versioned hierarchy keyed by `category_id`, with required
`category_name`, `taxonomy_name`, and `taxonomy_version`, nullable
`parent_category_id`, and nullable source evidence in `source_category_text`.
`product_category_assignment` links products to categories. Tags use independent
`product_tag` and `product_tag_assignment` tables and do not participate in the
category hierarchy.

`market` is a hierarchy keyed by `market_id`, with unique governed `market_code`,
`market_name`, `market_type`, and nullable `parent_market_id`. `campaign_market`
records campaign coverage. Nullable `campaign_market_metric.market_id` records
the geography supported for that measurement. Metrics also carry nullable
`measurement_period_precision` and `comparison_period_precision`; unknown values
remain null. Campaign dates describe campaign existence, measurement and
comparison dates describe metric periods, and `observed_at` records when the
pipeline observed the evidence.

The Narangd/RESCENE campaign keeps its existing campaign ID and legacy `MODEL`
value. The current source does not assign a normalized category, tag, market, or
business-period date, so those relationships remain absent or null.

### Advertising table grains

| Table | Grain and purpose |
| --- | --- |
| `advertiser_organization` | One canonical legal or operating organization; it may own many brands. |
| `brand` | One canonical brand, optionally linked to its organization. |
| `product` | One canonical product under a brand; source-native category text remains evidence. |
| `product_category` | One node in one named/versioned hierarchical taxonomy. |
| `product_category_assignment` | One product/category association. |
| `product_tag` | One normalized, typed product attribute/tag, separate from category hierarchy. |
| `product_tag_assignment` | One product/tag association with nullable evidence and observation time for compatibility. |
| `advertising_campaign` | One resolved commercial campaign; artist, product, market, metric, and creative relationships are optional. |
| `campaign_brand` | One canonical campaign/brand association, keyed by (`campaign_id`, `brand_id`). |
| `advertisement_creative` | One source creative identifier; campaign, brand, and product may remain unresolved and media stays external. |
| `creative_tag` | One source-native or normalized creative descriptor such as scene/object/mood, not a product attribute. |
| `creative_tag_assignment` | One creative/tag observation supported by evidence. |
| `campaign_artist` | One explicit artist participation in one campaign; group and member rows are independent facts. |
| `campaign_product` | One campaign/product association. |
| `market` | One governed country, region, or global node. |
| `campaign_market` | One campaign/market association. |
| `campaign_source` | Legacy campaign-specific lineage retained for existing records. |
| `campaign_market_metric` | One observed metric for a nullable campaign/product/market and explicit periods; metrics are optional. |
| `source_evidence` | One immutable source observation identified independently of canonical entities. |
| `canonical_field_evidence` | One source assertion for one important entity field, including asserted and selected values. |

`advertisement_creative` is distinct from `advertising_campaign`: a campaign can
have many creatives, and an unresolved creative can exist without a campaign.
Organization, brand, and product identities are also distinct. AI-detected
creative keywords remain creative tags unless separate evidence supports a
product attribute.

Allowed artist roles are `MODEL`, `AMBASSADOR`, `ENDORSEMENT`,
`SPONSORED_CONTENT`, `COLLABORATION`, and `EVENT_PARTNERSHIP`. Generic keywords
do not create these relationships.

### Evidence, resolution, conflicts, and quality

`source_evidence` records source name/type, URL and native record identifier,
collection/publication times, content hash, authority level, immutable Bronze
reference, and verification status. Authority levels are `OFFICIAL`,
`STRUCTURED_PUBLIC_SOURCE`, `PLATFORM_SOURCE`, and `DERIVED`; they are labels,
not numerical confidence scores.

`canonical_field_evidence` links brand, product, category, participation role,
and campaign date values to assertions. Multiple assertions are retained.
`is_selected` and `selection_reason` explain the chosen value; differing values
produce a downstream conflict flag rather than silent overwrite. `source_count`,
`conflicting_values`, and `conflict_flag` are derived in quality or Gold work.

Official advertising evidence ingestion separates three concerns:

```text
source acquisition (bounded HTTP fetch)
    -> source adapter (native ID, dates, explicit factual wording)
    -> normalized official-evidence contract and validation
    -> minimal factual Bronze provenance
    -> source_evidence and canonical_field_evidence
    -> supported canonical Advertising Silver entities/relationships
```

Shared code owns URL normalization, observation timestamps, factual content
hashes, evidence identity, explicit relationship normalization, validation, and
minimal provenance envelopes. Each official domain owns a small adapter for its
page structure, native identifiers, and date semantics. A page that merely shows
campaign participation retains a null relationship role. Publication dates are
never copied into relationship or campaign start dates.

Minimal factual Bronze is supported alongside the legacy full-document capture
for sources whose raw-page retention rights remain unresolved. Its proposed
content-addressed layout is
`bronze/advertising/official_brand/source=<source>/source_record_id=<id>/content_hash=<hash>/evidence.json`.
The payload contains normalized factual evidence and provenance, not full page
HTML, images, scripts, cookies, or media. Preparation is implemented; this
milestone performs no production write or live Iceberg migration.

The fixture-driven canonical transform now completes this path for the Dong-A
and Domino adapters. Resolution uses explicit alias mappings only: unknown
artists, brands, organizations, products, and markets remain `UNRESOLVED` and do
not create placeholder entities. Dong-A `idx=672` retains the legacy Narangd
campaign ID. A new campaign with an explicit source campaign name uses a stable
brand-plus-campaign-name identity, so its ID is not coupled to the participating
artist. `campaign_brand` stores the canonical many-to-many campaign/brand
relationship. The corresponding `canonical_field_evidence` assertion remains as
provenance explaining why the relationship is selected; it is no longer used as
the business join itself.

The pure `gold_artist_commercial_intelligence` projection uses one row per
artist × campaign relationship × product × market. When product or market is
unresolved it emits one row with the corresponding value null and sets
`unresolved_flag=true`; it never creates an `UNKNOWN` dimension entity or drops
the valid commercial relationship. `has_official_evidence` is true only when the
projection can trace the input batch to `source_evidence`.

Resolution proceeds through normalized exact identifier/name, source identifier,
explicit alias, deterministic contextual matching, then unresolved/manual review.
Fuzzy similarity alone never merges entities. Source-native names remain in
evidence or future explicit alias mappings.

Quality findings use `ERROR`, `WARNING`, or `UNRESOLVED`. Errors cover duplicate
source records, invalid foreign keys, hierarchy cycles, bad date order,
unsupported roles, invalid market codes, duplicate source IDs, and orphan
assignments. Warnings cover possible duplicate canonical products and conflicting
assertions. Unresolved findings cover brand/product resolution and verified facts
without evidence. Existing Narangd `campaign_source` lineage stays readable while
it is incrementally mapped to `source_evidence`.

### Advertising Gold contracts

`gold_artist_commercial_intelligence` has one row per
`artist_id × campaign/commercial relationship × product × market`. Null product
or market can represent unresolved dimensions; multiple values are never packed
into strings. It includes organization/brand/product/category dimensions,
relationship and campaign dates, creative/platform/tag/source counts, evidence
flags, conflict/unresolved flags, and first/last observation times.

Supporting contracts are `gold_product_tag_profile` at one product × tag and
`gold_campaign_creative_summary` at one campaign × platform. These marts are
designs only and are not created in this task.

Conceptual examples, not inserted facts: RESCENE → Domino Pizza →
product/category → MODEL → KR; Woni → Biodance → skincare/face mask →
AMBASSADOR → KR. An individual relationship does not imply a group relationship,
or the reverse.

```text
advertiser_organization 1--* brand 1--* product
                                  |        |--* product_category_assignment *--1 product_category
                                  |        `--* product_tag_assignment *--1 product_tag
                                  `--* campaign_brand *-- advertising_campaign
                                                               |--* campaign_artist *--1 artist
                                                               |--* campaign_product *--1 product
                                                               |--* campaign_market *--1 market
                                                               |--* advertisement_creative
                                                               |--* campaign_market_metric
                                                               `--* campaign_source (legacy)
source_evidence 1--* canonical_field_evidence *--1 canonical entity/field
source_evidence 1--* advertisement_creative
source_evidence 1--* creative_tag_assignment *--1 creative_tag
```

Canonical relationship tables (`campaign_brand`, `campaign_artist`,
`campaign_product`, and `campaign_market`) are the business truth model.
`source_evidence` and `canonical_field_evidence` explain the assertions supporting
those relationships and must not substitute for them.

## Advertising discovery staging

KR-only discovery evidence is captured immutably under
`bronze/advertising_discovery/`, separate from verified advertising Bronze.
Provisional rows are deduplicated by discovery source and normalized source URL
in `staging.advertising_campaign_candidate`. They remain outside canonical
Silver and cannot create advertiser, product, campaign, or artist entities.
Nullable `discovered_for_artist_id` records which canonical watchlist artist
caused discovery; it is not evidence of commercial participation and never
creates a `campaign_artist` row.

The candidate key identifies one discovery evidence URL, not one canonical
campaign. Different article URLs about the same apparent commercial relationship
remain separate candidates. A future verification and entity-resolution step may
link them to one canonical campaign; discovery persistence does not perform that
merge.

Candidate evidence status supports only `DISCOVERED`, `OFFICIAL_SOURCE_FOUND`,
`VERIFIED`, and `REJECTED`, with forward transitions through official evidence
or rejection. The current implementation creates discovery candidates and
validates lifecycle transitions; it does not search for official sources or
verify candidates automatically.

Official evidence is represented separately from the candidate by a deterministic
`official_evidence_id`, `candidate_id`, normalized official URL and domain,
controlled source type, discovery time, status, and reason. Official domains must
be explicitly allowlisted; news/search, blog, and repost URLs do not qualify.
Evidence records are currently validated in memory only and are not persisted.

Artist-first discovery configuration lives outside the artist master and joins
to canonical `artist` rows by `artist_id`. Canonical name and `GROUP`/`PERSON`
type come from `artist`; the configuration contains only discovery enablement,
priority, and Korean/English query aliases. Query templates must include an
artist placeholder, are KR-only, and require an artist mention near an explicit
commercial-intent signal before a candidate is retained. RESCENE is the only
initially configured artist.

The Google News candidate path is legacy/provisional Advertising discovery.
Persisted candidates remain staging data and never become canonical facts
automatically. A future News domain should model one article per publisher URL
with artist linkage, publisher, published/observed timestamps, language, body
reference, topics/tags, entities, and optional later sentiment. Candidate data
can then be migrated or referenced without deletion. Proposed News marts are
`gold_artist_news_hourly` and `gold_artist_news_daily`.

Migration is additive: existing Advertising tables remain; `product_tag` and
`product_tag_assignment` gain nullable columns; new creative, evidence, and
field-evidence tables are defined; and `campaign_source` remains the legacy
lineage contract. Discovery tables remain readable but are deprecated as an
Advertising source. This milestone performs no live Iceberg migration.

## Artist activity timeline

`artist_activity_timeline` is an additive Silver integration projection. It
does not replace or merge the YouTube, artist/event, or Advertising business
models. Its grain is one canonical artist × one supported source-domain
temporal fact. `timeline_event_id` is deterministic from `artist_id`, source
domain, source entity type and ID, and event type; a corrected time updates the
same logical event rather than creating a second identity. The UUID5 input is a
canonical compact JSON array of those components, so delimiter characters
inside an existing ID or event type cannot make two component tuples identical.

| Column | Type | Rule |
| --- | --- | --- |
| `timeline_event_id` | string | Primary key; deterministic projection identity |
| `artist_id` | string | Foreign key to canonical `artist.artist_id` |
| `event_type` | string | Source-supported fact such as `VIDEO_PUBLISHED`, an existing `artist_event.event_type`, or a supported Advertising event |
| `event_name` | string | Human-readable source-domain label |
| `event_at` | timestamp | UTC value; date-only facts use the UTC day boundary and must be read with `temporal_precision` |
| `temporal_precision` | string | `TIMESTAMP` or `DATE` |
| `time_semantics` | string | `EVENT_TIME`, `PUBLICATION_TIME`, or `EFFECTIVE_TIME` |
| `observed_at` | timestamp, nullable | When the pipeline first observed the supporting record when available; distinct from `event_at` |
| `source_domain` | string | `YOUTUBE`, `ARTIST_EVENT`, or `ADVERTISING` |
| `source_entity_type` | string | Type of canonical/source entity referenced by the event |
| `source_entity_id` | string | Existing canonical or source identity; no display-name identity |
| `source_reference` | string, nullable | Bronze object or human-verifiable source URL when available |

`artist_activity_timeline_evidence` has one row per
(`timeline_event_id`, `source_evidence_id`) and preserves zero-to-many official
Advertising evidence links without using provenance as a business join.

The source projections are deliberately narrow:

- YouTube produces `VIDEO_PUBLISHED` from exact `youtube_video.published_at`;
  the earliest available metric observation is retained separately as
  `observed_at`.
- `artist_event` rows preserve their existing event type and declared
  `DATE`/`TIMESTAMP` precision through `event_artist`.
- Advertising produces campaign announcement (`EVENT_TIME`) and campaign start
  or end (`EFFECTIVE_TIME`) facts only from the corresponding canonical fields.
  An official evidence publication date produces a separate
  `OFFICIAL_EVIDENCE_PUBLISHED` fact and never becomes a campaign or
  relationship effective date.

Rows with no supported event time are not projected. Unknown optional
provenance and observation values remain null; no `UNKNOWN` dimension entity is
created. The projection is suitable for later event-window analysis, but M04
does not calculate windows, correlations, or causal effects.

## Relationships

```text
artist (GROUP/PERSON) 1 ──< artist_external_identifier
          │
          ├──< artist_relationship >── artist (GROUP/PERSON)
          │
          ├──< event_artist >── artist_event
          │
          ├──< youtube_channel 1 ──< youtube_video 1 ──< video_metrics_snapshot
          │
          └──< artist_activity_timeline ──< artist_activity_timeline_evidence
```

- Artists can be related to other artists over explicit historical periods.
- An event can involve one group, one person, or multiple artists through
  `event_artist`.
- One artist can be associated with many tracked channels; the existing
  `youtube_channel.artist_id` can reference either a group or person.
- One channel can publish many videos; each video has exactly one channel.
- One video can have many observations per UTC date, uniquely identified by
  their actual UTC `observed_at` timestamps.

Later time-series analysis can join a video's channel to an artist, expand
group/person context through `artist_relationship`, and compare metric
observations with participating events through `event_artist`. No direct
event-to-video foreign key is required for the current design.

## Advertising Bronze collection observations

The existing content-version key and all canonical Silver IDs remain unchanged.
Each successful document collection also writes a small immutable observation at
`bronze/advertising/<source_type>/source_id=<digest>/observations/<id>.json`.

- Observation identity is SHA-256 of the JSON tuple `(source_type,
  source_identifier, run_id, normalized UTC retrieved_at)`. Replaying the same
  occurrence must reuse its run/time and factual observation metadata; conflicting
  content or metadata at that identity is quarantined rather than overwritten.
- `content_reference` points to the existing content-addressed document.
  Observation metadata retains source identity/URL/name, publication date,
  collector version, request metadata, and observed text/byte hashes, but no
  duplicate full payload. Source-specific normalization can still ignore a
  volatile page counter; hashes identify that occurrence's fetched representation,
  while the content reference retains the first full representation of that version.
- Ordered observations reconstruct repeats and reversions. Previous content and
  change status are derived from that order, not the content object's original
  envelope. Equal timestamps use the object key as a deterministic tie-breaker;
  they do not establish physical fetch order.
- Latest readers select content by observation chronology and expose
  `observation_reference` and a separate `observation` metadata object containing
  its run, retrieval time, and derived previous-content/change values. The
  returned content envelope retains its original fields, including retrieval
  time, so existing Silver transformations do not retime content-keyed facts.
- Legacy documents supply only their original known occurrence. Newly marked
  `advertising-observation/1` documents require a completed observation write.

This is an additive Bronze contract, not a canonical entity/grain migration.
M05 remains blocked pending the remaining foundation corrections.

## Medallion ownership

| Layer | Owns | Responsibility |
| --- | --- | --- |
| Bronze | Raw source responses, discovery captures, and curated inputs | Append source payloads with ingestion timestamp, source/endpoint metadata, request context, and a reproducible object identity. Bronze is not the canonical relational model. |
| Silver | Artist, event, YouTube, Advertising, and timeline entity, relationship, and integration tables defined above | Parse, normalize, deduplicate, enforce the keys above, and retain lineage back to Bronze or official evidence. Silver Iceberg tables are the canonical data model. |
| Gold | Minimal analytics-ready views/tables derived from Silver, including hourly and rolling 24-hour video growth with artist, channel, and event context | Calculate count deltas from actual UTC observation times and serve DuckDB analysis incrementally. Keep reusable calculations here; do not copy raw payloads or create duplicate master data. |

Gold does not own new identities. It uses Silver primary and foreign keys so an
analytic result remains traceable through Silver to its Bronze source.

## Gold time-series tables

### `video_metrics_hourly`

One row per Silver observation, keyed by (`video_id`, `observed_at`). It keeps
the cumulative `view_count`, `like_count`, and `comment_count` and adds
`view_delta`, `like_delta`, and `comment_delta` relative to the previous
available observation for that video. The first observation has null deltas.
A delta is also null when either cumulative nullable metric is unavailable;
missing likes or comments are never treated as zero. Negative deltas are valid.

Despite the table name, `observed_at` is not rounded to an hourly boundary and
no missing hourly observation is synthesized.

### `video_growth_24h`

One row per Silver observation, keyed by (`video_id`, `observed_at`). It keeps
`view_count` and adds `view_delta_24h`, `like_delta_24h`,
`comment_delta_24h`, and `view_growth_rate_24h`.

For each row, the baseline is the latest real observation whose timestamp is
at or before `observed_at - 24 hours`. This supports delayed or missing hourly
collections without inventing observations. If no such baseline exists, all
24-hour metrics are null. Nullable metric deltas remain null when either side
is unavailable. View growth rate is `(current - baseline) / baseline`; it is
null when the baseline view count is zero or unavailable.

## Future content-classification data mart

Content classification may eventually be multi-label. Silver should preserve a
normalized classification representation rather than require one-hot columns
or force each video into exactly one analytical class. The classification
taxonomy is intentionally not finalized here.

A later Gold or Data Mart can pivot classifications into binary features such
as `is_short_form`, `is_official_mv`, `is_behind`, `is_performance`,
`is_dance`, `is_teaser`, and `is_vlog`. These flags are not mutually exclusive:
one video may legitimately have multiple values equal to `1` at the same time.
