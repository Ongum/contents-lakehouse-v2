# RESCENE YouTube MVP Data Model

## Scope

This model supports the current local MVP: RESCENE, its relevant YouTube
channels and videos, hourly video metrics, and artist events used to give
metric changes context. The artist model also defines the minimal future-facing
structure needed for groups, people, historical membership, and shared events;
no external artist or event ingestion is implemented yet. Other platforms,
advertising, and machine-learning features remain out of scope. All timestamps
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

## Relationships

```text
artist (GROUP/PERSON) 1 ──< artist_external_identifier
          │
          ├──< artist_relationship >── artist (GROUP/PERSON)
          │
          ├──< event_artist >── artist_event
          │
          └──< youtube_channel 1 ──< youtube_video 1 ──< video_metrics_snapshot
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

## Medallion ownership

| Layer | Owns | Responsibility |
| --- | --- | --- |
| Bronze | Raw YouTube API responses and raw curated event inputs | Append source payloads with ingestion timestamp, source/endpoint metadata, request context, and a reproducible object identity. Bronze is not the canonical relational model. |
| Silver | `artist`, `artist_external_identifier`, `artist_relationship`, `artist_event`, `event_artist`, `youtube_channel`, `youtube_video`, `video_metrics_snapshot` | Parse, normalize, deduplicate, enforce the keys above, and retain lineage back to Bronze records. Silver Iceberg tables are the canonical data model. |
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
