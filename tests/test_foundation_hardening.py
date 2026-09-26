import json
import io
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

if __package__:
    from .test_advertising_bronze import FakeMinioClient, StaticAdapter, config
    from .test_bronze_capture import FakeResponse
else:
    from test_advertising_bronze import FakeMinioClient, StaticAdapter, config
    from test_bronze_capture import FakeResponse
from src.advertising_bronze_storage import AdvertisingBronzeStorage
from src.advertising_collection import CollectionStatus, build_bronze_record, collect_source, content_hash
from src.advertising_silver import latest_narangd_bronze
from src.advertising_sources import NARANGD_SOURCE
from src.bronze_storage import BronzeStorage, BronzeStorageError
from src.youtube_connectivity import BronzeCapture, collect_seed_videos, fetch_video_details


class AdvertisingObservationTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeMinioClient()
        self.storage = AdvertisingBronzeStorage(self.client, 'lakehouse')

    def collect(self, text, hour, source=None):
        return collect_source(source or config(), StaticAdapter(text), self.storage,
                              run_id=f'run-{hour}', retrieved_at=f'2026-09-25T{hour:02}:00:00Z')

    def test_sequences_preserve_occurrences_and_deduplicate_content(self):
        for sequence in [('A', 'A'), ('A', 'B'), ('A', 'B', 'A')]:
            with self.subTest(sequence=sequence):
                self.setUp()
                results = [self.collect(value, index) for index, value in enumerate(sequence)]
                history = self.storage.list_source_observations(config())
                self.assertEqual([row['content_hash'] for _, row in history],
                                 [content_hash(value) for value in sequence])
                self.assertEqual(len(self.storage.list_source_versions(config())), len(set(sequence)))
                self.assertEqual(self.storage.latest_content_hash(config()), content_hash(sequence[-1]))
                if sequence == ('A', 'B', 'A'):
                    self.assertEqual(results[0].object_key, results[2].object_key)
                    self.assertTrue(results[2].content_changed)
                    self.assertFalse(results[2].content_created)
                    self.assertEqual(results[2].record['observation']['previous_content_hash'], content_hash('B'))
                if sequence == ('A', 'A'):
                    self.assertEqual(results[-1].status, CollectionStatus.UNCHANGED)
                for key, _ in history:
                    observation = self.storage.read_record(key)
                    self.assertNotIn('raw_content', observation)
                    self.assertNotIn('raw_content_bytes_base64', observation)
                    self.assertIn('request_metadata', observation)

    def test_same_observation_replay_is_idempotent_and_conflicts_are_retained(self):
        first = self.collect('A', 1)
        self.collect('B', 2)
        before = dict(self.client.objects)
        replay = self.collect('A', 1)
        self.assertEqual(first.observation_key, replay.observation_key)
        self.assertEqual(self.client.objects, before)
        self.assertEqual(self.storage.latest_content_hash(config()), content_hash('B'))
        conflict = self.collect('B', 1)
        self.assertEqual(conflict.status, CollectionStatus.QUARANTINED)
        self.assertEqual(self.client.objects, before)

    def test_latest_reader_uses_observations_even_when_content_reverts(self):
        self.collect('A', 1, NARANGD_SOURCE)
        self.collect('B', 2, NARANGD_SOURCE)
        last = self.collect('A', 3, NARANGD_SOURCE)
        self.collect('C', 0, NARANGD_SOURCE)
        reference, record = latest_narangd_bronze(self.storage)
        self.assertEqual(reference, last.object_key)
        self.assertEqual(record['raw_content'], 'A')
        self.assertEqual(record['observation_reference'], last.observation_key)
        self.assertEqual(record['observation']['run_id'], 'run-3')
        self.assertEqual(record['run_id'], 'run-1')

    def test_repeated_content_keeps_original_silver_provenance_and_timestamps(self):
        from src.advertising_silver import transform_advertising_bronze
        content = (Path(__file__).parent / 'fixtures' /
                   'advertising_official_donga_672.html').read_text(encoding='utf-8')
        first = self.collect(content, 1, NARANGD_SOURCE)
        second = self.collect(content, 2, NARANGD_SOURCE)
        raw = self.storage.read_record(first.object_key)
        _, latest = latest_narangd_bronze(self.storage)
        for record in (second.record, latest):
            for name, value in raw.items():
                self.assertEqual(record[name], value, name)
            self.assertEqual(record['observation']['run_id'], 'run-2')
            before = transform_advertising_bronze(first.object_key, raw)
            after = transform_advertising_bronze(first.object_key, record)
            self.assertFalse(before.invalid_records)
            self.assertEqual(before, after)

    def test_recovery_rejects_corrupted_referenced_content(self):
        first = self.collect('A', 1)
        record = self.storage.read_record(first.object_key)
        corrupted = dict(record, raw_content='corrupted')
        self.client.objects[('lakehouse', first.object_key)] = json.dumps(corrupted).encode()
        record['run_id'] = 'recovery'
        with self.assertRaises(BronzeStorageError):
            self.storage.write_observation(record, first.object_key)

    def test_legacy_content_is_read_without_migration(self):
        record = build_bronze_record(config(), StaticAdapter('legacy').fetch(config()),
                                    'legacy', '2026-09-25T00:00:00Z', None)
        key, _ = self.storage.write_version(record)
        before = self.client.objects[('lakehouse', key)]
        self.assertEqual(self.storage.latest_content_hash(config()), content_hash('legacy'))
        self.collect('new', 1)
        self.assertEqual(len(self.storage.list_source_observations(config())), 2)
        self.assertEqual(self.client.objects[('lakehouse', key)], before)

    def test_content_without_observation_is_recoverable_but_not_latest_state(self):
        original = self.client._put_object

        def fail_observation(bucket, key, data, headers):
            if '/observations/' in key:
                raise OSError('storage unavailable')
            return original(bucket, key, data, headers)

        with patch.object(self.client, '_put_object', side_effect=fail_observation):
            failed = self.collect('A', 1)
        self.assertEqual(failed.status, CollectionStatus.RETRYABLE_FAILURE)
        self.assertEqual(len(self.storage.list_source_versions(config())), 1)
        self.assertIsNone(self.storage.latest_content_hash(config()))
        self.collect('A', 1)
        self.assertEqual(len(self.storage.list_source_observations(config())), 1)

    def test_timezone_and_fractional_seconds_order(self):
        for value, timestamp in [('B', '2026-09-25T00:00:00.100Z'),
                                 ('A', '2026-09-25T09:00:00+09:00')]:
            collect_source(config(), StaticAdapter(value), self.storage,
                           run_id=value, retrieved_at=timestamp)
        self.assertEqual(self.storage.latest_content_hash(config()), content_hash('B'))

    def test_additive_contract_works_with_mocked_gcs_generation_guards(self):
        if __package__:
            from .test_gcs_storage import _Client
        else:
            from test_gcs_storage import _Client
        from src.gcs_storage import GCSClientAdapter
        client = _Client()
        self.storage = AdvertisingBronzeStorage(GCSClientAdapter(client, 'project'), 'bucket')
        for index, value in enumerate(('A', 'B', 'A')):
            self.collect(value, index)
        self.assertEqual(len(self.storage.list_source_observations(config())), 3)
        self.assertEqual(len(self.storage.list_source_versions(config())), 2)
        self.assertEqual(set(client.preconditions), {0})


