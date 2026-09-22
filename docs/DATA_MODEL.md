# RESCENE YouTube MVP Data Model

## Scope

This model supports the current local MVP only: RESCENE, its relevant YouTube
channels and videos, hourly video metrics, and timestamped artist events used
to give metric changes context. It does not model members, releases as separate
entities, other platforms, advertising, or machine-learning features.
All timestamps in this model are stored in UTC.

## Core entities

### `artist`

One canonical row for RESCENE. Keeping an artist entity avoids embedding the
artist name in every downstream record and leaves relationships explicit.

| Column | Type | Rule |
| --- | --- | --- |
| `artist_id` | string | Primary key; stable internal ID |
| `artist_name` | string | Required canonical display name |

`artist_id` is generated internally and must not change when the display name
changes. For the MVP this table contains one row.

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

### `youtube_video`

One row per collected YouTube video.

| Column | Type | Rule |
| --- | --- | --- |
| `video_id` | string | Primary key; YouTube video ID |
| `channel_id` | string | Foreign key to `youtube_channel.channel_id` |
| `title` | string | Latest normalized video title |
| `published_at` | timestamp | YouTube publication time |
| `source_updated_at` | timestamp, nullable | Update time supplied by YouTube, when available |

Video metadata is kept once here. Changing metrics do not belong in this table.

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

A small curated table of RESCENE activities used to compare video growth before
and after an event.

| Column | Type | Rule |
| --- | --- | --- |
| `event_id` | string | Primary key; stable internal ID |
| `artist_id` | string | Foreign key to `artist.artist_id` |
| `event_at` | timestamp | Event time in UTC; use 00:00 UTC when only the date is known |
| `event_time_precision` | string | `timestamp` when time is known; `date` when only the date is known |
| `event_type` | string | Small controlled value, such as `release` or `activity` |
| `event_name` | string | Required short description |
| `source_url` | string, nullable | Evidence for the curated event |

Events are artist-level context in this milestone. No direct event-to-video
mapping is required; analysis compares `event_at` with snapshot `observed_at`.
Consumers must treat a `date`-precision event as occurring on that UTC date,
not as an exact midnight event.

## Relationships

```text
artist 1 ──< youtube_channel 1 ──< youtube_video 1 ──< video_metrics_snapshot
   │
   └──< artist_event
```

- One artist can be associated with many tracked channels.
- One channel can publish many videos; each video has exactly one channel.
- One video can have many observations per UTC date, uniquely identified by
  their actual UTC `observed_at` timestamps.
- One artist can have many events.

## Medallion ownership

| Layer | Owns | Responsibility |
| --- | --- | --- |
| Bronze | Raw YouTube API responses and raw curated event inputs | Append source payloads with ingestion timestamp, source/endpoint metadata, request context, and a reproducible object identity. Bronze is not the canonical relational model. |
| Silver | `artist`, `youtube_channel`, `youtube_video`, `video_metrics_snapshot`, `artist_event` | Parse, normalize, deduplicate, enforce the keys above, and retain lineage back to Bronze records. Silver Iceberg tables are the canonical data model. |
| Gold | Minimal analytics-ready views/tables derived from Silver, including hourly and rolling 24-hour video growth with artist, channel, and event context | Calculate count deltas from actual UTC observation times and serve DuckDB analysis incrementally. Keep reusable calculations here; do not copy raw payloads or create duplicate master data. |

Gold does not own new identities. It uses Silver primary and foreign keys so an
analytic result remains traceable through Silver to its Bronze source.