def video(video_id):
    return {'id': video_id, 'snippet': {'channelId': 'channel', 'title': video_id,
            'publishedAt': '2026-01-01T00:00:00Z'}, 'statistics': {'viewCount': '10'}}


class YouTubeIsolationTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeMinioClient()
        # YouTube raw storage uses the public client operation.
        self.client.put_object = lambda bucket, key, data, length, content_type: (
            self.client._put_object(bucket, key, data.read(length), {}))
        self.storage = BronzeStorage(self.client, 'lakehouse')
        self.capture = BronzeCapture(run_id='run-1', observed_at='2026-09-25T00:00:00Z',
                                     record_sink=self.storage.write_record,
                                     failure_sink=self.storage.write_failure)

    def failures(self):
        return [row for _, row in self.storage.list_records(prefix='failures/youtube/')]

    @patch('src.youtube_connectivity.urlopen')
    def test_missing_and_malformed_items_do_not_discard_successful_items(self, request):
        malformed = video('bad')
        malformed['statistics'] = None
        payload = {'items': [video('good'), malformed, video('later')]}
        request.return_value = FakeResponse(payload)
        result = fetch_video_details('secret', ['missing', 'good', 'bad', 'later'],
                                     self.capture.observed_at, self.capture)
        self.assertEqual([row['video_id'] for row in result], ['good', 'later'])
        self.assertEqual({row['error_type'] for row in self.failures()},
                         {'invalid_video', 'unavailable_video'})
        self.assertEqual(self.storage.list_records()[0][1]['raw_payload'], payload)
        for failure in self.failures():
            self.assertTrue(failure['payload_reference'].startswith('bronze/youtube/'))
            self.assertEqual(failure['run_id'], 'run-1')
        self.assertNotIn('secret', json.dumps(self.failures()))

    @patch('src.youtube_connectivity.urlopen')
    def test_failed_batch_still_collects_later_batch(self, request):
        request.side_effect = [HTTPError('url', 503, 'unavailable', {}, None),
                               FakeResponse({'items': [video('video-50')]})]
        result = fetch_video_details('secret', [f'video-{i}' for i in range(51)],
                                     self.capture.observed_at, self.capture)
        self.assertEqual([row['video_id'] for row in result], ['video-50'])
        self.assertEqual(len(self.storage.list_records()), 1)
        failure = self.failures()[0]
        self.assertEqual(failure['status'], 'retryable')
        self.assertEqual(failure['http_status'], 503)
        self.assertEqual(len(failure['request_context']['id'].split(',')), 50)
        self.assertIsNone(failure['payload_reference'])

    @patch('src.youtube_connectivity.urlopen')
    def test_failed_channel_still_collects_next_channel(self, request):
        request.side_effect = [HTTPError('url', 503, 'unavailable', {}, None),
            FakeResponse({'items': [{'id': 'channel', 'snippet': {'title': 'Channel'},
                'contentDetails': {'relatedPlaylists': {'uploads': 'uploads'}}}]}),
            FakeResponse({'items': [{'contentDetails': {'videoId': 'good'}}]}),
            FakeResponse({'items': [video('good')]})]
        result = collect_seed_videos('secret', self.capture)
        self.assertEqual([row['video_id'] for row in result], ['good'])
        self.assertEqual(len(self.storage.list_records()), 3)
        self.assertEqual(self.failures()[0]['resource'], 'channels')

    @patch('src.youtube_connectivity.urlopen')
    def test_failed_video_batch_does_not_stop_later_channel(self, request):
        channel = {'items': [{'id': 'channel', 'snippet': {'title': 'Channel'},
                   'contentDetails': {'relatedPlaylists': {'uploads': 'uploads'}}}]}
        playlist = {'items': [{'contentDetails': {'videoId': 'good'}}]}
        second_channel = {'items': [{'id': 'channel-2', 'snippet': {'title': 'Second'},
                          'contentDetails': {'relatedPlaylists': {'uploads': 'uploads-2'}}}]}
        request.side_effect = [FakeResponse(channel), FakeResponse(playlist),
            HTTPError('url', 503, 'unavailable', {}, None),
            FakeResponse(second_channel), FakeResponse(playlist), FakeResponse({'items': [video('good')]})]
        result = collect_seed_videos('secret', self.capture)
        self.assertEqual([row['video_id'] for row in result], ['good'])
        self.assertEqual(len(self.storage.list_records()), 5)
        self.assertEqual(len(self.failures()), 1)

    @patch('src.youtube_connectivity.urlopen')
    def test_malformed_batch_is_preserved_and_later_batch_continues(self, request):
        request.side_effect = [FakeResponse({'items': None}),
                               FakeResponse({'items': [video('video-50')]})]
        result = fetch_video_details('secret', [f'video-{i}' for i in range(51)],
                                     self.capture.observed_at, self.capture)
        self.assertEqual([row['video_id'] for row in result], ['video-50'])
        self.assertEqual(len(self.storage.list_records()), 2)
        failure = self.failures()[0]
        self.assertEqual(failure['error_type'], 'invalid_response')
        self.assertIsNone(self.storage.read_record(failure['payload_reference'])['raw_payload']['items'])

    @patch('src.youtube_connectivity.urlopen')
    def test_failed_playlist_page_keeps_already_discovered_ids(self, request):
        from src.youtube_connectivity import discover_video_ids
        request.side_effect = [FakeResponse({'items': [{'contentDetails': {'videoId': 'good'}}],
                                            'nextPageToken': 'page-2'}),
                               HTTPError('url', 503, 'unavailable', {}, None)]
        self.assertEqual(discover_video_ids('secret', 'uploads', self.capture), ['good'])
        self.assertEqual(self.failures()[0]['request_context']['pageToken'], 'page-2')

    def test_failure_record_replay_does_not_duplicate_and_storage_failure_is_fatal(self):
        self.capture.fail('videos', {'id': 'missing'}, 'unavailable_video', 'Unavailable video.')
        count = len(self.client.objects)
        self.storage.write_failure(self.capture.failures[0])
        self.assertEqual(len(self.client.objects), count)
        with patch.object(self.client, '_put_object', side_effect=OSError('unavailable')):
            with self.assertRaises(BronzeStorageError):
                self.capture.fail('videos', {'id': 'other'}, 'unavailable_video', 'Unavailable video.')

    @patch('src.youtube_connectivity.urlopen')
    def test_repeated_request_failure_does_not_reference_an_earlier_response(self, request):
        request.side_effect = [FakeResponse({'items': [video('good')]}),
                               HTTPError('url', 503, 'unavailable', {}, None)]
        fetch_video_details('secret', ['good'], self.capture.observed_at, self.capture)
        fetch_video_details('secret', ['good'], self.capture.observed_at, self.capture)
        self.assertIsNone(self.failures()[0]['payload_reference'])

    @patch('src.youtube_connectivity.urlopen')
    def test_undecodable_batch_response_does_not_stop_later_batch(self, request):
        request.side_effect = [io.BytesIO(b'\xff'),
                               FakeResponse({'items': [video('video-50')]})]
        result = fetch_video_details('secret', [f'video-{i}' for i in range(51)],
                                     self.capture.observed_at, self.capture)
        self.assertEqual([row['video_id'] for row in result], ['video-50'])
        self.assertEqual(self.failures()[0]['cause_type'], 'UnicodeDecodeError')

    @patch('src.youtube_connectivity.urlopen')
    def test_timestamp_overflow_is_isolated_to_video(self, request):
        invalid = video('bad')
        invalid['snippet']['publishedAt'] = '0001-01-01T00:00:00+01:00'
        request.return_value = FakeResponse({'items': [invalid, video('good')]})
        result = fetch_video_details('secret', ['bad', 'good'], self.capture.observed_at, self.capture)
        self.assertEqual([row['video_id'] for row in result], ['good'])
        self.assertEqual(self.failures()[0]['video_id'], 'bad')


if __name__ == '__main__':
    unittest.main()
