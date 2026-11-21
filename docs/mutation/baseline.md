# Mutation baseline at d5cb32f

| | count |
|---|---|
| mutants checked | 4053 |
| killed | 3367 |
| survived | 682 |
| timeout | 4 |
| cli message-only survivors (not scored) | 51 |
| **score** (killed / checked, excluding cli messages) | **84.1%** |

| tests | count |
|---|---|
| required (only killer of some mutant) | 128 |
| cover (needed to kill the rest) | 32 |
| protected (marked schema_rule, or call an unattributed mutant) | 32 |
| prune: one or two kept tests kill all its mutants | 91 |
| prune (scattered): its mutants need 3+ kept tests | 127 |

Caught mutants the rerun could not attribute to a test. Every test calling their function is kept:
- `computer_history.cli.app.x_build_parser__mutmut_9`

## Tests by file

### tests/unit/test_aw_adapter.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_adapter_reports_a_stream_without_buckets_as_unavailable` | keep (required) | 1 | 35 |  |
| `test_adapter_resumes_a_little_before_its_position` | keep (required) | 1 | 141 |  |
| `test_afk_has_no_signal` | prune | 0 | 1 | `test_lone_surrogates_are_scrubbed` |
| `test_awerror_fails_the_stream_without_writing` | prune (scattered) | 0 | 247 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_fresh_db_has_full_schema`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_hard_database_errors_propagate`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_poll_reports_aw_errors`, `test_poll_keeps_outcomes_committed_before_a_failure` |
| `test_backfill_chunk_with_growing_event_reports_it_held_back` | prune (scattered) | 0 | 357 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_mixed_new_and_duplicate_batch`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_event_created_during_the_pull_counts_as_latest`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_progress_does_not_move_outside_a_batch_transaction`, `test_unreadable_event_before_the_start_fails_safe`, `test_cli_start_end_overrides` |
| `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent` | keep (cover) | 0 | 338 |  |
| `test_client_builds_read_only_get_requests` | keep (required) | 24 | 41 |  |
| `test_client_maps_404_to_none_and_failures_to_awerror` | keep (required) | 7 | 22 |  |
| `test_discovery_maps_bucket_types_to_sources` | prune (scattered) | 0 | 25 | `test_discovery_with_no_known_buckets_is_empty`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_adapter_resumes_a_little_before_its_position` |
| `test_discovery_with_no_known_buckets_is_empty` | keep (cover) | 0 | 6 |  |
| `test_empty_range_is_rejected` | keep (required) | 3 | 13 |  |
| `test_event_created_during_the_pull_counts_as_latest` | keep (required) | 3 | 97 |  |
| `test_event_straddling_the_query_start_is_never_stored_clipped` | prune (scattered) | 0 | 444 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_lone_surrogates_are_scrubbed`, `test_source_without_buckets_has_no_frontier`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_every_afk_event_is_stored` |
| `test_event_written_late_reaching_back_past_the_resume_start_is_stored` | prune (scattered) | 0 | 423 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_resumes_a_little_before_its_position`, `test_event_created_during_the_pull_counts_as_latest`, `test_every_afk_event_is_stored`, `test_fresh_db_has_full_schema` |
| `test_extract_domain[  https://www.notion.so/page  -notion.so]` | prune | 0 | 23 | `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_extract_domain[https://example.com./-example.com]` |
| `test_extract_domain[-None]` | prune (kills nothing) | 0 | 0 |  |
| `test_extract_domain[None-None]` | prune | 0 | 1 | `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]` |
| `test_extract_domain[chrome://newtab/-None]` | keep (required) | 1 | 12 |  |
| `test_extract_domain[file:///Users/brandon/notes.txt-None]` | prune | 0 | 10 | `test_extract_domain[chrome://newtab/-None]` |
| `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]` | keep (required) | 2 | 23 |  |
| `test_extract_domain[http://[::1-None]` | prune | 0 | 10 | `test_extract_domain[chrome://newtab/-None]` |
| `test_extract_domain[https://example.com./-example.com]` | keep (required) | 2 | 22 |  |
| `test_extract_domain[https://localhost:3000/-localhost]` | prune | 0 | 20 | `test_extract_domain[https://example.com./-example.com]` |
| `test_extract_domain[https://user:pw@docs.google.com/doc-docs.google.com]` | prune | 0 | 20 | `test_extract_domain[https://example.com./-example.com]` |
| `test_extract_domain[https://www.github.com/x-github.com]` | prune | 0 | 23 | `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_extract_domain[https://example.com./-example.com]` |
| `test_extract_domain[https://www2.example.com/-www2.example.com]` | prune | 0 | 20 | `test_extract_domain[https://example.com./-example.com]` |
| `test_extract_domain[not a url-None]` | prune | 0 | 10 | `test_extract_domain[chrome://newtab/-None]` |
| `test_incremental_outcome_reports_held_back_and_progress` | prune (scattered) | 0 | 485 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_missing_data_gives_empty_signal`, `test_adapter_resumes_a_little_before_its_position`, `test_event_created_during_the_pull_counts_as_latest`, `test_progress_is_min_over_buckets_and_dead_bucket_does_not_pin_it`, `test_mixed_new_and_duplicate_batch`, `test_poll_keeps_outcomes_committed_before_a_failure` |
| `test_late_arriving_event_inside_the_overlap_is_picked_up` | prune (scattered) | 0 | 453 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_event_created_during_the_pull_counts_as_latest`, `test_source_without_buckets_has_no_frontier`, `test_progress_is_min_over_buckets_and_dead_bucket_does_not_pin_it`, `test_fresh_db_has_full_schema` |
| `test_latest_event_is_held_back_older_events_ingested` | prune (scattered) | 0 | 94 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_event_created_during_the_pull_counts_as_latest`, `test_every_afk_event_is_stored` |
| `test_latest_event_settles_once_its_end_is_older_than_the_margin[119-False]` | prune | 0 | 85 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]` |
| `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]` | keep (required) | 1 | 86 |  |
| `test_latest_event_settles_once_its_end_is_older_than_the_margin[120.001-True]` | prune (scattered) | 0 | 87 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position` |
| `test_latest_event_settles_once_its_end_is_older_than_the_margin[121-True]` | prune (scattered) | 0 | 87 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position` |
| `test_lone_surrogates_are_scrubbed` | keep (required) | 3 | 39 |  |
| `test_malformed_events_are_skipped_and_negative_duration_clamped` | keep (required) | 3 | 413 |  |
| `test_missing_data_gives_empty_signal` | keep (required) | 1 | 45 |  |
| `test_non_string_fields_and_unknown_keys_go_to_extras` | keep (required) | 6 | 42 |  |
| `test_payload_is_stored_verbatim_up_to_json_round_trip` | prune (scattered) | 0 | 397 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_lone_surrogates_are_scrubbed`, `test_source_without_buckets_has_no_frontier`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_every_afk_event_is_stored` |
| `test_poll_writes_observations_and_signals` | prune (scattered) | 0 | 497 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_web_signal_domain_title_hygiene_and_extras`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_source_without_buckets_has_no_frontier`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_mixed_new_and_duplicate_batch`, `test_every_afk_event_is_stored`, `test_status_on_fresh_db`, `test_shrinking_to_half_is_allowed` |
| `test_progress_is_min_over_buckets_and_dead_bucket_does_not_pin_it` | keep (cover) | 0 | 463 |  |
| `test_progress_settles_at_held_event_and_polls_pick_up_new_events` | prune (scattered) | 0 | 488 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_event_created_during_the_pull_counts_as_latest`, `test_source_without_buckets_has_no_frontier`, `test_progress_is_min_over_buckets_and_dead_bucket_does_not_pin_it`, `test_fresh_db_has_full_schema`, `test_a_file_that_cannot_be_removed_fails_once_and_does_not_block_later_files`, `test_poll_keeps_outcomes_committed_before_a_failure` |
| `test_project_signal_accepts_stored_payload_text` | prune (scattered) | 0 | 27 | `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_web_signal_domain_title_hygiene_and_extras`, `test_shrinking_to_half_is_allowed` |
| `test_project_signal_rejects_unknown_source` | prune | 0 | 2 | `test_lone_surrogates_are_scrubbed` |
| `test_range_ending_in_the_future_stops_the_frontier_at_now` | prune (scattered) | 0 | 298 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_mixed_new_and_duplicate_batch`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_event_created_during_the_pull_counts_as_latest`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_unreadable_event_before_the_start_fails_safe` |
| `test_range_ending_in_the_future_with_a_held_event` | prune (scattered) | 0 | 303 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_mixed_new_and_duplicate_batch`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_event_created_during_the_pull_counts_as_latest`, `test_source_without_buckets_has_no_frontier`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_unreadable_event_before_the_start_fails_safe` |
| `test_range_never_stores_a_start_clipped_first_copy` | prune (scattered) | 0 | 329 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_mixed_new_and_duplicate_batch`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_event_created_during_the_pull_counts_as_latest`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_cli_start_end_overrides`, `test_every_afk_event_is_stored` |
| `test_reingesting_the_same_range_adds_nothing` | prune (scattered) | 0 | 315 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_mixed_new_and_duplicate_batch`, `test_discovery_with_no_known_buckets_is_empty`, `test_adapter_resumes_a_little_before_its_position`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_missing_data_gives_empty_signal`, `test_event_created_during_the_pull_counts_as_latest`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_progress_does_not_move_outside_a_batch_transaction`, `test_web_signal_domain_title_hygiene_and_extras` |
| `test_repeated_incremental_polls_add_nothing` | prune (scattered) | 0 | 404 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_resumes_a_little_before_its_position`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_missing_data_gives_empty_signal`, `test_event_created_during_the_pull_counts_as_latest`, `test_source_without_buckets_has_no_frontier`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_web_signal_domain_title_hygiene_and_extras`, `test_mixed_new_and_duplicate_batch`, `test_progress_is_min_over_buckets_and_dead_bucket_does_not_pin_it` |
| `test_same_event_id_in_two_buckets_are_distinct_rows` | prune (scattered) | 0 | 409 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_event_created_during_the_pull_counts_as_latest`, `test_web_signal_domain_title_hygiene_and_extras`, `test_adapter_resumes_a_little_before_its_position`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_every_afk_event_is_stored` |
| `test_source_without_buckets_has_no_frontier` | keep (required) | 1 | 13 |  |
| `test_sources_package_reexports_exactly_the_runner_and_adapter_api` | prune (kills nothing) | 0 | 0 |  |
| `test_stored_url_and_domain_come_from_the_same_sanitized_string` | prune | 0 | 56 | `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_web_signal_domain_title_hygiene_and_extras` |
| `test_superseded_event_is_settled_even_if_it_just_ended` | prune | 0 | 91 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_event_created_during_the_pull_counts_as_latest` |
| `test_text_hygiene_collapse_cap_and_empty` | prune | 0 | 44 | `test_window_signal` |
| `test_url_is_capped` | prune | 0 | 53 | `test_extract_domain[https://example.com./-example.com]`, `test_web_signal_domain_title_hygiene_and_extras` |
| `test_web_signal_domain_title_hygiene_and_extras` | keep (required) | 3 | 73 |  |
| `test_window_signal` | keep (cover) | 0 | 45 |  |

### tests/unit/test_aw_ingest_properties.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_every_afk_event_is_stored` | keep (cover) | 0 | 447 |  |
| `test_every_afk_event_is_stored_whole` | prune (scattered) | 0 | 46 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_event_created_during_the_pull_counts_as_latest`, `test_every_afk_event_is_stored` |
| `test_every_window_event_is_stored_whole` | prune (scattered) | 0 | 448 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_event_created_during_the_pull_counts_as_latest`, `test_every_afk_event_is_stored` |

### tests/unit/test_ax_text.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_a_backlog_is_listed_once_per_drain` | keep (required) | 1 | 392 |  |
| `test_a_capture_dated_after_now_is_stored_but_does_not_move_progress` | keep (required) | 1 | 387 |  |
| `test_a_crash_between_commit_and_removal_re_reads_nothing_new` | prune (scattered) | 0 | 404 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_progress_never_moves_back_to_an_older_capture`, `test_the_newest_record_is_the_last_usable_line_of_the_newest_file`, `test_mixed_new_and_duplicate_batch`, `test_a_file_that_cannot_be_removed_fails_once_and_does_not_block_later_files` |
| `test_a_file_that_cannot_be_removed_fails_once_and_does_not_block_later_files` | keep (required) | 2 | 431 |  |
| `test_a_file_with_no_usable_record_is_moved_aside_not_deleted` | prune (scattered) | 0 | 437 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_malformed_lines_and_unknown_versions_are_skipped_and_counted`, `test_a_backlog_is_listed_once_per_drain`, `test_a_set_aside_name_already_taken_gets_its_own_copy` |
| `test_a_large_backlog_is_ingested_oldest_first_in_one_poll` | prune (scattered) | 0 | 420 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_the_fixture_ingests_to_its_observations_and_signals`, `test_a_backlog_is_listed_once_per_drain`, `test_a_capture_dated_after_now_is_stored_but_does_not_move_progress` |
| `test_a_missing_spool_folder_is_nothing_to_ingest` | keep (required) | 1 | 194 |  |
| `test_a_record_failing_validation_says_why[1-not a JSON object]` | keep (required) | 3 | 5 |  |
| `test_a_record_failing_validation_says_why[line2-unknown version]` | prune | 0 | 6 | `test_a_record_failing_validation_says_why[line3-unknown version]`, `test_a_record_failing_validation_says_why[line4-unknown kind]` |
| `test_a_record_failing_validation_says_why[line3-unknown version]` | keep (cover) | 0 | 6 |  |
| `test_a_record_failing_validation_says_why[line4-unknown kind]` | keep (required) | 1 | 19 |  |
| `test_a_record_failing_validation_says_why[line5-bad id]` | keep (required) | 1 | 13 |  |
| `test_a_record_failing_validation_says_why[line6-bad captured_at]` | keep (required) | 1 | 31 |  |
| `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]` | keep (required) | 1 | 29 |  |
| `test_a_record_failing_validation_says_why[{-not JSON]` | prune | 0 | 3 | `test_a_record_failing_validation_says_why[line3-unknown version]`, `test_malformed_lines_and_unknown_versions_are_skipped_and_counted` |
| `test_a_set_aside_name_already_taken_gets_its_own_copy` | keep (required) | 10 | 273 |  |
| `test_activitywatch_down_does_not_stop_the_spool` | keep (cover) | 0 | 382 |  |
| `test_an_unlistable_spool_does_not_stop_activitywatch` | prune (scattered) | 0 | 421 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_lone_surrogates_are_scrubbed`, `test_source_without_buckets_has_no_frontier`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_poll_reports_aw_errors`, `test_cli_ingest_with_an_unlistable_spool_gives_the_spool_hint`, `test_activitywatch_down_does_not_stop_the_spool` |
| `test_an_unreadable_file_is_moved_aside_and_the_rest_ingested` | keep (required) | 28 | 422 |  |
| `test_cli_ingest_honors_the_spool_flag_and_prints_rejected_records` | keep (required) | 4 | 667 |  |
| `test_cli_ingest_reads_the_spool_beside_the_database` | keep (required) | 2 | 676 |  |
| `test_cli_ingest_with_activitywatch_down_still_stores_the_spool` | keep (protected) | 0 | 511 |  |
| `test_cli_ingest_with_an_unlistable_spool_gives_the_spool_hint` | keep (required) | 1 | 557 |  |
| `test_excluded_paused_and_resumed_records_have_no_signal` | prune (scattered) | 0 | 67 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_an_unclaimed_source_raises_its_own_error`, `test_extract_domain[chrome://newtab/-None]`, `test_utc_iso_rejects_naive_timestamps`, `test_the_newest_record_is_the_last_usable_line_of_the_newest_file`, `test_lone_surrogates_are_scrubbed`, `test_text_is_capped_at_ten_thousand_characters_and_titles_keep_theirs` |
| `test_malformed_lines_and_unknown_versions_are_skipped_and_counted` | keep (required) | 10 | 443 |  |
| `test_open_part_agent_lock_and_other_entries_are_ignored_and_left_in_place` | prune (scattered) | 0 | 368 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_progress_never_moves_back_to_an_older_capture`, `test_the_backlog_counts_finished_files_and_ignores_open_part_and_agent_lock` |
| `test_progress_never_moves_back_to_an_older_capture` | keep (cover) | 0 | 416 |  |
| `test_rebuild_reprojects_the_spool_to_identical_signals` | prune (scattered) | 0 | 438 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_a_backlog_is_listed_once_per_drain`, `test_cli_rebuild_signals_on_a_fresh_db`, `test_shrinking_to_half_is_allowed`, `test_the_newest_record_is_the_last_usable_line_of_the_newest_file`, `test_cli_rebuild_signals_allow_shrink`, `test_a_capture_dated_after_now_is_stored_but_does_not_move_progress`, `test_text_is_capped_at_ten_thousand_characters_and_titles_keep_theirs` |
| `test_text_is_capped_at_ten_thousand_characters_and_titles_keep_theirs` | keep (required) | 2 | 370 |  |
| `test_the_fixture_ingests_to_its_observations_and_signals` | keep (required) | 13 | 454 |  |
| `test_the_spool_path_is_the_flag_then_the_env_var_then_beside_the_database` | prune | 0 | 3 | `test_status_on_missing_db_does_not_create_it`, `test_status_reads_the_spool_flag` |
| `test_watch_polls_activitywatch_and_the_spool_in_one_loop` | prune (scattered) | 0 | 433 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_a_file_that_cannot_be_removed_fails_once_and_does_not_block_later_files`, `test_watch_starts_the_next_cycle_at_once_after_a_slow_one`, `test_poll_reports_aw_errors`, `test_watch_reports_every_cycle_and_sleeps_for_the_rest_of_the_interval`, `test_poll_keeps_outcomes_committed_before_a_failure`, `test_activitywatch_down_does_not_stop_the_spool` |

### tests/unit/test_backfill.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_a_failed_last_chunk_sets_no_progress` | prune (scattered) | 0 | 467 | `test_held_back_events_without_a_settled_time_make_the_chunk_incomplete`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_lone_surrogates_are_scrubbed`, `test_source_without_buckets_has_no_frontier`, `test_plan_chunks_are_fixed_width_oldest_first_from_local_midnight`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_bad_progress_updates_are_rejected[no-position]`, `test_backfill_stops_at_an_observation_from_another_stream`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_cli_backfill_mid_run_failure_keeps_committed_chunks`, `test_cli_backfill_on_a_locked_store_fails_cleanly` |
| `test_backfill_help_lists_its_flags` | keep (protected) | 0 | 52 |  |
| `test_backfill_ingests_all_history_across_chunks` | prune (scattered) | 0 | 529 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_plan_chunks_are_fixed_width_oldest_first_from_local_midnight`, `test_event_created_during_the_pull_counts_as_latest`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_cli_backfill_creates_store_prints_progress_and_totals`, `test_unreadable_event_before_the_start_fails_safe` |
| `test_cli_backfill_creates_store_prints_progress_and_totals` | keep (required) | 5 | 782 |  |
| `test_cli_backfill_mid_run_failure_keeps_committed_chunks` | keep (protected) | 0 | 701 |  |
| `test_cli_backfill_on_a_locked_store_fails_cleanly` | keep (required) | 8 | 553 |  |
| `test_cli_backfill_progress_read_failure_fails_cleanly[dry-run]` | keep (protected) | 0 | 234 |  |
| `test_cli_backfill_progress_read_failure_fails_cleanly[run]` | keep (cover) | 0 | 223 |  |
| `test_cli_backfill_reports_the_held_back_final_chunk` | keep (required) | 2 | 686 |  |
| `test_cli_backfill_rerun_inserts_nothing` | keep (required) | 1 | 818 |  |
| `test_cli_backfill_with_aw_down_creates_nothing` | keep (cover) | 0 | 120 |  |
| `test_cli_dry_run_creates_nothing_and_lists_chunks` | keep (required) | 8 | 279 |  |
| `test_cli_dry_run_on_existing_store_writes_nothing_and_uses_the_progress` | keep (required) | 1 | 446 |  |
| `test_cli_hard_database_error_mid_run_reports_totals_and_resume_hint` | keep (required) | 4 | 653 |  |
| `test_cli_lists_buckets_once_per_run` | keep (required) | 3 | 620 |  |
| `test_cli_planning_failure_creates_nothing_and_claims_no_progress` | keep (protected) | 0 | 228 |  |
| `test_cli_rejects_bad_ranges` | keep (required) | 9 | 80 |  |
| `test_cli_reports_progress_without_a_settled_time_as_existing` | keep (required) | 4 | 716 |  |
| `test_cli_start_end_overrides` | keep (required) | 10 | 702 |  |
| `test_cli_warns_about_unreadable_earlier_history` | keep (required) | 8 | 280 |  |
| `test_event_straddling_a_chunk_edge_is_stored_once_and_whole` | prune (scattered) | 0 | 577 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_plan_chunks_are_fixed_width_oldest_first_from_local_midnight`, `test_plan_ends_where_progress_is_settled_and_overrides_only_narrow_it`, `test_cli_backfill_rerun_inserts_nothing`, `test_unreadable_event_before_the_start_fails_safe`, `test_every_afk_event_is_stored` |
| `test_existing_progress_bounds_the_range_and_is_not_moved` | prune (scattered) | 0 | 516 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_lone_surrogates_are_scrubbed`, `test_source_without_buckets_has_no_frontier`, `test_plan_chunks_are_fixed_width_oldest_first_from_local_midnight`, `test_event_created_during_the_pull_counts_as_latest`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_plan_ends_where_progress_is_settled_and_overrides_only_narrow_it`, `test_cli_backfill_rerun_inserts_nothing` |
| `test_history_before_the_floor_is_reported_and_leaves_progress_unset` | prune (scattered) | 0 | 568 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_plan_chunks_are_fixed_width_oldest_first_from_local_midnight`, `test_event_created_during_the_pull_counts_as_latest`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_plan_probe_ignores_an_event_at_the_start_but_finds_one_before`, `test_unreadable_event_before_the_start_fails_safe`, `test_mixed_new_and_duplicate_batch`, `test_cli_start_end_overrides` |
| `test_plan_chunks_are_fixed_width_oldest_first_from_local_midnight` | keep (required) | 5 | 201 |  |
| `test_plan_ends_where_progress_is_settled_and_overrides_only_narrow_it` | keep (cover) | 0 | 267 |  |
| `test_plan_probe_ignores_an_event_at_the_start_but_finds_one_before` | keep (required) | 1 | 175 |  |
| `test_plan_without_created_times_has_no_start` | keep (required) | 6 | 183 |  |
| `test_progress_is_set_in_the_last_chunks_commit` | prune (scattered) | 0 | 534 | `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_plan_chunks_are_fixed_width_oldest_first_from_local_midnight`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_cli_backfill_mid_run_failure_keeps_committed_chunks` |
| `test_progress_set_meanwhile_wins` | prune (scattered) | 0 | 516 | `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_plan_chunks_are_fixed_width_oldest_first_from_local_midnight`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_backfill_reports_progress_set_meanwhile` |
| `test_progress_set_to_final_frontier_so_ingest_does_not_rescan_history` | prune (scattered) | 0 | 678 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_plan_chunks_are_fixed_width_oldest_first_from_local_midnight`, `test_event_created_during_the_pull_counts_as_latest`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_unreadable_event_before_the_start_fails_safe`, `test_every_afk_event_is_stored`, `test_cli_backfill_mid_run_failure_keeps_committed_chunks` |
| `test_unhandled_command_fails_cleanly` | keep (required) | 5 | 49 |  |
| `test_unreadable_event_before_the_start_fails_safe` | keep (required) | 2 | 510 |  |
| `test_when_arg_reads_naive_values_as_local_time` | keep (required) | 1 | 4 |  |

### tests/unit/test_capture_health.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_a_capture_after_a_pause_without_a_resume_ends_the_pause` | prune (scattered) | 0 | 605 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_a_pause_from_before_the_range_explains_its_start`, `test_the_spans_in_range_are_counted`, `test_a_capture_still_in_the_spool_is_the_last_capture`, `test_coverage_stops_at_stored_progress_while_the_spool_holds_records[open.part]`, `test_records_sharing_a_time_with_an_unknown_kind_do_not_break_the_rule`, `test_an_empty_open_part_is_not_a_record`, `test_the_newest_afk_event_from_activitywatch_counts_before_it_is_stored`, `test_counts_today_by_kind_and_flag`, `test_status_reports_paused_and_unobserved_capture_gaps`, `test_status_reports_every_capture_agent_line` |
| `test_a_capture_inside_a_span_of_its_app_matches_ignoring_case` | prune (scattered) | 0 | 45 | `test_the_spans_in_range_are_counted`, `test_the_pairs_come_most_common_first`, `test_app_agreement_reads_stored_and_newest_window_spans` |
| `test_a_capture_reading_another_app_differs_and_names_the_pair` | prune (scattered) | 0 | 56 | `test_the_spans_in_range_are_counted`, `test_the_pairs_come_most_common_first`, `test_app_agreement_counts_only_this_hosts_window_buckets` |
| `test_a_capture_still_in_the_spool_is_the_last_capture` | keep (required) | 1 | 402 |  |
| `test_a_capture_with_no_span_near_it_is_unjudged_never_matched` | prune (scattered) | 0 | 31 | `test_the_spans_in_range_are_counted`, `test_the_pairs_come_most_common_first`, `test_app_agreement_counts_only_this_hosts_window_buckets` |
| `test_a_gap_between_spans_within_the_tolerance_is_judged_by_the_nearest` | keep (required) | 2 | 53 |  |
| `test_a_garbled_open_part_falls_back_to_the_newest_finished_file` | prune (scattered) | 0 | 82 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_the_newest_record_is_the_last_usable_line_of_the_newest_file`, `test_an_empty_open_part_is_not_a_record`, `test_the_backlog_counts_finished_files_and_ignores_open_part_and_agent_lock` |
| `test_a_missing_spool_holds_nothing` | prune (scattered) | 0 | 25 | `test_an_empty_open_part_is_not_a_record`, `test_the_backlog_counts_finished_files_and_ignores_open_part_and_agent_lock`, `test_status_before_the_agent_reports` |
| `test_a_pause_from_before_the_range_explains_its_start` | keep (required) | 4 | 107 |  |
| `test_a_pause_still_in_the_spool_counts` | prune (scattered) | 0 | 412 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_a_capture_still_in_the_spool_is_the_last_capture`, `test_status_reports_paused_and_unobserved_capture_gaps`, `test_status_reports_every_capture_agent_line` |
| `test_a_pause_with_no_resume_explains_the_rest_of_the_range` | prune | 0 | 100 | `test_records_sharing_a_time_with_an_unknown_kind_do_not_break_the_rule` |
| `test_a_paused_agent_is_reported_as_paused` | prune | 0 | 2 | `test_status_reports_paused_and_unobserved_capture_gaps` |
| `test_a_paused_span_explains_active_time_until_the_resume` | prune | 0 | 101 | `test_records_sharing_a_time_with_an_unknown_kind_do_not_break_the_rule`, `test_a_pause_from_before_the_range_explains_its_start` |
| `test_a_recent_record_means_alive` | prune | 0 | 3 | `test_status_reports_every_capture_agent_line` |
| `test_a_record_still_in_the_spool_counts_as_the_last_record` | prune (scattered) | 0 | 406 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_a_capture_still_in_the_spool_is_the_last_capture`, `test_status_reports_every_capture_agent_line` |
| `test_a_short_silence_within_the_tolerance_is_not_a_gap` | prune | 0 | 91 | `test_a_pause_from_before_the_range_explains_its_start` |
| `test_a_switch_noticed_late_differs` | prune | 0 | 51 | `test_the_spans_in_range_are_counted`, `test_the_pairs_come_most_common_first` |
| `test_a_switch_within_the_tolerance_still_matches` | prune (scattered) | 0 | 41 | `test_the_spans_in_range_are_counted`, `test_the_pairs_come_most_common_first`, `test_a_gap_between_spans_within_the_tolerance_is_judged_by_the_nearest`, `test_app_agreement_reads_stored_and_newest_window_spans`, `test_status_reports_app_agreement_with_names_only` |
| `test_active_with_no_captures_is_unobserved_beyond_the_tolerance` | prune (scattered) | 0 | 99 | `test_a_pause_from_before_the_range_explains_its_start`, `test_records_sharing_a_time_with_an_unknown_kind_do_not_break_the_rule`, `test_silence_while_afk_is_not_a_gap` |
| `test_an_empty_open_part_is_not_a_record` | keep (required) | 1 | 29 |  |
| `test_app_agreement_counts_only_this_hosts_window_buckets` | keep (required) | 1 | 651 |  |
| `test_app_agreement_reads_stored_and_newest_window_spans` | keep (required) | 25 | 714 |  |
| `test_counts_today_by_kind_and_flag` | keep (required) | 2 | 569 |  |
| `test_coverage_stops_at_stored_progress_while_the_spool_holds_records[20261118T173000.000Z.jsonl]` | keep (required) | 1 | 584 |  |
| `test_coverage_stops_at_stored_progress_while_the_spool_holds_records[open.part]` | keep (required) | 1 | 574 |  |
| `test_excluded_records_explain_time_like_captures` | prune | 0 | 91 | `test_a_pause_from_before_the_range_explains_its_start` |
| `test_heartbeats_while_active_leave_no_gap` | prune | 0 | 92 | `test_silence_while_afk_is_not_a_gap` |
| `test_last_capture_does_not_depend_on_signals` | prune (scattered) | 0 | 531 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_the_spans_in_range_are_counted`, `test_a_pause_from_before_the_range_explains_its_start`, `test_a_capture_still_in_the_spool_is_the_last_capture`, `test_last_capture_ignores_later_records_of_other_kinds` |
| `test_last_capture_ignores_later_records_of_other_kinds` | keep (cover) | 0 | 534 |  |
| `test_missing_afk_data_cannot_be_judged_and_is_never_called_active` | prune (scattered) | 0 | 101 | `test_a_pause_from_before_the_range_explains_its_start`, `test_records_sharing_a_time_with_an_unknown_kind_do_not_break_the_rule`, `test_silence_while_afk_is_not_a_gap`, `test_counts_today_by_kind_and_flag` |
| `test_no_afk_data_at_all_leaves_the_silent_stretches_unjudged` | prune (scattered) | 0 | 88 | `test_a_pause_from_before_the_range_explains_its_start`, `test_records_sharing_a_time_with_an_unknown_kind_do_not_break_the_rule`, `test_silence_while_afk_is_not_a_gap`, `test_counts_today_by_kind_and_flag` |
| `test_nothing_stored_has_not_reported_but_shows_the_spool` | prune (scattered) | 0 | 150 | `test_fresh_db_has_full_schema`, `test_the_backlog_counts_finished_files_and_ignores_open_part_and_agent_lock`, `test_status_before_the_agent_reports` |
| `test_one_health_check_lists_the_buckets_once` | keep (required) | 6 | 558 |  |
| `test_only_captures_in_the_range_count` | prune (scattered) | 0 | 23 | `test_the_spans_in_range_are_counted`, `test_the_pairs_come_most_common_first`, `test_app_agreement_reads_stored_and_newest_window_spans` |
| `test_overlapping_spans_from_two_buckets_match_either_app` | prune (scattered) | 0 | 39 | `test_the_spans_in_range_are_counted`, `test_the_pairs_come_most_common_first`, `test_app_agreement_reads_stored_and_newest_window_spans` |
| `test_paused_until_a_later_record` | prune (scattered) | 0 | 556 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_the_spans_in_range_are_counted`, `test_a_pause_from_before_the_range_explains_its_start`, `test_a_capture_still_in_the_spool_is_the_last_capture`, `test_last_capture_ignores_later_records_of_other_kinds`, `test_records_sharing_a_time_with_an_unknown_kind_do_not_break_the_rule`, `test_status_reports_paused_and_unobserved_capture_gaps`, `test_status_reports_every_capture_agent_line` |
| `test_records_sharing_a_time_with_an_unknown_kind_do_not_break_the_rule` | keep (required) | 2 | 102 |  |
| `test_silence_while_active_is_unobserved_and_not_alive` | prune (scattered) | 0 | 595 | `test_a_record_failing_validation_says_why[line7-full_text_bytes is not a int]`, `test_the_spans_in_range_are_counted`, `test_a_pause_from_before_the_range_explains_its_start`, `test_a_capture_still_in_the_spool_is_the_last_capture`, `test_coverage_stops_at_stored_progress_while_the_spool_holds_records[open.part]`, `test_an_empty_open_part_is_not_a_record`, `test_the_newest_afk_event_from_activitywatch_counts_before_it_is_stored`, `test_status_reports_paused_and_unobserved_capture_gaps` |
| `test_silence_while_active_means_not_alive` | prune | 0 | 31 | `test_a_pause_from_before_the_range_explains_its_start`, `test_the_newest_afk_event_from_activitywatch_counts_before_it_is_stored` |
| `test_silence_while_afk_is_not_a_gap` | keep (required) | 1 | 93 |  |
| `test_silence_while_afk_or_without_afk_data_cannot_be_told` | prune | 0 | 31 | `test_a_pause_from_before_the_range_explains_its_start`, `test_the_newest_afk_event_from_activitywatch_counts_before_it_is_stored` |
| `test_status_before_the_agent_reports` | keep (required) | 1 | 331 |  |
| `test_status_reads_the_spool_flag` | keep (required) | 3 | 354 |  |
| `test_status_reports_app_agreement_with_names_only` | keep (required) | 9 | 953 |  |
| `test_status_reports_every_capture_agent_line` | keep (required) | 14 | 910 |  |
| `test_status_reports_paused_and_unobserved_capture_gaps` | keep (required) | 15 | 909 |  |
| `test_status_shows_a_file_named_after_now_as_ahead` | keep (required) | 4 | 650 |  |
| `test_status_tells_window_data_far_from_every_capture_apart` | keep (required) | 3 | 897 |  |
| `test_status_without_window_data_cannot_judge_app_agreement` | keep (required) | 3 | 812 |  |
| `test_the_backlog_counts_finished_files_and_ignores_open_part_and_agent_lock` | keep (required) | 2 | 54 |  |
| `test_the_newest_afk_event_from_activitywatch_counts_before_it_is_stored` | keep (required) | 21 | 646 |  |
| `test_the_newest_record_is_the_last_usable_line_of_the_newest_file` | keep (required) | 1 | 82 |  |
| `test_the_pairs_come_most_common_first` | keep (required) | 4 | 59 |  |
| `test_the_spans_in_range_are_counted` | keep (required) | 1 | 34 |  |

### tests/unit/test_cli.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_backfill_dry_run_refuses_an_outdated_db` | keep (required) | 4 | 174 |  |
| `test_bytes[0-0 B]` | prune (kills nothing) | 0 | 0 |  |
| `test_bytes[1023-1023 B]` | prune (kills nothing) | 0 | 0 |  |
| `test_bytes[1536-1.5 KB]` | prune | 0 | 4 | `test_bytes[5242880-5.0 MB]`, `test_status_reports_sources_lag_gaps_and_counts` |
| `test_bytes[5242880-5.0 MB]` | keep (required) | 4 | 6 |  |
| `test_duration[-5-0s]` | prune | 0 | 7 | `test_duration[0-0s]` |
| `test_duration[0-0s]` | keep (cover) | 0 | 7 |  |
| `test_duration[1800-30m]` | prune | 0 | 17 | `test_duration[60-1m]` |
| `test_duration[192-3m 12s]` | prune | 0 | 23 | `test_duration[7500-2h 5m]`, `test_lag` |
| `test_duration[3600-1h]` | prune | 0 | 17 | `test_duration[7500-2h 5m]` |
| `test_duration[3605-1h 5s]` | prune | 0 | 23 | `test_duration[7500-2h 5m]`, `test_lag` |
| `test_duration[42.4-42s]` | prune | 0 | 6 | `test_duration[0-0s]` |
| `test_duration[59.6-1m]` | prune | 0 | 19 | `test_duration[60-1m]` |
| `test_duration[60-1m]` | keep (cover) | 0 | 19 |  |
| `test_duration[7260-2h 1m]` | prune | 0 | 23 | `test_duration[7500-2h 5m]` |
| `test_duration[7500-2h 5m]` | keep (cover) | 0 | 23 |  |
| `test_duration[86400-1d]` | prune | 0 | 17 | `test_duration[88200-1d 30m]` |
| `test_duration[86405-1d 5s]` | prune | 0 | 23 | `test_duration[88200-1d 30m]`, `test_lag` |
| `test_duration[88200-1d 30m]` | keep (cover) | 0 | 23 |  |
| `test_duration[97259-1d 3h]` | keep (required) | 1 | 22 |  |
| `test_every_command_has_a_handler` | prune (kills nothing) | 0 | 0 |  |
| `test_every_command_refuses_a_newer_schema[backfill --dry-run]` | keep (protected) | 0 | 181 |  |
| `test_every_command_refuses_a_newer_schema[backfill]` | keep (protected) | 0 | 167 |  |
| `test_every_command_refuses_a_newer_schema[ingest]` | keep (cover) | 0 | 167 |  |
| `test_every_command_refuses_a_newer_schema[rebuild-signals]` | keep (protected) | 0 | 154 |  |
| `test_every_command_refuses_a_newer_schema[status]` | keep (protected) | 0 | 209 |  |
| `test_every_command_reports_a_file_that_is_not_a_database[backfill --dry-run]` | keep (protected) | 0 | 128 |  |
| `test_every_command_reports_a_file_that_is_not_a_database[backfill]` | keep (protected) | 0 | 123 |  |
| `test_every_command_reports_a_file_that_is_not_a_database[ingest]` | keep (protected) | 0 | 128 |  |
| `test_every_command_reports_a_file_that_is_not_a_database[rebuild-signals]` | keep (protected) | 0 | 110 |  |
| `test_every_command_reports_a_file_that_is_not_a_database[status]` | keep (required) | 1 | 148 |  |
| `test_help_lists_commands` | keep (protected) | 0 | 39 |  |
| `test_ingest_honors_db_env_var_and_flag_after_subcommand` | keep (protected) | 0 | 495 |  |
| `test_ingest_prints_partial_progress_then_fails` | keep (protected) | 0 | 557 |  |
| `test_ingest_watch_exits_zero_on_ctrl_c` | keep (required) | 19 | 508 |  |
| `test_ingest_with_aw_down_fails_cleanly` | keep (protected) | 0 | 320 |  |
| `test_ingest_with_no_sources` | keep (required) | 3 | 312 |  |
| `test_ingest_writes_rows_and_prints_counts` | keep (protected) | 0 | 574 |  |
| `test_lag` | keep (required) | 2 | 27 |  |
| `test_package_imports` | prune (kills nothing) | 0 | 0 |  |
| `test_poll_keeps_outcomes_committed_before_a_failure` | keep (cover) | 0 | 432 |  |
| `test_poll_reports_aw_errors` | keep (required) | 2 | 107 |  |
| `test_poll_reports_aw_errors_mid_pull` | prune (scattered) | 0 | 189 | `test_fresh_db_has_full_schema`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_hard_database_errors_propagate`, `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_keeps_outcomes_committed_before_a_failure` |
| `test_poll_returns_outcomes` | prune (scattered) | 0 | 422 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_lone_surrogates_are_scrubbed`, `test_source_without_buckets_has_no_frontier`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_poll_keeps_outcomes_committed_before_a_failure`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent` |
| `test_poll_survives_a_locked_database` | prune (scattered) | 0 | 432 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_lone_surrogates_are_scrubbed`, `test_source_without_buckets_has_no_frontier`, `test_event_created_during_the_pull_counts_as_latest`, `test_poll_keeps_outcomes_committed_before_a_failure`, `test_a_held_write_lock_does_not_block_opening_a_ready_database[Purpose.WRITE_EXISTING]`, `test_watch_survives_a_locked_database_and_logs_the_real_delay`, `test_cli_backfill_on_a_locked_store_fails_cleanly` |
| `test_rebuild_signals_migrates_an_outdated_db` | keep (protected) | 0 | 206 |  |
| `test_status_checks_sources_without_progress_up_to_latest_observation` | keep (required) | 6 | 440 |  |
| `test_status_does_not_migrate_an_old_schema` | keep (required) | 5 | 143 |  |
| `test_status_gap_window_ends_at_settled_time_not_now` | keep (protected) | 0 | 776 |  |
| `test_status_honors_aw_url` | keep (required) | 2 | 307 |  |
| `test_status_lists_many_gaps_compactly` | keep (required) | 2 | 804 |  |
| `test_status_on_fresh_db` | keep (required) | 12 | 340 |  |
| `test_status_on_missing_db_does_not_create_it` | keep (required) | 2 | 108 |  |
| `test_status_reports_a_newer_schema` | keep (cover) | 0 | 204 |  |
| `test_status_reports_sources_lag_gaps_and_counts` | keep (required) | 5 | 840 |  |
| `test_status_uses_settled_until_for_an_opaque_position` | keep (required) | 5 | 471 |  |
| `test_status_with_aw_down_still_reports_store` | keep (required) | 5 | 778 |  |
| `test_status_writes_nothing` | keep (protected) | 0 | 763 |  |
| `test_watch_survives_a_locked_database_and_logs_the_real_delay` | keep (required) | 1 | 470 |  |
| `test_watch_survives_aw_outage_and_logs_each_cycle` | prune (scattered) | 0 | 469 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_watch_reports_every_cycle_and_sleeps_for_the_rest_of_the_interval`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_lone_surrogates_are_scrubbed`, `test_source_without_buckets_has_no_frontier`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_poll_keeps_outcomes_committed_before_a_failure`, `test_watch_survives_a_locked_database_and_logs_the_real_delay`, `test_ingest_watch_exits_zero_on_ctrl_c` |
| `test_writing_commands_migrate_an_outdated_db[backfill]` | keep (protected) | 0 | 615 |  |
| `test_writing_commands_migrate_an_outdated_db[ingest]` | keep (protected) | 0 | 506 |  |
| `test_writing_commands_report_a_locked_db_at_open[backfill]` | keep (protected) | 0 | 195 |  |
| `test_writing_commands_report_a_locked_db_at_open[ingest]` | keep (protected) | 0 | 195 |  |
| `test_writing_commands_report_a_locked_db_at_open[rebuild-signals]` | keep (cover) | 0 | 177 |  |

### tests/unit/test_progress.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_a_changed_position_or_settled_time_refreshes_progress[position]` | prune (scattered) | 0 | 134 | `test_fresh_db_has_full_schema`, `test_migration_moves_cursors_into_progress_and_leaves_observations`, `test_bad_progress_updates_are_rejected[no-position]`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_a_capture_dated_after_now_is_stored_but_does_not_move_progress` |
| `test_a_changed_position_or_settled_time_refreshes_progress[settled-until-cleared]` | prune (scattered) | 0 | 139 | `test_fresh_db_has_full_schema`, `test_migration_moves_cursors_into_progress_and_leaves_observations`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_cli_reports_progress_without_a_settled_time_as_existing`, `test_a_capture_dated_after_now_is_stored_but_does_not_move_progress` |
| `test_a_changed_position_or_settled_time_refreshes_progress[settled-until]` | prune (scattered) | 0 | 137 | `test_fresh_db_has_full_schema`, `test_migration_moves_cursors_into_progress_and_leaves_observations`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_a_capture_dated_after_now_is_stored_but_does_not_move_progress` |
| `test_advance_replaces_the_previous_progress` | prune (scattered) | 0 | 140 | `test_fresh_db_has_full_schema`, `test_migration_moves_cursors_into_progress_and_leaves_observations`, `test_bad_progress_updates_are_rejected[no-position]`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_progress_does_not_move_outside_a_batch_transaction`, `test_a_capture_dated_after_now_is_stored_but_does_not_move_progress`, `test_status_uses_settled_until_for_an_opaque_position` |
| `test_backfill_keeps_progress_that_has_no_settled_time` | prune (scattered) | 0 | 524 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_lone_surrogates_are_scrubbed`, `test_source_without_buckets_has_no_frontier`, `test_plan_chunks_are_fixed_width_oldest_first_from_local_midnight`, `test_event_created_during_the_pull_counts_as_latest`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_cli_dry_run_creates_nothing_and_lists_chunks`, `test_cli_backfill_progress_read_failure_fails_cleanly[run]`, `test_cli_reports_progress_without_a_settled_time_as_existing`, `test_cli_start_end_overrides`, `test_cli_backfill_mid_run_failure_keeps_committed_chunks` |
| `test_backfill_plans_up_to_settled_until_for_an_opaque_position` | prune (scattered) | 0 | 279 | `test_plan_ends_where_progress_is_settled_and_overrides_only_narrow_it`, `test_cli_dry_run_creates_nothing_and_lists_chunks`, `test_cli_backfill_progress_read_failure_fails_cleanly[run]`, `test_cli_dry_run_on_existing_store_writes_nothing_and_uses_the_progress` |
| `test_bad_progress_updates_are_rejected[naive-settled-until]` | prune (scattered) | 0 | 5 | `test_utc_iso_rejects_naive_timestamps`, `test_progress_does_not_move_outside_a_batch_transaction`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it` |
| `test_bad_progress_updates_are_rejected[no-position]` | keep (required) | 1 | 2 |  |
| `test_bad_progress_updates_are_rejected[no-source]` | prune | 0 | 1 | `test_progress_does_not_move_outside_a_batch_transaction` |
| `test_migrated_cursor_resumes_like_progress_written_today[resume_after_migration]` | prune (scattered) | 0 | 509 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_migration_files_must_be_contiguous`, `test_event_created_during_the_pull_counts_as_latest`, `test_migration_moves_cursors_into_progress_and_leaves_observations`, `test_source_without_buckets_has_no_frontier`, `test_progress_is_min_over_buckets_and_dead_bucket_does_not_pin_it`, `test_a_file_that_cannot_be_removed_fails_once_and_does_not_block_later_files` |
| `test_migrated_cursor_resumes_like_progress_written_today[resume_on_current_schema]` | prune (scattered) | 0 | 495 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_resumes_a_little_before_its_position`, `test_lone_surrogates_are_scrubbed`, `test_event_created_during_the_pull_counts_as_latest`, `test_source_without_buckets_has_no_frontier`, `test_progress_is_min_over_buckets_and_dead_bucket_does_not_pin_it`, `test_mixed_new_and_duplicate_batch`, `test_a_file_that_cannot_be_removed_fails_once_and_does_not_block_later_files` |
| `test_migration_moves_cursors_into_progress_and_leaves_observations` | keep (required) | 1 | 146 |  |
| `test_position_without_a_settled_time_is_kept` | prune (scattered) | 0 | 131 | `test_fresh_db_has_full_schema`, `test_migration_moves_cursors_into_progress_and_leaves_observations`, `test_bad_progress_updates_are_rejected[no-position]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_progress_does_not_move_outside_a_batch_transaction`, `test_cli_reports_progress_without_a_settled_time_as_existing` |
| `test_progress_does_not_move_outside_a_batch_transaction` | keep (required) | 2 | 83 |  |
| `test_repeating_the_same_progress_does_not_refresh_it[no-settled-time]` | prune (scattered) | 0 | 158 | `test_mixed_new_and_duplicate_batch`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_progress_does_not_move_outside_a_batch_transaction`, `test_cli_reports_progress_without_a_settled_time_as_existing` |
| `test_repeating_the_same_progress_does_not_refresh_it[settled]` | prune (scattered) | 0 | 156 | `test_mixed_new_and_duplicate_batch`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it` |
| `test_set_if_none_never_overwrites` | prune (scattered) | 0 | 151 | `test_mixed_new_and_duplicate_batch`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_backfill_reports_progress_set_meanwhile` |
| `test_set_if_none_sets_absent_progress` | prune (scattered) | 0 | 148 | `test_mixed_new_and_duplicate_batch`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it` |
| `test_status_summary_reads_settled_until_for_an_opaque_position` | prune (scattered) | 0 | 143 | `test_fresh_db_has_full_schema`, `test_mixed_new_and_duplicate_batch`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_status_uses_settled_until_for_an_opaque_position` |
| `test_store_round_trips_an_opaque_position_with_settled_until_set_separately` | prune (scattered) | 0 | 165 | `test_mixed_new_and_duplicate_batch`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_a_backlog_is_listed_once_per_drain` |
| `test_the_store_exports_no_progress_writer` | prune (kills nothing) | 0 | 0 |  |

### tests/unit/test_projection.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_a_fake_adapters_projector_serves_both_ingest_and_rebuild` | prune (scattered) | 0 | 270 | `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_cli_rebuild_signals_on_a_fresh_db`, `test_shrinking_to_half_is_allowed`, `test_cli_rebuild_signals_allow_shrink` |
| `test_an_unclaimed_source_raises_its_own_error` | keep (required) | 1 | 12 |  |
| `test_backfill_stops_at_an_observation_from_another_stream` | keep (cover) | 0 | 178 |  |
| `test_cli_ingest_prints_an_unprojected_stream_and_exits_nonzero` | keep (required) | 6 | 558 |  |
| `test_cli_rebuild_with_an_unclaimed_source_fails_loudly` | keep (required) | 5 | 485 |  |
| `test_ingest_projects_only_new_observations` | prune (scattered) | 0 | 316 | `test_backfill_reports_progress_set_meanwhile`, `test_mixed_new_and_duplicate_batch`, `test_backfill_stops_at_an_observation_from_another_stream`, `test_cli_backfill_rerun_inserts_nothing` |
| `test_known_sources_project_every_activitywatch_stream` | prune (scattered) | 0 | 74 | `test_window_signal`, `test_an_unclaimed_source_raises_its_own_error`, `test_missing_data_gives_empty_signal`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_shrinking_to_half_is_allowed` |
| `test_poll_reports_a_stream_its_adapter_does_not_project_and_goes_on` | prune (scattered) | 0 | 237 | `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_an_unclaimed_source_raises_its_own_error`, `test_backfill_stops_at_an_observation_from_another_stream`, `test_cli_ingest_prints_an_unprojected_stream_and_exits_nonzero` |
| `test_poll_reports_an_observation_from_another_stream_and_stores_none_of_its_batch` | prune (scattered) | 0 | 232 | `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_backfill_stops_at_an_observation_from_another_stream`, `test_cli_ingest_prints_an_unprojected_stream_and_exits_nonzero` |
| `test_rebuild_reproduces_what_the_runner_ingested_row_for_row` | prune (scattered) | 0 | 566 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_backfill_reports_progress_set_meanwhile`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_cli_rebuild_signals_on_a_fresh_db`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_web_signal_domain_title_hygiene_and_extras`, `test_shrinking_to_half_is_allowed`, `test_cli_rebuild_signals_allow_shrink`, `test_backfill_stops_at_an_observation_from_another_stream`, `test_cli_start_end_overrides` |
| `test_rebuild_with_an_unclaimed_source_aborts_without_calling_it_malformed` | keep (required) | 5 | 445 |  |
| `test_the_same_adapter_listed_twice_is_one_claim` | prune | 0 | 7 | `test_an_unclaimed_source_raises_its_own_error` |
| `test_two_sources_projecting_one_stream_differently_are_refused` | keep (cover) | 0 | 5 |  |
| `test_unclaimed_rows_win_over_earlier_malformed_ones` | keep (required) | 2 | 393 |  |
| `test_watch_logs_an_unprojected_stream_and_keeps_polling` | prune (scattered) | 0 | 290 | `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_watch_starts_the_next_cycle_at_once_after_a_slow_one`, `test_poll_reports_aw_errors`, `test_an_unclaimed_source_raises_its_own_error`, `test_watch_survives_a_locked_database_and_logs_the_real_delay`, `test_cli_ingest_prints_an_unprojected_stream_and_exits_nonzero`, `test_ingest_watch_exits_zero_on_ctrl_c` |

### tests/unit/test_rebuild.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_a_projector_bug_failing_every_row_aborts` | prune (scattered) | 0 | 433 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_event_created_during_the_pull_counts_as_latest`, `test_only_the_first_failures_are_logged_individually`, `test_a_projector_failing_every_row_aborts_early` |
| `test_a_projector_failing_every_row_aborts_early` | keep (cover) | 0 | 437 |  |
| `test_a_projector_wrongly_returning_none_aborts_as_a_shrink` | keep (required) | 2 | 425 |  |
| `test_allow_shrink_overrides_the_shrink_check` | prune (scattered) | 0 | 423 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_lone_surrogates_are_scrubbed`, `test_source_without_buckets_has_no_frontier`, `test_event_created_during_the_pull_counts_as_latest`, `test_shrinking_to_half_is_allowed`, `test_cli_rebuild_signals_on_a_fresh_db`, `test_a_projector_wrongly_returning_none_aborts_as_a_shrink` |
| `test_cli_rebuild_signals_abort_exits_nonzero` | keep (required) | 6 | 553 |  |
| `test_cli_rebuild_signals_allow_shrink` | keep (required) | 11 | 528 |  |
| `test_cli_rebuild_signals_on_a_fresh_db` | keep (protected) | 0 | 201 |  |
| `test_cli_rebuild_signals_refuses_a_missing_db` | keep (required) | 2 | 78 |  |
| `test_cli_rebuild_signals_reports_counts` | keep (required) | 2 | 554 |  |
| `test_cli_rebuild_signals_reports_skipped_rows` | keep (protected) | 0 | 579 |  |
| `test_cli_rebuild_signals_says_how_many_ids_it_left_out` | keep (required) | 3 | 585 |  |
| `test_database_failure_mid_rebuild_rolls_back_everything` | prune (scattered) | 0 | 429 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_event_created_during_the_pull_counts_as_latest`, `test_rebuild_reproduces_ingested_signals_row_for_row[1]` |
| `test_interrupt_mid_rebuild_rolls_back_everything` | prune (scattered) | 0 | 427 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_event_created_during_the_pull_counts_as_latest`, `test_rebuild_reproduces_ingested_signals_row_for_row[1]` |
| `test_malformed_afk_payload_is_not_a_failure` | prune (scattered) | 0 | 445 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_only_the_first_failures_are_logged_individually`, `test_mixed_new_and_duplicate_batch` |
| `test_malformed_payload_is_skipped_counted_and_logged` | prune (scattered) | 0 | 469 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_only_the_first_failures_are_logged_individually`, `test_mixed_new_and_duplicate_batch`, `test_cli_rebuild_signals_on_a_fresh_db`, `test_shrinking_to_half_is_allowed` |
| `test_more_than_half_failing_aborts_and_rolls_back` | prune (scattered) | 0 | 462 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_event_created_during_the_pull_counts_as_latest`, `test_only_the_first_failures_are_logged_individually`, `test_a_projector_failing_every_row_aborts_early`, `test_a_projector_wrongly_returning_none_aborts_as_a_shrink` |
| `test_only_the_first_failures_are_logged_individually` | keep (required) | 3 | 474 |  |
| `test_rebuild_of_an_empty_store` | prune | 0 | 95 | `test_fresh_db_has_full_schema`, `test_cli_rebuild_signals_on_a_fresh_db` |
| `test_rebuild_refuses_to_run_inside_a_transaction` | keep (required) | 2 | 356 |  |
| `test_rebuild_rejects_a_nonpositive_batch_size` | keep (required) | 1 | 65 |  |
| `test_rebuild_repairs_stale_and_missing_signals` | prune (scattered) | 0 | 442 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_only_the_first_failures_are_logged_individually`, `test_mixed_new_and_duplicate_batch` |
| `test_rebuild_reproduces_ingested_signals_row_for_row[1000]` | prune (scattered) | 0 | 452 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_event_created_during_the_pull_counts_as_latest`, `test_only_the_first_failures_are_logged_individually`, `test_cli_rebuild_signals_on_a_fresh_db`, `test_mixed_new_and_duplicate_batch`, `test_shrinking_to_half_is_allowed` |
| `test_rebuild_reproduces_ingested_signals_row_for_row[1]` | keep (cover) | 0 | 454 |  |
| `test_rebuild_reproduces_ingested_signals_row_for_row[2]` | prune (scattered) | 0 | 456 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_event_created_during_the_pull_counts_as_latest`, `test_rebuild_reproduces_ingested_signals_row_for_row[1]`, `test_shrinking_to_half_is_allowed` |
| `test_rolled_back_rebuild_is_invisible_to_other_connections` | prune (scattered) | 0 | 418 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_cli_rebuild_signals_on_a_fresh_db`, `test_web_signal_domain_title_hygiene_and_extras`, `test_only_the_first_failures_are_logged_individually` |
| `test_shrinking_to_half_is_allowed` | keep (required) | 2 | 457 |  |
| `test_small_stores_may_shrink` | prune (scattered) | 0 | 438 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_extract_domain[http://WWW.Example.COM:8080/path?q=1-example.com]`, `test_source_without_buckets_has_no_frontier`, `test_non_string_fields_and_unknown_keys_go_to_extras`, `test_event_created_during_the_pull_counts_as_latest`, `test_rebuild_reproduces_ingested_signals_row_for_row[1]`, `test_cli_rebuild_signals_on_a_fresh_db`, `test_shrinking_to_half_is_allowed` |

### tests/unit/test_runner.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_backfill_commits_each_chunk_once_and_progress_only_with_the_last` | prune | 0 | 286 | `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_cli_backfill_mid_run_failure_keeps_committed_chunks` |
| `test_backfill_interrupted_reports_what_committed` | keep (cover) | 0 | 245 |  |
| `test_backfill_leaves_progress_alone_when_the_range_misses_history` | prune (scattered) | 0 | 256 | `test_held_back_events_without_a_settled_time_make_the_chunk_incomplete`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_plan_probe_ignores_an_event_at_the_start_but_finds_one_before`, `test_unreadable_event_before_the_start_fails_safe` |
| `test_backfill_of_a_stream_with_progress_keeps_it` | prune (scattered) | 0 | 361 | `test_backfill_reports_progress_set_meanwhile`, `test_plan_ends_where_progress_is_settled_and_overrides_only_narrow_it`, `test_mixed_new_and_duplicate_batch`, `test_cli_backfill_rerun_inserts_nothing` |
| `test_backfill_refuses_two_plans_for_one_stream` | keep (required) | 2 | 105 |  |
| `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it` | keep (required) | 4 | 356 |  |
| `test_backfill_reports_progress_set_meanwhile` | keep (cover) | 0 | 368 |  |
| `test_backfill_stops_at_a_busy_database_before_progress_is_set` | prune (scattered) | 0 | 270 | `test_backfill_interrupted_reports_what_committed`, `test_bad_progress_updates_are_rejected[no-position]`, `test_backfill_stops_at_an_observation_from_another_stream`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_cli_backfill_mid_run_failure_keeps_committed_chunks`, `test_cli_backfill_on_a_locked_store_fails_cleanly` |
| `test_backfill_stops_at_an_unavailable_source_and_keeps_committed_chunks` | prune (scattered) | 0 | 262 | `test_backfill_interrupted_reports_what_committed`, `test_backfill_stops_at_an_observation_from_another_stream`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_cli_backfill_with_aw_down_creates_nothing`, `test_cli_hard_database_error_mid_run_reports_totals_and_resume_hint` |
| `test_backfill_without_a_position_reports_that_progress_was_not_sent` | prune (scattered) | 0 | 252 | `test_held_back_events_without_a_settled_time_make_the_chunk_incomplete`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_cli_start_end_overrides` |
| `test_busy_database_mid_cycle_keeps_earlier_streams_and_ends_the_cycle` | prune (scattered) | 0 | 425 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_lone_surrogates_are_scrubbed`, `test_source_without_buckets_has_no_frontier`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_poll_reports_aw_errors`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_poll_keeps_outcomes_committed_before_a_failure`, `test_activitywatch_down_does_not_stop_the_spool`, `test_watch_survives_a_locked_database_and_logs_the_real_delay`, `test_cli_backfill_on_a_locked_store_fails_cleanly` |
| `test_ctrl_c_while_reporting_a_finished_stream_is_reported_as_interrupted` | prune (scattered) | 0 | 278 | `test_backfill_interrupted_reports_what_committed`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_cli_backfill_creates_store_prints_progress_and_totals` |
| `test_hard_database_errors_propagate` | keep (required) | 1 | 119 |  |
| `test_held_back_captures_wait_for_a_later_poll` | prune | 0 | 267 | `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_poll_keeps_outcomes_committed_before_a_failure` |
| `test_held_back_events_without_a_settled_time_make_the_chunk_incomplete` | keep (required) | 2 | 268 |  |
| `test_poll_refuses_a_stream_fed_by_two_sources` | prune (scattered) | 0 | 71 | `test_fresh_db_has_full_schema`, `test_two_sources_projecting_one_stream_differently_are_refused`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it` |
| `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it` | keep (required) | 1 | 282 |  |
| `test_source_that_cannot_list_its_streams_is_reported_without_a_stream` | prune (scattered) | 0 | 93 | `test_fresh_db_has_full_schema`, `test_an_unclaimed_source_raises_its_own_error`, `test_poll_reports_aw_errors` |
| `test_unavailable_source_mid_cycle_keeps_earlier_streams_and_other_sources` | prune (scattered) | 0 | 405 | `test_latest_event_settles_once_its_end_is_older_than_the_margin[120-False]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_adapter_reports_a_stream_without_buckets_as_unavailable`, `test_lone_surrogates_are_scrubbed`, `test_source_without_buckets_has_no_frontier`, `test_event_created_during_the_pull_counts_as_latest`, `test_adapter_resumes_a_little_before_its_position`, `test_poll_reports_aw_errors`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_a_file_that_cannot_be_removed_fails_once_and_does_not_block_later_files`, `test_activitywatch_down_does_not_stop_the_spool` |
| `test_watch_reports_every_cycle_and_sleeps_for_the_rest_of_the_interval` | keep (required) | 2 | 268 |  |
| `test_watch_starts_the_next_cycle_at_once_after_a_slow_one` | keep (required) | 1 | 87 |  |

### tests/unit/test_store.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_block_evidence_is_signals_overlapping_half_open_range` | prune | 0 | 67 | `test_fresh_db_has_full_schema` |
| `test_connect_uses_env_path` | prune | 0 | 64 | `test_fresh_db_has_full_schema` |
| `test_connection_settings` | prune | 0 | 65 | `test_fresh_db_has_full_schema` |
| `test_creates_parent_directory` | keep (required) | 3 | 65 |  |
| `test_failing_first_migration_leaves_db_empty` | prune | 0 | 47 | `test_later_migration_applies_in_order`, `test_a_held_write_lock_does_not_block_opening_a_ready_database[Purpose.WRITE_EXISTING]` |
| `test_failing_migration_leaves_previous_state_untouched` | prune | 0 | 83 | `test_later_migration_applies_in_order`, `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE_EXISTING]` |
| `test_fresh_db_has_full_schema` | keep (protected) | 0 | 67 |  |
| `test_later_migration_applies_in_order` | keep (required) | 1 | 84 |  |
| `test_migrate_again_is_noop` | prune | 0 | 69 | `test_fresh_db_has_full_schema`, `test_a_held_write_lock_does_not_block_opening_a_ready_database[Purpose.WRITE_EXISTING]` |
| `test_migrate_rejects_unsorted_or_gapped_caller_lists` | prune (scattered) | 0 | 74 | `test_fresh_db_has_full_schema`, `test_migration_files_must_be_contiguous`, `test_later_migration_applies_in_order` |
| `test_migration_files_must_be_contiguous` | keep (required) | 17 | 25 |  |
| `test_newer_schema_version_is_refused` | keep (required) | 1 | 68 |  |
| `test_observations_are_immutable[delete]` | keep (protected) | 0 | 66 |  |
| `test_observations_are_immutable[update]` | keep (protected) | 0 | 66 |  |
| `test_observations_unique_on_source_and_source_id` | keep (protected) | 0 | 66 |  |
| `test_path_default_under_home` | prune | 0 | 16 | `test_path_empty_values_count_as_unset` |
| `test_path_empty_values_count_as_unset` | keep (cover) | 0 | 16 |  |
| `test_path_env_wins_over_default` | prune | 0 | 2 | `test_path_empty_values_count_as_unset`, `test_cli_rejects_bad_ranges` |
| `test_path_expands_user` | prune | 0 | 2 | `test_path_empty_values_count_as_unset`, `test_cli_rejects_bad_ranges` |
| `test_path_flag_wins_over_env` | prune | 0 | 2 | `test_path_empty_values_count_as_unset`, `test_cli_rejects_bad_ranges` |
| `test_reopen_is_noop` | prune (scattered) | 0 | 71 | `test_fresh_db_has_full_schema`, `test_a_held_write_lock_does_not_block_opening_a_ready_database[Purpose.WRITE_EXISTING]`, `test_only_the_first_failures_are_logged_individually` |
| `test_signal_without_observation_is_rejected` | keep (protected) | 0 | 66 |  |
| `test_transaction_rolls_back_on_error` | prune | 0 | 66 | `test_fresh_db_has_full_schema` |
| `test_two_open_connections_to_same_file` | prune (scattered) | 0 | 71 | `test_fresh_db_has_full_schema`, `test_a_held_write_lock_does_not_block_opening_a_ready_database[Purpose.WRITE_EXISTING]`, `test_only_the_first_failures_are_logged_individually` |
| `test_utc_iso_canonicalizes_mixed_spellings` | prune | 0 | 9 | `test_utc_iso_rejects_naive_timestamps`, `test_gaps_accept_string_bounds_and_reject_empty_range` |
| `test_utc_iso_rejects_naive_timestamps` | keep (required) | 1 | 5 |  |

### tests/unit/test_store_api.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_afk_observation_gets_no_signal` | prune | 0 | 117 | `test_mixed_new_and_duplicate_batch` |
| `test_duplicate_in_same_batch_is_skipped` | prune | 0 | 119 | `test_mixed_new_and_duplicate_batch`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it` |
| `test_duplicate_never_overwrites_existing_signal` | prune | 0 | 111 | `test_mixed_new_and_duplicate_batch` |
| `test_empty_batch` | prune | 0 | 95 | `test_fresh_db_has_full_schema`, `test_mixed_new_and_duplicate_batch` |
| `test_failed_batch_rolls_back_first_progress` | prune (scattered) | 0 | 116 | `test_fresh_db_has_full_schema`, `test_mixed_new_and_duplicate_batch`, `test_bad_progress_updates_are_rejected[no-position]`, `test_progress_does_not_move_outside_a_batch_transaction`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it` |
| `test_failed_signal_rolls_back_whole_batch_and_progress` | prune | 0 | 143 | `test_mixed_new_and_duplicate_batch`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it` |
| `test_gaps_accept_string_bounds_and_reject_empty_range` | keep (required) | 2 | 98 |  |
| `test_gaps_at_range_edges_are_clipped` | prune (scattered) | 0 | 138 | `test_no_gaps_when_continuous`, `test_utc_iso_rejects_naive_timestamps`, `test_gaps_accept_string_bounds_and_reject_empty_range`, `test_status_checks_sources_without_progress_up_to_latest_observation` |
| `test_gaps_ignore_observations_outside_range` | prune | 0 | 133 | `test_gaps_accept_string_bounds_and_reject_empty_range`, `test_mixed_new_and_duplicate_batch` |
| `test_gaps_ignore_other_sources` | prune | 0 | 133 | `test_gaps_accept_string_bounds_and_reject_empty_range`, `test_mixed_new_and_duplicate_batch` |
| `test_gaps_merge_overlapping_observations` | prune (scattered) | 0 | 139 | `test_no_gaps_when_continuous`, `test_gaps_accept_string_bounds_and_reject_empty_range`, `test_status_checks_sources_without_progress_up_to_latest_observation` |
| `test_gaps_min_length_filter` | prune (scattered) | 0 | 139 | `test_no_gaps_when_continuous`, `test_gaps_accept_string_bounds_and_reject_empty_range`, `test_status_checks_sources_without_progress_up_to_latest_observation` |
| `test_gaps_whole_range_when_no_observations` | prune | 0 | 96 | `test_gaps_accept_string_bounds_and_reject_empty_range` |
| `test_generator_input` | prune | 0 | 118 | `test_mixed_new_and_duplicate_batch`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it` |
| `test_insert_inside_open_transaction_is_refused` | keep (required) | 2 | 68 |  |
| `test_insert_writes_observation_and_signal` | prune | 0 | 120 | `test_mixed_new_and_duplicate_batch`, `test_fresh_db_has_full_schema` |
| `test_invalid_observation_rejects_whole_batch[empty-id]` | prune | 0 | 75 | `test_fresh_db_has_full_schema`, `test_mixed_new_and_duplicate_batch` |
| `test_invalid_observation_rejects_whole_batch[ends-before-start]` | prune | 0 | 75 | `test_fresh_db_has_full_schema`, `test_mixed_new_and_duplicate_batch` |
| `test_invalid_observation_rejects_whole_batch[naive-timestamp]` | prune (scattered) | 0 | 77 | `test_fresh_db_has_full_schema`, `test_utc_iso_rejects_naive_timestamps`, `test_mixed_new_and_duplicate_batch` |
| `test_invalid_observation_rejects_whole_batch[null-id]` | prune | 0 | 75 | `test_fresh_db_has_full_schema`, `test_mixed_new_and_duplicate_batch` |
| `test_mixed_new_and_duplicate_batch` | keep (cover) | 0 | 120 |  |
| `test_no_gaps_when_continuous` | keep (required) | 1 | 125 |  |
| `test_progress_advances_even_when_batch_is_all_duplicates` | prune (scattered) | 0 | 152 | `test_migration_moves_cursors_into_progress_and_leaves_observations`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it` |
| `test_progress_advances_with_batch` | prune | 0 | 164 | `test_mixed_new_and_duplicate_batch`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it` |
| `test_reinsert_adds_zero_rows` | prune | 0 | 120 | `test_mixed_new_and_duplicate_batch`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it` |
| `test_retry_after_failure_succeeds` | prune (scattered) | 0 | 167 | `test_mixed_new_and_duplicate_batch`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it` |
| `test_same_source_id_in_different_sources_is_not_a_duplicate` | prune | 0 | 119 | `test_mixed_new_and_duplicate_batch`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it` |
| `test_source_summary` | prune (scattered) | 0 | 148 | `test_mixed_new_and_duplicate_batch`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_status_uses_settled_until_for_an_opaque_position` |
| `test_table_counts` | prune (scattered) | 0 | 138 | `test_mixed_new_and_duplicate_batch`, `test_bad_progress_updates_are_rejected[no-position]`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent`, `test_status_on_fresh_db` |
| `test_timestamps_stored_canonically` | prune (scattered) | 0 | 139 | `test_mixed_new_and_duplicate_batch`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it`, `test_fresh_db_has_full_schema`, `test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it` |
| `test_unclaimed_source_rolls_back_whole_batch_and_progress` | prune (scattered) | 0 | 109 | `test_fresh_db_has_full_schema`, `test_mixed_new_and_duplicate_batch`, `test_bad_progress_updates_are_rejected[no-position]`, `test_progress_does_not_move_outside_a_batch_transaction`, `test_an_unclaimed_source_raises_its_own_error`, `test_poll_writes_each_stream_with_its_progress_and_resumes_after_it` |
| `test_zero_length_observation_does_not_split_a_gap` | prune (scattered) | 0 | 134 | `test_gaps_accept_string_bounds_and_reject_empty_range`, `test_mixed_new_and_duplicate_batch`, `test_a_backlog_is_listed_once_per_drain` |

### tests/unit/test_store_open.py

| test | verdict | unique kills | kills | still killed by |
|---|---|---|---|---|
| `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE]` | prune | 0 | 43 | `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE_EXISTING]`, `test_fresh_db_has_full_schema` |
| `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE_EXISTING]` | keep (cover) | 0 | 42 |  |
| `test_a_file_that_is_not_a_database_is_unreadable[Purpose.READ]` | prune | 0 | 42 | `test_every_command_reports_a_file_that_is_not_a_database[backfill --dry-run]` |
| `test_a_file_that_is_not_a_database_is_unreadable[Purpose.WRITE]` | prune | 0 | 44 | `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE_EXISTING]`, `test_every_command_reports_a_file_that_is_not_a_database[ingest]` |
| `test_a_file_that_is_not_a_database_is_unreadable[Purpose.WRITE_EXISTING]` | prune | 0 | 43 | `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE_EXISTING]`, `test_every_command_reports_a_file_that_is_not_a_database[rebuild-signals]` |
| `test_a_held_write_lock_does_not_block_opening_a_ready_database[Purpose.READ]` | prune | 0 | 89 | `test_fresh_db_has_full_schema`, `test_ready_database_opens_for_every_purpose` |
| `test_a_held_write_lock_does_not_block_opening_a_ready_database[Purpose.WRITE]` | prune | 0 | 78 | `test_fresh_db_has_full_schema`, `test_a_held_write_lock_does_not_block_opening_a_ready_database[Purpose.WRITE_EXISTING]` |
| `test_a_held_write_lock_does_not_block_opening_a_ready_database[Purpose.WRITE_EXISTING]` | keep (cover) | 0 | 82 |  |
| `test_closing_the_store_closes_its_connection` | prune (scattered) | 0 | 80 | `test_fresh_db_has_full_schema`, `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE_EXISTING]`, `test_ready_database_opens_for_every_purpose`, `test_cli_backfill_with_aw_down_creates_nothing`, `test_ingest_with_no_sources` |
| `test_lock_contention_while_opening_for_write_is_busy[Purpose.WRITE]` | prune | 0 | 106 | `test_later_migration_applies_in_order`, `test_writing_commands_report_a_locked_db_at_open[rebuild-signals]` |
| `test_lock_contention_while_opening_for_write_is_busy[Purpose.WRITE_EXISTING]` | prune | 0 | 105 | `test_later_migration_applies_in_order`, `test_writing_commands_report_a_locked_db_at_open[rebuild-signals]` |
| `test_missing_database_is_reported_and_never_created[Purpose.READ]` | prune | 0 | 12 | `test_cli_rebuild_signals_refuses_a_missing_db` |
| `test_missing_database_is_reported_and_never_created[Purpose.WRITE_EXISTING]` | prune | 0 | 12 | `test_cli_rebuild_signals_refuses_a_missing_db` |
| `test_newer_database_is_refused_for_every_purpose[Purpose.READ]` | keep (cover) | 0 | 96 |  |
| `test_newer_database_is_refused_for_every_purpose[Purpose.WRITE]` | prune | 0 | 80 | `test_fresh_db_has_full_schema`, `test_newer_database_is_refused_for_every_purpose[Purpose.WRITE_EXISTING]` |
| `test_newer_database_is_refused_for_every_purpose[Purpose.WRITE_EXISTING]` | keep (cover) | 0 | 85 |  |
| `test_read_purpose_connection_refuses_writes` | prune (scattered) | 0 | 127 | `test_fresh_db_has_full_schema`, `test_utc_iso_rejects_naive_timestamps`, `test_ready_database_opens_for_every_purpose`, `test_mixed_new_and_duplicate_batch`, `test_status_on_fresh_db`, `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE_EXISTING]` |
| `test_read_purpose_refuses_an_outdated_database_without_migrating` | prune (scattered) | 0 | 86 | `test_later_migration_applies_in_order`, `test_newer_database_is_refused_for_every_purpose[Purpose.READ]`, `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE_EXISTING]`, `test_backfill_dry_run_refuses_an_outdated_db` |
| `test_read_purpose_treats_an_empty_file_as_outdated` | prune (scattered) | 0 | 41 | `test_newer_database_is_refused_for_every_purpose[Purpose.READ]`, `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE_EXISTING]`, `test_backfill_dry_run_refuses_an_outdated_db` |
| `test_ready_database_opens_for_every_purpose` | keep (required) | 6 | 115 |  |
| `test_write_purpose_creates_a_missing_database` | prune (scattered) | 0 | 75 | `test_creates_parent_directory`, `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE_EXISTING]`, `test_a_held_write_lock_does_not_block_opening_a_ready_database[Purpose.WRITE_EXISTING]`, `test_cli_rebuild_signals_refuses_a_missing_db`, `test_ingest_with_no_sources` |
| `test_write_purposes_migrate_an_outdated_database[Purpose.WRITE]` | prune (scattered) | 0 | 91 | `test_later_migration_applies_in_order`, `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE_EXISTING]`, `test_ready_database_opens_for_every_purpose` |
| `test_write_purposes_migrate_an_outdated_database[Purpose.WRITE_EXISTING]` | prune (scattered) | 0 | 90 | `test_later_migration_applies_in_order`, `test_a_database_that_cannot_use_wal_is_unreadable_for_write[Purpose.WRITE_EXISTING]`, `test_ready_database_opens_for_every_purpose` |

## Surviving mutants

### computer_history.cli.app

| mutant | status | change |
|---|---|---|
| `x_build_parser__mutmut_10` | survived | `description="Local activity store and ActivityWatch ingest.",` → `description="LOCAL ACTIVITY STORE AND ACTIVITYWATCH INGEST.",` |
| `x_build_parser__mutmut_102` | survived | `help="backfill from this ISO date/datetime (local time unless it has an"` → `help="backfill from this iso date/datetime (local time unless it has an"` |
| `x_build_parser__mutmut_103` | survived | `help="backfill from this ISO date/datetime (local time unless it has an"` → `help="BACKFILL FROM THIS ISO DATE/DATETIME (LOCAL TIME UNLESS IT HAS AN"` |
| `x_build_parser__mutmut_105` | survived | `" offset) instead of where the ActivityWatch buckets begin",` → `" offset) instead of where the activitywatch buckets begin",` |
| `x_build_parser__mutmut_106` | survived | `" offset) instead of where the ActivityWatch buckets begin",` → `" OFFSET) INSTEAD OF WHERE THE ACTIVITYWATCH BUCKETS BEGIN",` |
| `x_build_parser__mutmut_109` | survived | `help="stop at this ISO date/datetime (default: the time the source's ingest" / " is settled until, or now; never later than those)",` → `help=None,` |
| `x_build_parser__mutmut_11` | survived | `db_help = ( / "SQLite database path (default: $COMPUTER_HISTORY_DB, else " / "~/Library/Application Support/ComputerHistory/history.db)" / )` → `db_help = None` |
| `x_build_parser__mutmut_112` | survived | `help="stop at this ISO date/datetime (default: the time the source's ingest" / " is settled until, or now; never later than those)", / )` → `)` |
| `x_build_parser__mutmut_116` | survived | `help="stop at this ISO date/datetime (default: the time the source's ingest"` → `help="stop at this iso date/datetime (default: the time the source's ingest"` |
| `x_build_parser__mutmut_117` | survived | `help="stop at this ISO date/datetime (default: the time the source's ingest"` → `help="STOP AT THIS ISO DATE/DATETIME (DEFAULT: THE TIME THE SOURCE'S INGEST"` |
| `x_build_parser__mutmut_119` | survived | `" is settled until, or now; never later than those)",` → `" IS SETTLED UNTIL, OR NOW; NEVER LATER THAN THOSE)",` |
| `x_build_parser__mutmut_122` | survived | `help="discover sources and print the planned chunks; write nothing",` → `help=None,` |
| `x_build_parser__mutmut_125` | survived | `help="discover sources and print the planned chunks; write nothing", / )` → `)` |
| `x_build_parser__mutmut_13` | survived | `"SQLite database path (default: $COMPUTER_HISTORY_DB, else "` → `"sqlite database path (default: $computer_history_db, else "` |
| `x_build_parser__mutmut_131` | survived | `help="discover sources and print the planned chunks; write nothing",` → `help="DISCOVER SOURCES AND PRINT THE PLANNED CHUNKS; WRITE NOTHING",` |
| `x_build_parser__mutmut_138` | survived | `help="capture spool folder (default: $COMPUTER_HISTORY_SPOOL, else spool/ beside" / " the database)",` → `help=None,` |
| `x_build_parser__mutmut_14` | survived | `"SQLite database path (default: $COMPUTER_HISTORY_DB, else "` → `"SQLITE DATABASE PATH (DEFAULT: $COMPUTER_HISTORY_DB, ELSE "` |
| `x_build_parser__mutmut_140` | survived | `help="capture spool folder (default: $COMPUTER_HISTORY_SPOOL, else spool/ beside" / " the database)", / )` → `)` |
| `x_build_parser__mutmut_144` | survived | `help="capture spool folder (default: $COMPUTER_HISTORY_SPOOL, else spool/ beside"` → `help="capture spool folder (default: $computer_history_spool, else spool/ beside"` |
| `x_build_parser__mutmut_145` | survived | `help="capture spool folder (default: $COMPUTER_HISTORY_SPOOL, else spool/ beside"` → `help="CAPTURE SPOOL FOLDER (DEFAULT: $COMPUTER_HISTORY_SPOOL, ELSE SPOOL/ BESIDE"` |
| `x_build_parser__mutmut_147` | survived | `" the database)",` → `" THE DATABASE)",` |
| `x_build_parser__mutmut_153` | survived | `help=f"poll every {POLL_INTERVAL_SECONDS}s until interrupted (Ctrl-C)",` → `help=None,` |
| `x_build_parser__mutmut_156` | survived | `help=f"poll every {POLL_INTERVAL_SECONDS}s until interrupted (Ctrl-C)", / )` → `)` |
| `x_build_parser__mutmut_16` | survived | `"~/Library/Application Support/ComputerHistory/history.db)"` → `"~/library/application support/computerhistory/history.db)"` |
| `x_build_parser__mutmut_17` | survived | `"~/Library/Application Support/ComputerHistory/history.db)"` → `"~/LIBRARY/APPLICATION SUPPORT/COMPUTERHISTORY/HISTORY.DB)"` |
| `x_build_parser__mutmut_19` | survived | `parser.add_argument("--db-path", help=db_help)` → `parser.add_argument("--db-path", help=None)` |
| `x_build_parser__mutmut_2` | survived | `prog="computer-history",` → `prog=None,` |
| `x_build_parser__mutmut_21` | survived | `parser.add_argument("--db-path", help=db_help)` → `parser.add_argument("--db-path", )` |
| `x_build_parser__mutmut_25` | survived | `db_after_command = argparse.ArgumentParser(add_help=False)` → `db_after_command = argparse.ArgumentParser(add_help=None)` |
| `x_build_parser__mutmut_29` | survived | `db_after_command.add_argument("--db-path", default=argparse.SUPPRESS, help=db_help)` → `db_after_command.add_argument("--db-path", default=argparse.SUPPRESS, help=None)` |
| `x_build_parser__mutmut_3` | survived | `description="Local activity store and ActivityWatch ingest.",` → `description=None,` |
| `x_build_parser__mutmut_32` | survived | `db_after_command.add_argument("--db-path", default=argparse.SUPPRESS, help=db_help)` → `db_after_command.add_argument("--db-path", default=argparse.SUPPRESS, )` |
| `x_build_parser__mutmut_36` | survived | `aw = argparse.ArgumentParser(add_help=False)` → `aw = argparse.ArgumentParser(add_help=None)` |
| `x_build_parser__mutmut_4` | survived | `prog="computer-history",` → `` |
| `x_build_parser__mutmut_40` | survived | `help=f"ActivityWatch API base URL (default: {DEFAULT_AW_URL})",` → `help=None,` |
| `x_build_parser__mutmut_43` | survived | `help=f"ActivityWatch API base URL (default: {DEFAULT_AW_URL})", / )` → `)` |
| `x_build_parser__mutmut_48` | survived | `subparsers = parser.add_subparsers(dest="command", required=True)` → `subparsers = parser.add_subparsers(dest="command", required=None)` |
| `x_build_parser__mutmut_5` | survived | `description="Local activity store and ActivityWatch ingest.", / )` → `)` |
| `x_build_parser__mutmut_50` | survived | `subparsers = parser.add_subparsers(dest="command", required=True)` → `subparsers = parser.add_subparsers(dest="command", )` |
| `x_build_parser__mutmut_53` | survived | `subparsers = parser.add_subparsers(dest="command", required=True)` → `subparsers = parser.add_subparsers(dest="command", required=False)` |
| `x_build_parser__mutmut_56` | survived | `if name in ("ingest", "status", "backfill")` → `if (name in ("ingest", "status", "backfill")) or True` |
| `x_build_parser__mutmut_6` | survived | `prog="computer-history",` → `prog="XXcomputer-historyXX",` |
| `x_build_parser__mutmut_66` | survived | `sub = subparsers.add_parser(name, help=help_text, description=help_text, parents=parents)` → `sub = subparsers.add_parser(name, help=None, description=help_text, parents=parents)` |
| `x_build_parser__mutmut_67` | survived | `sub = subparsers.add_parser(name, help=help_text, description=help_text, parents=parents)` → `sub = subparsers.add_parser(name, help=help_text, description=None, parents=parents)` |
| `x_build_parser__mutmut_7` | survived | `prog="computer-history",` → `prog="COMPUTER-HISTORY",` |
| `x_build_parser__mutmut_70` | survived | `sub = subparsers.add_parser(name, help=help_text, description=help_text, parents=parents)` → `sub = subparsers.add_parser(name, description=help_text, parents=parents)` |
| `x_build_parser__mutmut_71` | survived | `sub = subparsers.add_parser(name, help=help_text, description=help_text, parents=parents)` → `sub = subparsers.add_parser(name, help=help_text, parents=parents)` |
| `x_build_parser__mutmut_78` | survived | `help="allow a rebuild that drops more than half of the existing signals" / " (refused by default as a likely mapping bug)",` → `help=None,` |
| `x_build_parser__mutmut_81` | survived | `help="allow a rebuild that drops more than half of the existing signals" / " (refused by default as a likely mapping bug)", / )` → `)` |
| `x_build_parser__mutmut_87` | survived | `help="allow a rebuild that drops more than half of the existing signals"` → `help="ALLOW A REBUILD THAT DROPS MORE THAN HALF OF THE EXISTING SIGNALS"` |
| `x_build_parser__mutmut_89` | survived | `" (refused by default as a likely mapping bug)",` → `" (REFUSED BY DEFAULT AS A LIKELY MAPPING BUG)",` |
| `x_build_parser__mutmut_95` | survived | `help="backfill from this ISO date/datetime (local time unless it has an" / " offset) instead of where the ActivityWatch buckets begin",` → `help=None,` |
| `x_build_parser__mutmut_98` | survived | `help="backfill from this ISO date/datetime (local time unless it has an" / " offset) instead of where the ActivityWatch buckets begin", / )` → `)` |
| `x_main__mutmut_10` | survived | `format="%(asctime)s %(levelname)s %(message)s",` → `format="%(ASCTIME)S %(LEVELNAME)S %(MESSAGE)S",` |
| `x_main__mutmut_12` | survived | `datefmt="%Y-%m-%d %H:%M:%S",` → `datefmt="%y-%m-%d %h:%m:%s",` |
| `x_main__mutmut_13` | survived | `datefmt="%Y-%m-%d %H:%M:%S",` → `datefmt="%Y-%M-%D %H:%M:%S",` |
| `x_main__mutmut_3` | survived | `level=logging.INFO,` → `level=None,` |
| `x_main__mutmut_4` | survived | `format="%(asctime)s %(levelname)s %(message)s",` → `format=None,` |
| `x_main__mutmut_5` | survived | `datefmt="%Y-%m-%d %H:%M:%S",` → `datefmt=None,` |
| `x_main__mutmut_6` | survived | `level=logging.INFO,` → `` |
| `x_main__mutmut_7` | survived | `format="%(asctime)s %(levelname)s %(message)s",` → `` |
| `x_main__mutmut_8` | survived | `datefmt="%Y-%m-%d %H:%M:%S", / )` → `)` |
| `x_when_arg__mutmut_4` | survived | `if parsed.tzinfo is None:` → `if parsed.tzinfo is not None:` |

### computer_history.cli.backfill

| mutant | status | change |
|---|---|---|
| `x__backfill__mutmut_16` | survived | `print("backfill interrupted", file=sys.stderr)` → `print(None, file=sys.stderr)` |
| `x__backfill__mutmut_17` | survived | `print("backfill interrupted", file=sys.stderr)` → `print("backfill interrupted", file=None)` |
| `x__backfill__mutmut_18` | survived | `print("backfill interrupted", file=sys.stderr)` → `print(file=sys.stderr)` |
| `x__backfill__mutmut_19` | survived | `print("backfill interrupted", file=sys.stderr)` → `print("backfill interrupted", )` |
| `x__backfill__mutmut_21` | survived | `print("backfill interrupted", file=sys.stderr)` → `print("BACKFILL INTERRUPTED", file=sys.stderr)` |
| `x__backfill__mutmut_22` | survived | `code = 130` → `code = None` |
| `x__backfill__mutmut_23` | survived | `code = 130` → `code = 131` |
| `x__backfill__mutmut_25` | survived | `busy = db_busy_hint(db_path)` → `busy = db_busy_hint(None)` |
| `x__failed__mutmut_4` | survived | `print(f"backfill stopped: {failure.error}", file=sys.stderr)` → `print(None, file=sys.stderr)` |
| `x__failed__mutmut_5` | survived | `print(f"backfill stopped: {failure.error}", file=sys.stderr)` → `print(f"backfill stopped: {failure.error}", file=None)` |
| `x__failed__mutmut_6` | survived | `print(f"backfill stopped: {failure.error}", file=sys.stderr)` → `print(file=sys.stderr)` |
| `x__failed__mutmut_7` | survived | `print(f"backfill stopped: {failure.error}", file=sys.stderr)` → `print(f"backfill stopped: {failure.error}", )` |
| `x__failed__mutmut_8` | survived | `return 1` → `return 2` |
| `x__print_chunk__mutmut_1` | survived | `if done.index == 0:` → `if done.index != 0:` |
| `x__print_chunk__mutmut_13` | survived | `line += f"  incomplete from {when(done.incomplete_from)}"` → `line += f"  incomplete from {when(None)}"` |
| `x__print_chunk__mutmut_15` | survived | `print(line, flush=True)` → `print(line, flush=None)` |
| `x__print_chunk__mutmut_17` | survived | `print(line, flush=True)` → `print(line, )` |
| `x__print_chunk__mutmut_18` | survived | `print(line, flush=True)` → `print(line, flush=False)` |
| `x__print_chunk__mutmut_2` | survived | `if done.index == 0:` → `if done.index == 1:` |
| `x__print_chunk__mutmut_3` | survived | `print(flush=True)` → `print(flush=None)` |
| `x__print_chunk__mutmut_4` | survived | `print(flush=True)` → `print(flush=False)` |
| `x__print_chunk__mutmut_8` | survived | `f"  {done.stream} chunk {done.index + 1:>{width}}/{done.total}  {_span(done.chunk)}"` → `f"  {done.stream} chunk {done.index + 2:>{width}}/{done.total}  {_span(done.chunk)}"` |
| `x__print_done__mutmut_10` | survived | `if not plan.has_progress` → `if (not plan.has_progress) or True` |
| `x__print_done__mutmut_12` | survived | `"`computer-history ingest` picks them up once settled"` → `"`COMPUTER-HISTORY INGEST` PICKS THEM UP ONCE SETTLED"` |
| `x__print_done__mutmut_13` | survived | `if not plan.has_progress` → `if plan.has_progress` |
| `x__print_done__mutmut_15` | survived | `else "re-run backfill later to fill them"` → `else "RE-RUN BACKFILL LATER TO FILL THEM"` |
| `x__print_done__mutmut_17` | survived | `f"  note: {result.stream} events from {when(frontier)} to {when(chunk.end)}"` → `f"  note: {result.stream} events from {when(None)} to {when(chunk.end)}"` |
| `x__print_done__mutmut_18` | survived | `f"  note: {result.stream} events from {when(frontier)} to {when(chunk.end)}"` → `f"  note: {result.stream} events from {when(frontier)} to {when(None)}"` |
| `x__print_done__mutmut_3` | survived | `flush=True,` → `flush=None,` |
| `x__print_done__mutmut_5` | survived | `flush=True, / )` → `)` |
| `x__print_done__mutmut_7` | survived | `flush=True,` → `flush=False,` |
| `x__print_done__mutmut_8` | survived | `later = ( / "`computer-history ingest` picks them up once settled" / if not plan.has_progress / else "re-run backfill later to fill them" / )` → `later = None` |
| `x__print_done__mutmut_9` | survived | `if not plan.has_progress` → `if (not plan.has_progress) and False` |
| `x__print_plan__mutmut_13` | survived | `bound = f"up to its settled-until time {when(plan.settled_until)}"` → `bound = f"up to its settled-until time {when(None)}"` |
| `x__print_plan__mutmut_21` | survived | `f"{head} cannot tell where its history begins (no bucket has a usable" / " 'created' time); pass --start"` → `None` |
| `x__print_plan__mutmut_23` | survived | `" 'created' time); pass --start"` → `" 'CREATED' TIME); PASS --START"` |
| `x__print_plan__mutmut_25` | survived | `print(f"{head} nothing to backfill: {when(plan.start)} is not before {when(plan.end)}")` → `print(None)` |
| `x__print_plan__mutmut_26` | survived | `print(f"{head} nothing to backfill: {when(plan.start)} is not before {when(plan.end)}")` → `print(f"{head} nothing to backfill: {when(None)} is not before {when(plan.end)}")` |
| `x__print_plan__mutmut_27` | survived | `print(f"{head} nothing to backfill: {when(plan.start)} is not before {when(plan.end)}")` → `print(f"{head} nothing to backfill: {when(plan.start)} is not before {when(None)}")` |
| `x__print_plan__mutmut_30` | survived | `flush=True,` → `flush=None,` |
| `x__print_plan__mutmut_32` | survived | `flush=True, / )` → `)` |
| `x__print_plan__mutmut_34` | survived | `f"{head} {_span(Chunk(plan.start, plan.end))} {bound},"` → `f"{head} {_span(Chunk(None, plan.end))} {bound},"` |
| `x__print_plan__mutmut_35` | survived | `f"{head} {_span(Chunk(plan.start, plan.end))} {bound},"` → `f"{head} {_span(Chunk(plan.start, None))} {bound},"` |
| `x__print_plan__mutmut_38` | survived | `f" {count} chunk{'s' if count != 1 else ''}",` → `f" {count} chunk{'s' if (count != 1) and False else ''}",` |
| `x__print_plan__mutmut_39` | survived | `f" {count} chunk{'s' if count != 1 else ''}",` → `f" {count} chunk{'s' if (count != 1) or True else ''}",` |
| `x__print_plan__mutmut_4` | survived | `head = f"  {name} ({buckets} bucket{'s' if buckets != 1 else ''}):"` → `head = f"  {name} ({buckets} bucket{'s' if (buckets != 1) and False else ''}):"` |
| `x__print_plan__mutmut_40` | survived | `f" {count} chunk{'s' if count != 1 else ''}",` → `f" {count} chunk{'XXsXX' if count != 1 else ''}",` |
| `x__print_plan__mutmut_41` | survived | `f" {count} chunk{'s' if count != 1 else ''}",` → `f" {count} chunk{'S' if count != 1 else ''}",` |
| `x__print_plan__mutmut_42` | survived | `f" {count} chunk{'s' if count != 1 else ''}",` → `f" {count} chunk{'s' if count == 1 else ''}",` |
| `x__print_plan__mutmut_43` | survived | `f" {count} chunk{'s' if count != 1 else ''}",` → `f" {count} chunk{'s' if count != 2 else ''}",` |
| `x__print_plan__mutmut_44` | survived | `f" {count} chunk{'s' if count != 1 else ''}",` → `f" {count} chunk{'s' if count != 1 else 'XXXX'}",` |
| `x__print_plan__mutmut_45` | survived | `flush=True,` → `flush=False,` |
| `x__print_plan__mutmut_48` | survived | `newest = "has an unreadable timestamp" if began is None else f"starts {when(began)}"` → `newest = "has an unreadable timestamp" if (began is None) or True else f"starts {when(began)}"` |
| `x__print_plan__mutmut_52` | survived | `newest = "has an unreadable timestamp" if began is None else f"starts {when(began)}"` → `newest = "has an unreadable timestamp" if began is None else f"starts {when(None)}"` |
| `x__print_plan__mutmut_54` | survived | `f"    warning: {part} has events before {when(plan.start)}"` → `f"    warning: {part} has events before {when(None)}"` |
| `x__print_plan__mutmut_56` | survived | `" set. Pass an earlier --start to include them."` → `" set. pass an earlier --start to include them."` |
| `x__print_plan__mutmut_6` | survived | `head = f"  {name} ({buckets} bucket{'s' if buckets != 1 else ''}):"` → `head = f"  {name} ({buckets} bucket{'XXsXX' if buckets != 1 else ''}):"` |
| `x__print_plan__mutmut_62` | survived | `print(f"    chunk {index + 1:>{width}}/{count}  {_span(chunk)}")` → `print(f"    chunk {index + 2:>{width}}/{count}  {_span(chunk)}")` |
| `x__print_plan__mutmut_7` | survived | `head = f"  {name} ({buckets} bucket{'s' if buckets != 1 else ''}):"` → `head = f"  {name} ({buckets} bucket{'S' if buckets != 1 else ''}):"` |
| `x__progress_note__mutmut_11` | survived | `" (incremental ingest owns what follows)"` → `" (INCREMENTAL INGEST OWNS WHAT FOLLOWS)"` |
| `x__progress_note__mutmut_17` | survived | `" history, so the next `ingest` reads from the beginning"` → `" HISTORY, SO THE NEXT `INGEST` READS FROM THE BEGINNING"` |
| `x__progress_note__mutmut_19` | survived | `return "progress not set: the source reported no position to resume from"` → `return "PROGRESS NOT SET: THE SOURCE REPORTED NO POSITION TO RESUME FROM"` |
| `x__progress_note__mutmut_21` | survived | `return "progress not set: another ingest set it meanwhile"` → `return "PROGRESS NOT SET: ANOTHER INGEST SET IT MEANWHILE"` |
| `x__progress_note__mutmut_4` | survived | `case BackfillProgress.NOT_COVERED: / return ( / "progress not set: this range does not start before all of the source's" / " history, so the next `ingest` reads from the beginning" / )` → `` |
| `x__progress_note__mutmut_5` | survived | `case BackfillProgress.NO_POSITION: / return "progress not set: the source reported no position to resume from"` → `` |
| `x__progress_note__mutmut_6` | survived | `f"progress set: settled until {when(result.complete_until)};"` → `f"progress set: settled until {when(None)};"` |
| `x__progress_note__mutmut_8` | survived | `" `computer-history ingest` continues from there without re-reading history"` → `" `COMPUTER-HISTORY INGEST` CONTINUES FROM THERE WITHOUT RE-READING HISTORY"` |
| `x__progress_note__mutmut_9` | survived | `f"progress unchanged: settled until {when(result.plan.settled_until)}"` → `f"progress unchanged: settled until {when(None)}"` |
| `x__span__mutmut_1` | survived | `return f"[{when(chunk.start)}, {when(chunk.end)})"` → `return f"[{when(None)}, {when(chunk.end)})"` |
| `x__span__mutmut_2` | survived | `return f"[{when(chunk.start)}, {when(chunk.end)})"` → `return f"[{when(chunk.start)}, {when(None)})"` |
| `x_cmd_backfill__mutmut_12` | survived | `if args.start is not None and args.end is not None and args.start >= args.end:` → `if args.start is not None and args.end is not None and args.start > args.end:` |
| `x_cmd_backfill__mutmut_5` | survived | `source = ActivityWatch(AWClient(args.aw_url))` → `source = ActivityWatch(AWClient(None))` |
| `x_cmd_backfill__mutmut_50` | survived | `print("no ActivityWatch sources found (no window, AFK or web buckets)")` → `print(None)` |
| `x_cmd_backfill__mutmut_52` | survived | `print("no ActivityWatch sources found (no window, AFK or web buckets)")` → `print("no activitywatch sources found (no window, afk or web buckets)")` |
| `x_cmd_backfill__mutmut_53` | survived | `print("no ActivityWatch sources found (no window, AFK or web buckets)")` → `print("NO ACTIVITYWATCH SOURCES FOUND (NO WINDOW, AFK OR WEB BUCKETS)")` |
| `x_cmd_backfill__mutmut_54` | survived | `return 0` → `return 1` |
| `x_cmd_backfill__mutmut_55` | survived | `verb = "Dry run: would backfill" if args.dry_run else "Backfilling"` → `verb = None` |
| `x_cmd_backfill__mutmut_56` | survived | `verb = "Dry run: would backfill" if args.dry_run else "Backfilling"` → `verb = "Dry run: would backfill" if (args.dry_run) and False else "Backfilling"` |
| `x_cmd_backfill__mutmut_57` | survived | `verb = "Dry run: would backfill" if args.dry_run else "Backfilling"` → `verb = "Dry run: would backfill" if (args.dry_run) or True else "Backfilling"` |
| `x_cmd_backfill__mutmut_59` | survived | `verb = "Dry run: would backfill" if args.dry_run else "Backfilling"` → `verb = "dry run: would backfill" if args.dry_run else "Backfilling"` |
| `x_cmd_backfill__mutmut_60` | survived | `verb = "Dry run: would backfill" if args.dry_run else "Backfilling"` → `verb = "DRY RUN: WOULD BACKFILL" if args.dry_run else "Backfilling"` |
| `x_cmd_backfill__mutmut_61` | survived | `verb = "Dry run: would backfill" if args.dry_run else "Backfilling"` → `verb = "Dry run: would backfill" if args.dry_run else "XXBackfillingXX"` |
| `x_cmd_backfill__mutmut_62` | survived | `verb = "Dry run: would backfill" if args.dry_run else "Backfilling"` → `verb = "Dry run: would backfill" if args.dry_run else "backfilling"` |
| `x_cmd_backfill__mutmut_63` | survived | `verb = "Dry run: would backfill" if args.dry_run else "Backfilling"` → `verb = "Dry run: would backfill" if args.dry_run else "BACKFILLING"` |
| `x_cmd_backfill__mutmut_64` | survived | `width = duration(BACKFILL_CHUNK.total_seconds())` → `width = None` |
| `x_cmd_backfill__mutmut_66` | survived | `print(f"{verb} {args.aw_url} into {db_path} ({width} chunks)", flush=True)` → `print(None, flush=True)` |
| `x_cmd_backfill__mutmut_67` | survived | `print(f"{verb} {args.aw_url} into {db_path} ({width} chunks)", flush=True)` → `print(f"{verb} {args.aw_url} into {db_path} ({width} chunks)", flush=None)` |
| `x_cmd_backfill__mutmut_68` | survived | `print(f"{verb} {args.aw_url} into {db_path} ({width} chunks)", flush=True)` → `print(flush=True)` |
| `x_cmd_backfill__mutmut_69` | survived | `print(f"{verb} {args.aw_url} into {db_path} ({width} chunks)", flush=True)` → `print(f"{verb} {args.aw_url} into {db_path} ({width} chunks)", )` |
| `x_cmd_backfill__mutmut_70` | survived | `print(f"{verb} {args.aw_url} into {db_path} ({width} chunks)", flush=True)` → `print(f"{verb} {args.aw_url} into {db_path} ({width} chunks)", flush=False)` |
| `x_cmd_backfill__mutmut_83` | survived | `return _backfill(store.conn, source, plans, db_path)` → `return _backfill(store.conn, source, plans, None)` |
| `x_cmd_backfill__mutmut_93` | survived | `return store_unavailable(created)` → `return store_unavailable(None)` |
| `x_cmd_backfill__mutmut_97` | survived | `return _backfill(created.conn, source, plans, db_path)` → `return _backfill(created.conn, source, plans, None)` |

### computer_history.cli.db

| mutant | status | change |
|---|---|---|
| `x__unavailable_reason__mutmut_6` | survived | `raise ValueError(f"{store.path} is ready")` → `raise ValueError(None)` |

### computer_history.cli.formatting

| mutant | status | change |
|---|---|---|
| `x_ago__mutmut_10` | survived | `return f"{when(value)} ({duration(-seconds)} ahead of now)"` → `return f"{when(value)} ({duration(+seconds)} ahead of now)"` |
| `x_ago__mutmut_2` | survived | `return "never"` → `return "XXneverXX"` |
| `x_ago__mutmut_3` | survived | `return "never"` → `return "NEVER"` |
| `x_ago__mutmut_6` | survived | `if seconds < 0:` → `if seconds <= 0:` |
| `x_ago__mutmut_8` | survived | `return f"{when(value)} ({duration(-seconds)} ahead of now)"` → `return f"{when(None)} ({duration(-seconds)} ahead of now)"` |
| `x_ago__mutmut_9` | survived | `return f"{when(value)} ({duration(-seconds)} ahead of now)"` → `return f"{when(value)} ({duration(None)} ahead of now)"` |
| `x_app_name__mutmut_1` | survived | `return "(no name)" if value is None else "".join(c for c in value if c.isprintable())` → `return "(no name)" if (value is None) and False else "".join(c for c in value if c.isprintable())` |
| `x_app_name__mutmut_4` | survived | `return "(no name)" if value is None else "".join(c for c in value if c.isprintable())` → `return "(NO NAME)" if value is None else "".join(c for c in value if c.isprintable())` |
| `x_db_size__mutmut_10` | survived | `size += f" + {human_size(wal.stat().st_size)} WAL"` → `size -= f" + {human_size(wal.stat().st_size)} WAL"` |
| `x_db_size__mutmut_11` | survived | `size += f" + {human_size(wal.stat().st_size)} WAL"` → `size += f" + {human_size(None)} WAL"` |
| `x_db_size__mutmut_6` | survived | `wal = path.with_name(path.name + "-wal")` → `wal = path.with_name(path.name + "XX-walXX")` |
| `x_db_size__mutmut_7` | survived | `wal = path.with_name(path.name + "-wal")` → `wal = path.with_name(path.name + "-WAL")` |
| `x_db_size__mutmut_9` | survived | `size += f" + {human_size(wal.stat().st_size)} WAL"` → `size = f" + {human_size(wal.stat().st_size)} WAL"` |
| `x_human_size__mutmut_1` | survived | `if n < 1024:` → `if n <= 1024:` |
| `x_human_size__mutmut_10` | survived | `if value < 1024:` → `if value <= 1024:` |
| `x_human_size__mutmut_11` | survived | `if value < 1024:` → `if value < 1025:` |
| `x_human_size__mutmut_14` | survived | `value /= 1024` → `value /= 1025` |
| `x_human_size__mutmut_2` | survived | `if n < 1024:` → `if n < 1025:` |
| `x_human_size__mutmut_5` | survived | `value = n / 1024` → `value = n / 1025` |
| `x_lag__mutmut_2` | survived | `if seconds < 0:` → `if seconds <= 0:` |
| `x_lag__mutmut_3` | survived | `if seconds < 0:` → `if seconds < 1:` |
| `x_when__mutmut_7` | survived | `return "-" if value is None else value.astimezone().strftime("%Y-%m-%d %H:%M")` → `return "-" if value is None else value.astimezone().strftime("%y-%m-%d %h:%m")` |
| `x_when__mutmut_8` | survived | `return "-" if value is None else value.astimezone().strftime("%Y-%m-%d %H:%M")` → `return "-" if value is None else value.astimezone().strftime("%Y-%M-%D %H:%M")` |

### computer_history.cli.ingest

| mutant | status | change |
|---|---|---|
| `x__print_summary__mutmut_1` | survived | `if summary.outcomes or summary.ok:` → `if summary.outcomes and summary.ok:` |
| `x__print_summary__mutmut_12` | survived | `width = max((len(name) for name in summary.outcomes), default=0)` → `width = max((len(name) for name in summary.outcomes), default=None)` |
| `x__print_summary__mutmut_14` | survived | `width = max((len(name) for name in summary.outcomes), default=0)` → `width = max((len(name) for name in summary.outcomes), )` |
| `x__print_summary__mutmut_15` | survived | `width = max((len(name) for name in summary.outcomes), default=0)` → `width = max((len(name) for name in summary.outcomes), default=1)` |
| `x__print_summary__mutmut_27` | survived | `continue` → `break` |
| `x__print_summary__mutmut_34` | survived | `if failure.kind is not FailureKind.ADAPTER:` → `if failure.kind is FailureKind.ADAPTER:` |
| `x__print_summary__mutmut_35` | survived | `print(db_busy_hint(db_path), file=sys.stderr)` → `print(None, file=sys.stderr)` |
| `x__print_summary__mutmut_36` | survived | `print(db_busy_hint(db_path), file=sys.stderr)` → `print(db_busy_hint(db_path), file=None)` |
| `x__print_summary__mutmut_37` | survived | `print(db_busy_hint(db_path), file=sys.stderr)` → `print(file=sys.stderr)` |
| `x__print_summary__mutmut_38` | survived | `print(db_busy_hint(db_path), file=sys.stderr)` → `print(db_busy_hint(db_path), )` |
| `x__print_summary__mutmut_39` | survived | `print(db_busy_hint(db_path), file=sys.stderr)` → `print(db_busy_hint(None), file=sys.stderr)` |
| `x_cmd_ingest__mutmut_10` | survived | `sources = [ActivityWatch(AWClient(args.aw_url)), CaptureSpool(spool_path)]` → `sources = [ActivityWatch(AWClient(None)), CaptureSpool(spool_path)]` |
| `x_cmd_ingest__mutmut_21` | survived | `args.aw_url,` → `None,` |
| `x_cmd_ingest__mutmut_22` | survived | `spool_path,` → `None,` |
| `x_cmd_ingest__mutmut_24` | survived | `db_path,` → `None,` |
| `x_cmd_ingest__mutmut_31` | survived | `"watching %s and %s every %ds into %s (Ctrl-C to stop)",` → `"watching %s and %s every %ds into %s (ctrl-c to stop)",` |
| `x_cmd_ingest__mutmut_35` | survived | `watch(conn, sources, report=log_cycle)` → `watch(conn, sources, report=None)` |
| `x_cycle_line__mutmut_5` | survived | `f"{name} +{o.inserted} ({o.skipped} dup, {o.held_back} held{_rejected(o, ', ')})"` → `f"{name} +{o.inserted} ({o.skipped} dup, {o.held_back} held{_rejected(o, None)})"` |

### computer_history.cli.rebuild

| mutant | status | change |
|---|---|---|
| `x__id_sample__mutmut_6` | survived | `text = ", ".join(str(i) for i in ids) or "-"` → `text = ", ".join(str(i) for i in ids) or "XX-XX"` |
| `x__id_sample__mutmut_7` | survived | `if total > len(ids):` → `if total >= len(ids):` |
| `x_cmd_rebuild_signals__mutmut_20` | survived | `f"  first failing observation ids: {_id_sample(exc.failed_ids, exc.failed)}",` → `None,` |
| `x_cmd_rebuild_signals__mutmut_22` | survived | `f"  first failing observation ids: {_id_sample(exc.failed_ids, exc.failed)}",` → `` |
| `x_cmd_rebuild_signals__mutmut_41` | survived | `" rebuild with the version that ingested it",` → `" REBUILD WITH THE VERSION THAT INGESTED IT",` |
| `x_cmd_rebuild_signals__mutmut_43` | survived | `print(f"rebuild-signals failed, signals unchanged: {exc}", file=sys.stderr)` → `print(None, file=sys.stderr)` |
| `x_cmd_rebuild_signals__mutmut_44` | survived | `print(f"rebuild-signals failed, signals unchanged: {exc}", file=sys.stderr)` → `print(f"rebuild-signals failed, signals unchanged: {exc}", file=None)` |
| `x_cmd_rebuild_signals__mutmut_45` | survived | `print(f"rebuild-signals failed, signals unchanged: {exc}", file=sys.stderr)` → `print(file=sys.stderr)` |
| `x_cmd_rebuild_signals__mutmut_46` | survived | `print(f"rebuild-signals failed, signals unchanged: {exc}", file=sys.stderr)` → `print(f"rebuild-signals failed, signals unchanged: {exc}", )` |
| `x_cmd_rebuild_signals__mutmut_47` | survived | `print(db_busy_hint(db_path), file=sys.stderr)` → `print(None, file=sys.stderr)` |
| `x_cmd_rebuild_signals__mutmut_48` | survived | `print(db_busy_hint(db_path), file=sys.stderr)` → `print(db_busy_hint(db_path), file=None)` |
| `x_cmd_rebuild_signals__mutmut_49` | survived | `print(db_busy_hint(db_path), file=sys.stderr)` → `print(file=sys.stderr)` |
| `x_cmd_rebuild_signals__mutmut_5` | survived | `store = open_store(db_path, Purpose.WRITE_EXISTING)` → `store = open_store(db_path, None)` |
| `x_cmd_rebuild_signals__mutmut_50` | survived | `print(db_busy_hint(db_path), file=sys.stderr)` → `print(db_busy_hint(db_path), )` |
| `x_cmd_rebuild_signals__mutmut_51` | survived | `print(db_busy_hint(db_path), file=sys.stderr)` → `print(db_busy_hint(None), file=sys.stderr)` |
| `x_cmd_rebuild_signals__mutmut_52` | survived | `return 1` → `return 2` |

### computer_history.cli.sources

| mutant | status | change |
|---|---|---|
| `x_source_failed__mutmut_3` | survived | `where = f" on {stream}" if stream else ""` → `where = f" on {stream}" if (stream) or True else ""` |
| `x_source_failed__mutmut_4` | survived | `where = f" on {stream}" if stream else ""` → `where = f" on {stream}" if stream else "XXXX"` |

### computer_history.cli.status

| mutant | status | change |
|---|---|---|
| `x__alive__mutmut_10` | survived | `if health.alive == "no":` → `if health.alive == "XXnoXX":` |
| `x__alive__mutmut_11` | survived | `if health.alive == "no":` → `if health.alive == "NO":` |
| `x__print_agent__mutmut_10` | survived | `print("Capture agent:")` → `print(None)` |
| `x__print_agent__mutmut_12` | survived | `print("Capture agent:")` → `print("capture agent:")` |
| `x__print_agent__mutmut_13` | survived | `print("Capture agent:")` → `print("CAPTURE AGENT:")` |
| `x__print_agreement__mutmut_11` | survived | `print("  app agreement no captures to check")` → `print(None)` |
| `x__print_agreement__mutmut_13` | survived | `print("  app agreement no captures to check")` → `print("  APP AGREEMENT NO CAPTURES TO CHECK")` |
| `x__print_agreement__mutmut_3` | survived | `print("  app agreement no captures to check yet")` → `print(None)` |
| `x__print_agreement__mutmut_5` | survived | `print("  app agreement no captures to check yet")` → `print("  APP AGREEMENT NO CAPTURES TO CHECK YET")` |
| `x__print_capture_gaps__mutmut_17` | survived | `if not warnings:` → `if warnings:` |
| `x__print_capture_gaps__mutmut_18` | survived | `print(f"  {AX_TEXT_SOURCE}: no gaps since {when(coverage.start)}")` → `print(None)` |
| `x__print_capture_gaps__mutmut_19` | survived | `print(f"  {AX_TEXT_SOURCE}: no gaps since {when(coverage.start)}")` → `print(f"  {AX_TEXT_SOURCE}: no gaps since {when(None)}")` |
| `x__print_capture_gaps__mutmut_21` | survived | `f"  warning: no {AX_TEXT_SOURCE} coverage from {when(gap.start)} to {when(gap.end)}"` → `f"  warning: no {AX_TEXT_SOURCE} coverage from {when(None)} to {when(gap.end)}"` |
| `x__print_capture_gaps__mutmut_22` | survived | `f"  warning: no {AX_TEXT_SOURCE} coverage from {when(gap.start)} to {when(gap.end)}"` → `f"  warning: no {AX_TEXT_SOURCE} coverage from {when(gap.start)} to {when(None)}"` |
| `x__print_capture_gaps__mutmut_24` | survived | `if len(warnings) > MAX_GAPS_SHOWN:` → `if len(warnings) >= MAX_GAPS_SHOWN:` |
| `x__print_capture_gaps__mutmut_25` | survived | `print(f"  warning: ... and {len(warnings) - MAX_GAPS_SHOWN} more {AX_TEXT_SOURCE} gaps")` → `print(None)` |
| `x__print_capture_gaps__mutmut_26` | survived | `print(f"  warning: ... and {len(warnings) - MAX_GAPS_SHOWN} more {AX_TEXT_SOURCE} gaps")` → `print(f"  warning: ... and {len(warnings) + MAX_GAPS_SHOWN} more {AX_TEXT_SOURCE} gaps")` |
| `x__print_capture_gaps__mutmut_3` | survived | `print(f"  {AX_TEXT_SOURCE}: no settled span to check yet")` → `print(None)` |
| `x__print_capture_gaps__mutmut_5` | survived | `f"  {AX_TEXT_SOURCE} from {when(coverage.start)} to {when(coverage.end)} (unobserved:"` → `f"  {AX_TEXT_SOURCE} from {when(None)} to {when(coverage.end)} (unobserved:"` |
| `x__print_capture_gaps__mutmut_6` | survived | `f"  {AX_TEXT_SOURCE} from {when(coverage.start)} to {when(coverage.end)} (unobserved:"` → `f"  {AX_TEXT_SOURCE} from {when(coverage.start)} to {when(None)} (unobserved:"` |
| `x__print_capture_gaps__mutmut_9` | survived | `" not paused):"` → `" NOT PAUSED):"` |
| `x__print_counts__mutmut_1` | survived | `print("Rows:")` → `print(None)` |
| `x__print_counts__mutmut_11` | survived | `ordered = sorted(counts, key=lambda name: (name not in ("observations", "signals"), name))` → `ordered = sorted(counts, key=lambda name: (name in ("observations", "signals"), name))` |
| `x__print_counts__mutmut_12` | survived | `ordered = sorted(counts, key=lambda name: (name not in ("observations", "signals"), name))` → `ordered = sorted(counts, key=lambda name: (name not in ("XXobservationsXX", "signals"), name))` |
| `x__print_counts__mutmut_13` | survived | `ordered = sorted(counts, key=lambda name: (name not in ("observations", "signals"), name))` → `ordered = sorted(counts, key=lambda name: (name not in ("OBSERVATIONS", "signals"), name))` |
| `x__print_counts__mutmut_14` | survived | `ordered = sorted(counts, key=lambda name: (name not in ("observations", "signals"), name))` → `ordered = sorted(counts, key=lambda name: (name not in ("observations", "XXsignalsXX"), name))` |
| `x__print_counts__mutmut_15` | survived | `ordered = sorted(counts, key=lambda name: (name not in ("observations", "signals"), name))` → `ordered = sorted(counts, key=lambda name: (name not in ("observations", "SIGNALS"), name))` |
| `x__print_counts__mutmut_18` | survived | `width = max((len(name) for name in ordered), default=0)` → `width = max((len(name) for name in ordered), default=None)` |
| `x__print_counts__mutmut_2` | survived | `print("Rows:")` → `print("XXRows:XX")` |
| `x__print_counts__mutmut_20` | survived | `width = max((len(name) for name in ordered), default=0)` → `width = max((len(name) for name in ordered), )` |
| `x__print_counts__mutmut_21` | survived | `width = max((len(name) for name in ordered), default=0)` → `width = max((len(name) for name in ordered), default=1)` |
| `x__print_counts__mutmut_3` | survived | `print("Rows:")` → `print("rows:")` |
| `x__print_counts__mutmut_4` | survived | `print("Rows:")` → `print("ROWS:")` |
| `x__print_counts__mutmut_7` | survived | `ordered = sorted(counts, key=lambda name: (name not in ("observations", "signals"), name))` → `ordered = sorted(counts, key=None)` |
| `x__print_counts__mutmut_9` | survived | `ordered = sorted(counts, key=lambda name: (name not in ("observations", "signals"), name))` → `ordered = sorted(counts, )` |
| `x__print_gaps__mutmut_11` | survived | `if s.source == AX_TEXT_SOURCE and health.reported:` → `if s.source == AX_TEXT_SOURCE or health.reported:` |
| `x__print_gaps__mutmut_12` | survived | `if s.source == AX_TEXT_SOURCE and health.reported:` → `if s.source != AX_TEXT_SOURCE and health.reported:` |
| `x__print_gaps__mutmut_14` | survived | `continue` → `break` |
| `x__print_gaps__mutmut_18` | survived | `if end is None or first is None:` → `if end is None and first is None:` |
| `x__print_gaps__mutmut_29` | survived | `if start >= end:` → `if start > end:` |
| `x__print_gaps__mutmut_30` | survived | `print(f"  {s.source}: no settled span to check yet")` → `print(None)` |
| `x__print_gaps__mutmut_31` | survived | `continue` → `break` |
| `x__print_gaps__mutmut_45` | survived | `print(f"  {s.source}: no gaps since {when(start)}")` → `print(f"  {s.source}: no gaps since {when(None)}")` |
| `x__print_gaps__mutmut_47` | survived | `f"  warning: no {s.source} coverage from {when(gap.start)} to"` → `f"  warning: no {s.source} coverage from {when(None)} to"` |
| `x__print_gaps__mutmut_48` | survived | `f" {when(gap.end)} ({duration(gap.seconds)})"` → `f" {when(None)} ({duration(gap.seconds)})"` |
| `x__print_gaps__mutmut_50` | survived | `if len(gaps) > MAX_GAPS_SHOWN:` → `if len(gaps) >= MAX_GAPS_SHOWN:` |
| `x__print_sources__mutmut_12` | survived | `f"  latest end {when(s.latest_ended_at)}"` → `f"  latest end {when(None)}"` |
| `x__print_sources__mutmut_13` | survived | `f"  settled until {when(s.settled_until)} ({_freshness(s, now)})"` → `f"  settled until {when(None)} ({_freshness(s, now)})"` |
| `x__print_sources__mutmut_25` | survived | `" still-growing window/tab/AFK event, so lag includes that event's length)"` → `" still-growing window/tab/afk event, so lag includes that event's length)"` |
| `x__print_sources__mutmut_26` | survived | `" still-growing window/tab/AFK event, so lag includes that event's length)"` → `" STILL-GROWING WINDOW/TAB/AFK EVENT, SO LAG INCLUDES THAT EVENT'S LENGTH)"` |
| `x__spool__mutmut_18` | survived | `oldest = duration(age) if age >= 0 else f"{duration(-age)} ahead of now"` → `oldest = duration(age) if age > 0 else f"{duration(-age)} ahead of now"` |
| `x__spool__mutmut_19` | survived | `oldest = duration(age) if age >= 0 else f"{duration(-age)} ahead of now"` → `oldest = duration(age) if age >= 1 else f"{duration(-age)} ahead of now"` |
| `x_cmd_status__mutmut_12` | survived | `client = AWClient(args.aw_url, timeout=STATUS_AW_TIMEOUT_SECONDS)` → `client = AWClient(args.aw_url, timeout=None)` |
| `x_cmd_status__mutmut_14` | survived | `client = AWClient(args.aw_url, timeout=STATUS_AW_TIMEOUT_SECONDS)` → `client = AWClient(args.aw_url, )` |
| `x_cmd_status__mutmut_30` | survived | `names = ", ".join(streams) or "none of window/AFK/web"` → `names = ", ".join(streams) or "none of window/afk/web"` |
| `x_cmd_status__mutmut_40` | survived | `print(aw_line)` → `print(None)` |
| `x_cmd_status__mutmut_43` | survived | `print(aw_line)` → `print(None)` |
| `x_cmd_status__mutmut_60` | survived | `client if aw_error is None else None,` → `None,` |
| `x_cmd_status__mutmut_72` | survived | `min_gap_seconds=MIN_GAP_SECONDS, / )` → `)` |
| `x_cmd_status__mutmut_73` | survived | `client if aw_error is None else None,` → `client if (aw_error is None) and False else None,` |
| `x_cmd_status__mutmut_74` | survived | `client if aw_error is None else None,` → `client if (aw_error is None) or True else None,` |
| `x_cmd_status__mutmut_75` | survived | `client if aw_error is None else None,` → `client if aw_error is not None else None,` |

### computer_history.sources.activitywatch.adapter

| mutant | status | change |
|---|---|---|
| `x__as_pull__mutmut_2` | survived | `position = None if pulled.frontier is None else position_at(pulled.frontier)` → `position = None if (pulled.frontier is None) and False else position_at(pulled.frontier)` |
| `xǁActivityWatchǁ__init____mutmut_2` | survived | `self._buckets: Mapping[str, Any] = {}` → `self._buckets: Mapping[str, Any] = None` |
| `xǁActivityWatchǁ_discover__mutmut_3` | survived | `found = discover_sources(self.client, buckets=self._buckets)` → `found = discover_sources(None, buckets=self._buckets)` |

### computer_history.sources.activitywatch.afk

| mutant | status | change |
|---|---|---|
| `x__span__mutmut_13` | survived | `return AfkSpan(start, end, AFK_STATUSES[status])` → `return AfkSpan(start, end, None)` |
| `x__span__mutmut_8` | survived | `if not isinstance(status, str) or status not in AFK_STATUSES:` → `if not isinstance(status, str) and status not in AFK_STATUSES:` |
| `x_stored_afk_spans__mutmut_18` | survived | `if isinstance(row.values[0], str) and row.values[0] in AFK_STATUSES` → `if isinstance(row.values[0], str) or row.values[0] in AFK_STATUSES` |
| `x_stored_afk_spans__mutmut_3` | survived | `AfkSpan(row.started_at, row.ended_at, AFK_STATUSES[row.values[0]])` → `AfkSpan(row.started_at, row.ended_at, None)` |

### computer_history.sources.activitywatch.client

| mutant | status | change |
|---|---|---|
| `xǁAWClientǁ__init____mutmut_4` | survived | `self.base_url = base_url.rstrip("/")` → `self.base_url = base_url.rstrip("XX/XX")` |
| `xǁAWClientǁ__init____mutmut_5` | survived | `self.timeout = timeout` → `self.timeout = None` |
| `xǁAWClientǁ_bucket_path__mutmut_7` | survived | `return "/buckets/" + quote(bucket_id, safe="")` → `return "/buckets/" + quote(bucket_id, )` |
| `xǁAWClientǁ_bucket_path__mutmut_8` | survived | `return "/buckets/" + quote(bucket_id, safe="")` → `return "/buckets/" + quote(bucket_id, safe="XXXX")` |
| `xǁAWClientǁ_get__mutmut_10` | survived | `request = Request(url, headers={"Accept": "application/json"}, method="GET")` → `request = Request(url, headers={"XXAcceptXX": "application/json"}, method="GET")` |
| `xǁAWClientǁ_get__mutmut_11` | survived | `request = Request(url, headers={"Accept": "application/json"}, method="GET")` → `request = Request(url, headers={"accept": "application/json"}, method="GET")` |
| `xǁAWClientǁ_get__mutmut_12` | survived | `request = Request(url, headers={"Accept": "application/json"}, method="GET")` → `request = Request(url, headers={"ACCEPT": "application/json"}, method="GET")` |
| `xǁAWClientǁ_get__mutmut_13` | survived | `request = Request(url, headers={"Accept": "application/json"}, method="GET")` → `request = Request(url, headers={"Accept": "XXapplication/jsonXX"}, method="GET")` |
| `xǁAWClientǁ_get__mutmut_14` | survived | `request = Request(url, headers={"Accept": "application/json"}, method="GET")` → `request = Request(url, headers={"Accept": "APPLICATION/JSON"}, method="GET")` |
| `xǁAWClientǁ_get__mutmut_18` | survived | `with urlopen(request, timeout=self.timeout) as response:` → `with urlopen(request, timeout=None) as response:` |
| `xǁAWClientǁ_get__mutmut_24` | survived | `raise _NotFound(f"ActivityWatch 404 for {url}") from exc` → `raise _NotFound(None) from exc` |
| `xǁAWClientǁ_get__mutmut_25` | survived | `raise AWError(f"ActivityWatch HTTP {exc.code} for {url}") from exc` → `raise AWError(None) from exc` |
| `xǁAWClientǁ_get__mutmut_26` | survived | `raise AWError(f"ActivityWatch unreachable at {self.base_url}: {exc}") from exc` → `raise AWError(None) from exc` |
| `xǁAWClientǁ_get__mutmut_27` | survived | `raise AWError(f"ActivityWatch returned invalid JSON for {url}") from exc` → `raise AWError(None) from exc` |
| `xǁAWClientǁ_get__mutmut_6` | survived | `request = Request(url, headers={"Accept": "application/json"}, method="GET")` → `request = Request(url, headers={"Accept": "application/json"}, method=None)` |
| `xǁAWClientǁ_get__mutmut_8` | survived | `request = Request(url, headers={"Accept": "application/json"}, method="GET")` → `request = Request(url, method="GET")` |
| `xǁAWClientǁ_get__mutmut_9` | survived | `request = Request(url, headers={"Accept": "application/json"}, method="GET")` → `request = Request(url, headers={"Accept": "application/json"}, )` |
| `xǁAWClientǁget_buckets__mutmut_1` | survived | `buckets = self._get("/buckets/")` → `buckets = None` |
| `xǁAWClientǁget_buckets__mutmut_3` | survived | `buckets = self._get("/buckets/")` → `buckets = self._get("XX/buckets/XX")` |
| `xǁAWClientǁget_buckets__mutmut_4` | survived | `buckets = self._get("/buckets/")` → `buckets = self._get("/BUCKETS/")` |
| `xǁAWClientǁget_buckets__mutmut_5` | survived | `if not isinstance(buckets, dict):` → `if isinstance(buckets, dict):` |
| `xǁAWClientǁget_buckets__mutmut_6` | survived | `raise AWError("ActivityWatch /buckets/ did not return an object")` → `raise AWError(None)` |
| `xǁAWClientǁget_buckets__mutmut_7` | survived | `raise AWError("ActivityWatch /buckets/ did not return an object")` → `raise AWError("XXActivityWatch /buckets/ did not return an objectXX")` |
| `xǁAWClientǁget_buckets__mutmut_8` | survived | `raise AWError("ActivityWatch /buckets/ did not return an object")` → `raise AWError("activitywatch /buckets/ did not return an object")` |
| `xǁAWClientǁget_buckets__mutmut_9` | survived | `raise AWError("ActivityWatch /buckets/ did not return an object")` → `raise AWError("ACTIVITYWATCH /BUCKETS/ DID NOT RETURN AN OBJECT")` |
| `xǁAWClientǁget_event__mutmut_5` | survived | `event = self._get(f"{self._bucket_path(bucket_id)}/events/{quote(str(event_id))}")` → `event = self._get(f"{self._bucket_path(bucket_id)}/events/{quote(str(None))}")` |
| `xǁAWClientǁget_event__mutmut_6` | survived | `if not isinstance(event, dict):` → `if isinstance(event, dict):` |
| `xǁAWClientǁget_event__mutmut_7` | survived | `raise AWError(f"ActivityWatch event {bucket_id}/{event_id} was not an object")` → `raise AWError(None)` |
| `xǁAWClientǁget_events__mutmut_19` | survived | `raise AWError(f"ActivityWatch events for {bucket_id!r} were not a list")` → `raise AWError(None)` |

### computer_history.sources.activitywatch.discovery

| mutant | status | change |
|---|---|---|
| `x_discover_sources__mutmut_14` | survived | `source = BUCKET_TYPE_SOURCES.get(bucket_type) if isinstance(bucket_type, str) else None` → `source = BUCKET_TYPE_SOURCES.get(bucket_type) if (isinstance(bucket_type, str)) or True else None` |
| `x_discover_sources__mutmut_8` | survived | `bucket_type = meta.get("type") if isinstance(meta, Mapping) else None` → `bucket_type = meta.get("type") if (isinstance(meta, Mapping)) or True else None` |

### computer_history.sources.activitywatch.frontmost

| mutant | status | change |
|---|---|---|
| `x__app__mutmut_2` | survived | `return clean_text(value) if isinstance(value, str) else None` → `return clean_text(value) if (isinstance(value, str)) or True else None` |
| `x__span__mutmut_9` | survived | `return None if app is None else AppSpan(start, end, app)` → `return None if (app is None) and False else AppSpan(start, end, app)` |
| `x_stored_app_spans__mutmut_23` | survived | `if on_host(row.source_id.rpartition("/")[0], hostname)` → `if on_host(row.source_id.partition("/")[0], hostname)` |

### computer_history.sources.activitywatch.history

| mutant | status | change |
|---|---|---|
| `x__event_before__mutmut_15` | survived | `start.isoformat(),` → `None,` |
| `x__event_before__mutmut_16` | survived | `exc,` → `None,` |
| `x__event_before__mutmut_21` | survived | `"malformed ActivityWatch event in %s before %s: %s; treating it as"` → `"XXmalformed ActivityWatch event in %s before %s: %s; treating it asXX"` |
| `x__event_before__mutmut_24` | survived | `" history the backfill does not cover",` → `"XX history the backfill does not coverXX",` |
| `x__event_before__mutmut_25` | survived | `" history the backfill does not cover",` → `" HISTORY THE BACKFILL DOES NOT COVER",` |
| `x__event_before__mutmut_27` | survived | `if began < start:` → `if began <= start:` |
| `x__event_before__mutmut_6` | survived | `for raw in client.get_events(bucket_id, end=start - _PROBE_GUARD, limit=1):` → `for raw in client.get_events(bucket_id, end=start - _PROBE_GUARD, ):` |
| `x__event_before__mutmut_8` | survived | `for raw in client.get_events(bucket_id, end=start - _PROBE_GUARD, limit=1):` → `for raw in client.get_events(bucket_id, end=start - _PROBE_GUARD, limit=2):` |
| `x_history_floor__mutmut_13` | survived | `log.warning("bucket %s has no usable 'created' time (%r)", bucket_id, value)` → `log.warning("bucket %s has no usable 'created' time (%r)", None, value)` |
| `x_history_floor__mutmut_14` | survived | `log.warning("bucket %s has no usable 'created' time (%r)", bucket_id, value)` → `log.warning("bucket %s has no usable 'created' time (%r)", bucket_id, None)` |
| `x_history_floor__mutmut_18` | survived | `log.warning("bucket %s has no usable 'created' time (%r)", bucket_id, value)` → `log.warning("XXbucket %s has no usable 'created' time (%r)XX", bucket_id, value)` |
| `x_history_floor__mutmut_23` | survived | `return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)` → `return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(None)` |
| `x_history_floor__mutmut_29` | survived | `return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)` → `return local.replace(hour=0, second=0, microsecond=0).astimezone(UTC)` |
| `x_history_floor__mutmut_30` | survived | `return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)` → `return local.replace(hour=0, minute=0, microsecond=0).astimezone(UTC)` |
| `x_history_floor__mutmut_31` | survived | `return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)` → `return local.replace(hour=0, minute=0, second=0, ).astimezone(UTC)` |
| `x_history_floor__mutmut_6` | survived | `value = meta.get("created") if isinstance(meta, Mapping) else None` → `value = meta.get("created") if (isinstance(meta, Mapping)) or True else None` |

### computer_history.sources.activitywatch.normalize

| mutant | status | change |
|---|---|---|
| `x_project_signal__mutmut_3` | survived | `raise ValueError(f"not an ActivityWatch content source: {source!r}")` → `raise ValueError(None)` |
| `x_project_signal__mutmut_8` | survived | `raw_data = payload.get("data") if isinstance(payload, Mapping) else None` → `raw_data = payload.get("data") if (isinstance(payload, Mapping)) or True else None` |

### computer_history.sources.activitywatch.pull

| mutant | status | change |
|---|---|---|
| `x__parse_event__mutmut_13` | survived | `log.warning("skipping malformed ActivityWatch event in %s: %s", bucket_id, exc)` → `log.warning("skipping malformed ActivityWatch event in %s: %s", None, exc)` |
| `x__parse_event__mutmut_14` | survived | `log.warning("skipping malformed ActivityWatch event in %s: %s", bucket_id, exc)` → `log.warning("skipping malformed ActivityWatch event in %s: %s", bucket_id, None)` |
| `x__parse_event__mutmut_18` | survived | `log.warning("skipping malformed ActivityWatch event in %s: %s", bucket_id, exc)` → `log.warning("XXskipping malformed ActivityWatch event in %s: %sXX", bucket_id, exc)` |
| `x__parse_event__mutmut_19` | survived | `log.warning("skipping malformed ActivityWatch event in %s: %s", bucket_id, exc)` → `log.warning("skipping malformed activitywatch event in %s: %s", bucket_id, exc)` |
| `x__parse_event__mutmut_4` | survived | `if isinstance(event_id, bool) or not isinstance(event_id, int \| str) or event_id == "":` → `if isinstance(event_id, bool) or not isinstance(event_id, int \| str) and event_id == "":` |
| `x__parse_event__mutmut_5` | survived | `if isinstance(event_id, bool) or not isinstance(event_id, int \| str) or event_id == "":` → `if isinstance(event_id, bool) and not isinstance(event_id, int \| str) or event_id == "":` |
| `x__parse_event__mutmut_8` | survived | `if isinstance(event_id, bool) or not isinstance(event_id, int \| str) or event_id == "":` → `if isinstance(event_id, bool) or not isinstance(event_id, int \| str) or event_id == "XXXX":` |
| `x__parse_event__mutmut_9` | survived | `raise ValueError(f"bad id {event_id!r}")` → `raise ValueError(None)` |
| `x__refetch__mutmut_10` | survived | `log.warning("ActivityWatch event %s/%s vanished during the pull", bucket_id, clipped.id)` → `log.warning(bucket_id, clipped.id)` |
| `x__refetch__mutmut_11` | survived | `log.warning("ActivityWatch event %s/%s vanished during the pull", bucket_id, clipped.id)` → `log.warning("ActivityWatch event %s/%s vanished during the pull", clipped.id)` |
| `x__refetch__mutmut_12` | survived | `log.warning("ActivityWatch event %s/%s vanished during the pull", bucket_id, clipped.id)` → `log.warning("ActivityWatch event %s/%s vanished during the pull", bucket_id, )` |
| `x__refetch__mutmut_13` | survived | `log.warning("ActivityWatch event %s/%s vanished during the pull", bucket_id, clipped.id)` → `log.warning("XXActivityWatch event %s/%s vanished during the pullXX", bucket_id, clipped.id)` |
| `x__refetch__mutmut_14` | survived | `log.warning("ActivityWatch event %s/%s vanished during the pull", bucket_id, clipped.id)` → `log.warning("activitywatch event %s/%s vanished during the pull", bucket_id, clipped.id)` |
| `x__refetch__mutmut_15` | survived | `log.warning("ActivityWatch event %s/%s vanished during the pull", bucket_id, clipped.id)` → `log.warning("ACTIVITYWATCH EVENT %S/%S VANISHED DURING THE PULL", bucket_id, clipped.id)` |
| `x__refetch__mutmut_18` | survived | `event = _parse_event(raw, bucket_id)` → `event = _parse_event(raw, None)` |
| `x__refetch__mutmut_22` | survived | `if event is not None and event.id != clipped.id:` → `if event is None and event.id != clipped.id:` |
| `x__refetch__mutmut_24` | survived | `raise AWError(f"ActivityWatch returned event {event.id} for {bucket_id}/{clipped.id}")` → `raise AWError(None)` |
| `x__refetch__mutmut_7` | survived | `log.warning("ActivityWatch event %s/%s vanished during the pull", bucket_id, clipped.id)` → `log.warning(None, bucket_id, clipped.id)` |
| `x__refetch__mutmut_8` | survived | `log.warning("ActivityWatch event %s/%s vanished during the pull", bucket_id, clipped.id)` → `log.warning("ActivityWatch event %s/%s vanished during the pull", None, clipped.id)` |
| `x__refetch__mutmut_9` | survived | `log.warning("ActivityWatch event %s/%s vanished during the pull", bucket_id, clipped.id)` → `log.warning("ActivityWatch event %s/%s vanished during the pull", bucket_id, None)` |
| `x_event_times__mutmut_11` | survived | `duration = float(raw.get("duration") or 0)` → `duration = float(raw.get("duration") or 1)` |
| `x_event_times__mutmut_17` | survived | `duration = duration if math.isfinite(duration) and duration > 0 else 0.0` → `duration = duration if math.isfinite(duration) and duration >= 0 else 0.0` |
| `x_event_times__mutmut_18` | survived | `duration = duration if math.isfinite(duration) and duration > 0 else 0.0` → `duration = duration if math.isfinite(duration) and duration > 1 else 0.0` |
| `x_newest_events__mutmut_1` | survived | `for source in discover_sources(client, buckets=buckets)` → `for source in discover_sources(None, buckets=buckets)` |
| `x_newest_events__mutmut_10` | survived | `for raw in client.get_events(bucket_id, limit=1)` → `for raw in client.get_events(bucket_id, limit=2)` |
| `x_newest_events__mutmut_9` | survived | `for raw in client.get_events(bucket_id, limit=1)` → `for raw in client.get_events(bucket_id, )` |
| `x_pull_bucket__mutmut_100` | survived | `continue` → `break` |
| `x_pull_bucket__mutmut_122` | survived | `return BucketPull(bucket_id, tuple(observations), frontier, len(held))` → `return BucketPull(None, tuple(observations), frontier, len(held))` |
| `x_pull_bucket__mutmut_18` | survived | `raise ValueError(f"empty pull range: [{start_dt.isoformat()}, {end_dt.isoformat()})")` → `raise ValueError(None)` |
| `x_pull_bucket__mutmut_28` | survived | `newest = _parse_event(newest_raw[0], bucket_id) if newest_raw else None` → `newest = None` |
| `x_pull_bucket__mutmut_29` | survived | `newest = _parse_event(newest_raw[0], bucket_id) if newest_raw else None` → `newest = _parse_event(newest_raw[0], bucket_id) if (newest_raw) and False else None` |
| `x_pull_bucket__mutmut_31` | survived | `newest = _parse_event(newest_raw[0], bucket_id) if newest_raw else None` → `newest = _parse_event(None, bucket_id) if newest_raw else None` |
| `x_pull_bucket__mutmut_32` | survived | `newest = _parse_event(newest_raw[0], bucket_id) if newest_raw else None` → `newest = _parse_event(newest_raw[0], None) if newest_raw else None` |
| `x_pull_bucket__mutmut_39` | survived | `end=end_dt,` → `end=None,` |
| `x_pull_bucket__mutmut_43` | survived | `end=end_dt,` → `` |
| `x_pull_bucket__mutmut_53` | survived | `events = [e for e in (_parse_event(raw, bucket_id) for raw in raw_events) if e is not None]` → `events = [e for e in (_parse_event(raw, None) for raw in raw_events) if e is not None]` |
| `x_pull_bucket__mutmut_59` | survived | `before = [e for e in events if e.start < start_dt]` → `before = [e for e in events if e.start <= start_dt]` |
| `x_pull_bucket__mutmut_78` | survived | `if newest is not None and latest_start is not None:` → `if newest is None and latest_start is not None:` |
| `x_pull_bucket__mutmut_90` | survived | `if event.end >= end_dt - _END_CLIP_TOLERANCE:` → `if event.end > end_dt - _END_CLIP_TOLERANCE:` |
| `x_resolve_now__mutmut_3` | survived | `return datetime.now(UTC) if now is None else to_utc(now)` → `return datetime.now(None) if now is None else to_utc(now)` |

### computer_history.sources.agent_health

| mutant | status | change |
|---|---|---|
| `x__afk_spans__mutmut_8` | survived | `if client is not None and buckets is not None:` → `if client is not None or buckets is not None:` |
| `x__app_spans__mutmut_10` | survived | `if client is not None and buckets is not None:` → `if client is not None or buckets is not None:` |
| `x__last_capture__mutmut_21` | survived | `return max(times, default=None)` → `return max(times, )` |
| `x__last_capture__mutmut_9` | survived | `times = [] if stored is None else [stored[0]]` → `times = [] if (stored is None) and False else [stored[0]]` |
| `x_capture_health__mutmut_1` | survived | `min_gap_seconds: float = 0,` → `min_gap_seconds: float = 1,` |
| `x_capture_health__mutmut_112` | survived | `if start < end:` → `if start <= end:` |
| `x_capture_health__mutmut_134` | survived | `conn, client, buckets, start - APP_TOLERANCE, end + APP_TOLERANCE, hostname` → `conn, client, buckets, start + APP_TOLERANCE, end + APP_TOLERANCE, hostname` |
| `x_capture_health__mutmut_135` | survived | `conn, client, buckets, start - APP_TOLERANCE, end + APP_TOLERANCE, hostname` → `conn, client, buckets, start - APP_TOLERANCE, end - APP_TOLERANCE, hostname` |
| `x_capture_health__mutmut_142` | survived | `paused_at_start=before is not None and before[1] == PAUSED_KIND,` → `paused_at_start=None,` |
| `x_capture_health__mutmut_150` | survived | `min_gap_seconds=min_gap_seconds, / )` → `)` |
| `x_capture_health__mutmut_153` | survived | `paused_at_start=before is not None and before[1] == PAUSED_KIND,` → `paused_at_start=before is not None and before[2] == PAUSED_KIND,` |
| `x_capture_health__mutmut_154` | survived | `paused_at_start=before is not None and before[1] == PAUSED_KIND,` → `paused_at_start=before is not None and before[1] != PAUSED_KIND,` |
| `x_capture_health__mutmut_157` | survived | `spool_error=spool_error,` → `spool_error=None,` |
| `x_capture_health__mutmut_18` | survived | `if summary is None or summary.earliest_started_at is None or stored is None:` → `if summary is None or summary.earliest_started_at is None and stored is None:` |
| `x_capture_health__mutmut_23` | survived | `return CaptureHealth(False, spool, spool_error)` → `return CaptureHealth(None, spool, spool_error)` |
| `x_capture_health__mutmut_25` | survived | `return CaptureHealth(False, spool, spool_error)` → `return CaptureHealth(False, spool, None)` |
| `x_capture_health__mutmut_31` | survived | `unstored = None if spool is None else spool.newest` → `unstored = None if (spool is None) and False else spool.newest` |
| `x_capture_health__mutmut_40` | survived | `newest = unstored if unstored is not None and unstored[0] > stored[0] else stored` → `newest = unstored if unstored is not None and unstored[0] >= stored[0] else stored` |
| `x_capture_health__mutmut_6` | survived | `spool, spool_error = None, str(exc)` → `spool, spool_error = None` |
| `x_capture_health__mutmut_60` | survived | `day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)` → `day_start = now.astimezone().replace(minute=0, second=0, microsecond=0)` |
| `x_capture_health__mutmut_61` | survived | `day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)` → `day_start = now.astimezone().replace(hour=0, second=0, microsecond=0)` |
| `x_capture_health__mutmut_62` | survived | `day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)` → `day_start = now.astimezone().replace(hour=0, minute=0, microsecond=0)` |
| `x_capture_health__mutmut_63` | survived | `day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)` → `day_start = now.astimezone().replace(hour=0, minute=0, second=0, )` |
| `x_capture_health__mutmut_64` | survived | `day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)` → `day_start = now.astimezone().replace(hour=1, minute=0, second=0, microsecond=0)` |
| `x_capture_health__mutmut_65` | survived | `day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)` → `day_start = now.astimezone().replace(hour=0, minute=1, second=0, microsecond=0)` |
| `x_capture_health__mutmut_66` | survived | `day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)` → `day_start = now.astimezone().replace(hour=0, minute=0, second=1, microsecond=0)` |
| `x_capture_health__mutmut_67` | survived | `day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)` → `day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=1)` |
| `x_capture_health__mutmut_7` | survived | `spool, spool_error = None, str(exc)` → `spool, spool_error = None, str(None)` |
| `x_capture_health__mutmut_75` | survived | `read_from = min(start - CAPTURE_TOLERANCE, day_start)` → `read_from = min(start + CAPTURE_TOLERANCE, day_start)` |
| `x_capture_health__mutmut_83` | survived | `before = newest_stored(conn, until=read_from)` → `before = None` |

### computer_history.sources.ax_text.adapter

| mutant | status | change |
|---|---|---|
| `x__move_aside__mutmut_12` | survived | `log.warning("moved spool file %s to %s: %s", path.name, target, reason)` → `log.warning("XXmoved spool file %s to %s: %sXX", path.name, target, reason)` |
| `x__move_aside__mutmut_6` | survived | `log.warning("moved spool file %s to %s: %s", path.name, target, reason)` → `log.warning("moved spool file %s to %s: %s", path.name, None, reason)` |
| `x__read_records__mutmut_18` | survived | `line = raw.decode("utf-8")` → `line = raw.decode("UTF-8")` |
| `x__read_records__mutmut_41` | survived | `if record.captured_at <= now and (latest is None or record.captured_at > latest):` → `if record.captured_at < now and (latest is None or record.captured_at > latest):` |
| `x__read_records__mutmut_44` | survived | `if record.captured_at <= now and (latest is None or record.captured_at > latest):` → `if record.captured_at <= now and (latest is None or record.captured_at >= latest):` |
| `x__read_records__mutmut_5` | survived | `first_problem = (0, "")` → `first_problem = None` |
| `x__read_records__mutmut_6` | survived | `first_problem = (0, "")` → `first_problem = (1, "")` |
| `x__read_records__mutmut_7` | survived | `first_problem = (0, "")` → `first_problem = (0, "XXXX")` |
| `xǁCaptureSpoolǁ_empty__mutmut_18` | survived | `return Pull((), 0, None, None, more=more, after_commit=after_commit)` → `return Pull((), 1, None, None, more=more, after_commit=after_commit)` |
| `xǁCaptureSpoolǁpull_after__mutmut_2` | survived | `raise SpoolError(f"the spool feeds {AX_TEXT_SOURCE!r}, not {stream!r}")` → `raise SpoolError(None)` |
| `xǁCaptureSpoolǁpull_after__mutmut_22` | survived | `return self._empty(path, _gone, more)` → `return self._empty(None, _gone, more)` |
| `xǁCaptureSpoolǁpull_after__mutmut_23` | survived | `return self._empty(path, _gone, more)` → `return self._empty(path, None, more)` |
| `xǁCaptureSpoolǁpull_after__mutmut_24` | survived | `return self._empty(path, _gone, more)` → `return self._empty(path, _gone, None)` |
| `xǁCaptureSpoolǁpull_after__mutmut_25` | survived | `return self._empty(path, _gone, more)` → `return self._empty(_gone, more)` |
| `xǁCaptureSpoolǁpull_after__mutmut_26` | survived | `return self._empty(path, _gone, more)` → `return self._empty(path, more)` |
| `xǁCaptureSpoolǁpull_after__mutmut_27` | survived | `return self._empty(path, _gone, more)` → `return self._empty(path, _gone, )` |
| `xǁCaptureSpoolǁpull_after__mutmut_45` | survived | `path.name,` → `None,` |
| `xǁCaptureSpoolǁpull_after__mutmut_50` | survived | `"skipped %d unusable record(s) in spool file %s (first, line %d: %s)",` → `"XXskipped %d unusable record(s) in spool file %s (first, line %d: %s)XX",` |
| `xǁCaptureSpoolǁpull_after__mutmut_55` | survived | `kept = "its usable lines are stored" if read.observations else "no line is usable"` → `kept = "its usable lines are stored" if (read.observations) or True else "no line is usable"` |
| `xǁCaptureSpoolǁpull_after__mutmut_56` | survived | `kept = "its usable lines are stored" if read.observations else "no line is usable"` → `kept = "XXits usable lines are storedXX" if read.observations else "no line is usable"` |
| `xǁCaptureSpoolǁpull_after__mutmut_58` | survived | `kept = "its usable lines are stored" if read.observations else "no line is usable"` → `kept = "its usable lines are stored" if read.observations else "XXno line is usableXX"` |
| `xǁCaptureSpoolǁpull_after__mutmut_59` | survived | `kept = "its usable lines are stored" if read.observations else "no line is usable"` → `kept = "its usable lines are stored" if read.observations else "NO LINE IS USABLE"` |
| `xǁCaptureSpoolǁpull_after__mutmut_77` | survived | `position is None or newest > position or position > utc_iso(now)` → `position is None or newest > position or position >= utc_iso(now)` |

### computer_history.sources.ax_text.agreement

| mutant | status | change |
|---|---|---|
| `x__distance__mutmut_5` | survived | `return max(span[0] - at, at - span[1], timedelta())` → `return max(span[0] - at, timedelta())` |
| `x__distance__mutmut_6` | survived | `return max(span[0] - at, at - span[1], timedelta())` → `return max(span[0] - at, at - span[1], )` |
| `x__distance__mutmut_8` | survived | `return max(span[0] - at, at - span[1], timedelta())` → `return max(span[1] - at, at - span[1], timedelta())` |
| `x_app_agreement__mutmut_15` | survived | `sorted(s for s in spans if s[0] <= end + tolerance and s[1] >= start - tolerance)` → `sorted(s for s in spans if s[1] <= end + tolerance and s[1] >= start - tolerance)` |
| `x_app_agreement__mutmut_16` | survived | `sorted(s for s in spans if s[0] <= end + tolerance and s[1] >= start - tolerance)` → `sorted(s for s in spans if s[0] < end + tolerance and s[1] >= start - tolerance)` |
| `x_app_agreement__mutmut_17` | survived | `sorted(s for s in spans if s[0] <= end + tolerance and s[1] >= start - tolerance)` → `sorted(s for s in spans if s[0] <= end - tolerance and s[1] >= start - tolerance)` |
| `x_app_agreement__mutmut_19` | survived | `sorted(s for s in spans if s[0] <= end + tolerance and s[1] >= start - tolerance)` → `sorted(s for s in spans if s[0] <= end + tolerance and s[1] > start - tolerance)` |
| `x_app_agreement__mutmut_20` | survived | `sorted(s for s in spans if s[0] <= end + tolerance and s[1] >= start - tolerance)` → `sorted(s for s in spans if s[0] <= end + tolerance and s[1] >= start + tolerance)` |
| `x_app_agreement__mutmut_3` | survived | `key=lambda r: r.at,` → `key=None,` |
| `x_app_agreement__mutmut_30` | survived | `while pending and pending[0][0] <= at + tolerance:` → `while pending and pending[0][0] < at + tolerance:` |
| `x_app_agreement__mutmut_35` | survived | `near = [span for span in near if span[1] >= at - tolerance]` → `near = [span for span in near if span[1] > at - tolerance]` |
| `x_app_agreement__mutmut_5` | survived | `key=lambda r: r.at, / )` → `)` |
| `x_app_agreement__mutmut_53` | survived | `pairs[(capture.app, min(near, key=lambda span: _distance(at, span))[2])] += 1` → `pairs[(capture.app, min(near, key=None)[2])] += 1` |
| `x_app_agreement__mutmut_55` | survived | `pairs[(capture.app, min(near, key=lambda span: _distance(at, span))[2])] += 1` → `pairs[(capture.app, min(near, )[2])] += 1` |
| `x_app_agreement__mutmut_71` | survived | `ranked = sorted(pairs.items(), key=lambda item: (-item[1], str(item[0])))` → `ranked = sorted(pairs.items(), key=lambda item: (-item[1], str(None)))` |
| `x_app_agreement__mutmut_72` | survived | `ranked = sorted(pairs.items(), key=lambda item: (-item[1], str(item[0])))` → `ranked = sorted(pairs.items(), key=lambda item: (-item[1], str(item[1])))` |
| `x_app_agreement__mutmut_9` | survived | `(r for r in records if r.kind == CAPTURE_KIND and start <= r.at <= end),` → `(r for r in records if r.kind == CAPTURE_KIND and start <= r.at < end),` |

### computer_history.sources.ax_text.backlog

| mutant | status | change |
|---|---|---|
| `x__count_files__mutmut_4` | survived | `entry.is_file(follow_symlinks=False) and not entry.name.startswith(".")` → `entry.is_file(follow_symlinks=None) and not entry.name.startswith(".")` |
| `x__count_files__mutmut_5` | survived | `entry.is_file(follow_symlinks=False) and not entry.name.startswith(".")` → `entry.is_file(follow_symlinks=True) and not entry.name.startswith(".")` |
| `x__finished_at__mutmut_6` | survived | `return datetime.fromtimestamp(path.stat().st_mtime, UTC)` → `return datetime.fromtimestamp(None, UTC)` |
| `x__finished_at__mutmut_7` | survived | `return datetime.fromtimestamp(path.stat().st_mtime, UTC)` → `return datetime.fromtimestamp(path.stat().st_mtime, None)` |
| `x__finished_at__mutmut_8` | survived | `return datetime.fromtimestamp(path.stat().st_mtime, UTC)` → `return datetime.fromtimestamp(UTC)` |
| `x__finished_at__mutmut_9` | survived | `return datetime.fromtimestamp(path.stat().st_mtime, UTC)` → `return datetime.fromtimestamp(path.stat().st_mtime, )` |
| `x__has_bytes__mutmut_2` | survived | `return path.stat().st_size > 0` → `return path.stat().st_size > 1` |
| `x__newest_record__mutmut_8` | survived | `record = parse_record(raw.decode("utf-8"))` → `record = parse_record(raw.decode("UTF-8"))` |
| `x_spool_backlog__mutmut_17` | survived | `raise SpoolError(f"cannot inspect the spool at {folder}: {exc}") from exc` → `raise SpoolError(None) from exc` |

### computer_history.sources.ax_text.coverage

| mutant | status | change |
|---|---|---|
| `x__clip__mutmut_10` | survived | `return [(a, b) for a, b in clipped if a < b]` → `return [(a, b) for a, b in clipped if a <= b]` |
| `x__gaps__mutmut_6` | survived | `return tuple(g for g in (Gap(a, b) for a, b in spans) if g.seconds >= min_gap_seconds)` → `return tuple(g for g in (Gap(a, b) for a, b in spans) if g.seconds > min_gap_seconds)` |
| `x__merge__mutmut_3` | survived | `if b <= a:` → `if b < a:` |
| `x__merge__mutmut_4` | survived | `continue` → `break` |
| `x__merge__mutmut_6` | survived | `if merged and a <= merged[-1][1]:` → `if merged and a < merged[-1][1]:` |
| `x__paused_spans__mutmut_13` | survived | `paused_from = record.at if paused_from is None else paused_from` → `paused_from = record.at if (paused_from is None) or True else paused_from` |
| `x__subtract__mutmut_14` | survived | `if cursor >= b:` → `if cursor > b:` |
| `x__subtract__mutmut_16` | survived | `if cursor < b:` → `if cursor <= b:` |
| `x__subtract__mutmut_3` | survived | `if h1 <= cursor or h0 >= b:` → `if h1 <= cursor and h0 >= b:` |
| `x__subtract__mutmut_4` | survived | `if h1 <= cursor or h0 >= b:` → `if h1 < cursor or h0 >= b:` |
| `x__subtract__mutmut_5` | survived | `if h1 <= cursor or h0 >= b:` → `if h1 <= cursor or h0 > b:` |
| `x__subtract__mutmut_7` | survived | `if h0 > cursor:` → `if h0 >= cursor:` |
| `x_capture_coverage__mutmut_1` | survived | `min_gap_seconds: float = 0,` → `min_gap_seconds: float = 1,` |
| `x_capture_coverage__mutmut_38` | survived | `start, end, _gaps(unobserved, min_gap_seconds), _gaps(unjudged, min_gap_seconds)` → `None, end, _gaps(unobserved, min_gap_seconds), _gaps(unjudged, min_gap_seconds)` |
| `x_liveness__mutmut_15` | survived | `stretches = _clip(_merge(active), last_seen + CAPTURE_TOLERANCE, now)` → `stretches = _clip(_merge(active), last_seen - CAPTURE_TOLERANCE, now)` |
| `x_liveness__mutmut_26` | survived | `return "no" if attended > CAPTURE_TOLERANCE else "unknown"` → `return "no" if attended >= CAPTURE_TOLERANCE else "unknown"` |
| `x_liveness__mutmut_4` | survived | `if now - last_seen <= AGENT_ALIVE_WITHIN:` → `if now - last_seen < AGENT_ALIVE_WITHIN:` |

### computer_history.sources.ax_text.normalize

| mutant | status | change |
|---|---|---|
| `x_project_capture__mutmut_32` | survived | `extras=json.dumps(extras, sort_keys=True) if extras else None,` → `extras=json.dumps(extras, sort_keys=True) if (extras) or True else None,` |
| `x_project_capture__mutmut_34` | survived | `extras=json.dumps(extras, sort_keys=True) if extras else None,` → `extras=json.dumps(extras, sort_keys=None) if extras else None,` |
| `x_project_capture__mutmut_36` | survived | `extras=json.dumps(extras, sort_keys=True) if extras else None,` → `extras=json.dumps(extras, ) if extras else None,` |
| `x_project_capture__mutmut_37` | survived | `extras=json.dumps(extras, sort_keys=True) if extras else None,` → `extras=json.dumps(extras, sort_keys=False) if extras else None,` |

### computer_history.sources.ax_text.record

| mutant | status | change |
|---|---|---|
| `x__captured_at__mutmut_2` | survived | `raise InvalidRecord(f"bad captured_at {value!r}")` → `raise InvalidRecord(None)` |
| `x_parse_record__mutmut_6` | survived | `raise InvalidRecord("not a JSON object")` → `raise InvalidRecord("XXnot a JSON objectXX")` |

### computer_history.sources.ax_text.spool

| mutant | status | change |
|---|---|---|
| `x_finished_files__mutmut_10` | survived | `and entry.is_file(follow_symlinks=False)` → `and entry.is_file(follow_symlinks=None)` |
| `x_finished_files__mutmut_11` | survived | `and entry.is_file(follow_symlinks=False)` → `and entry.is_file(follow_symlinks=True)` |
| `x_remove_finished__mutmut_1` | survived | `path.unlink(missing_ok=True)` → `path.unlink(missing_ok=None)` |
| `x_remove_finished__mutmut_2` | survived | `path.unlink(missing_ok=True)` → `path.unlink(missing_ok=False)` |
| `x_set_aside__mutmut_15` | survived | `copy += 1` → `copy = 1` |
| `x_set_aside__mutmut_20` | survived | `path.unlink(missing_ok=True)` → `path.unlink(missing_ok=None)` |
| `x_set_aside__mutmut_21` | survived | `path.unlink(missing_ok=True)` → `path.unlink(missing_ok=False)` |
| `x_set_aside__mutmut_22` | survived | `raise SpoolError(f"cannot move spool file {path} aside: {exc}") from exc` → `raise SpoolError(None) from exc` |

### computer_history.sources.ax_text.stored

| mutant | status | change |
|---|---|---|
| `x_day_counts__mutmut_3` | survived | `if record.at < since:` → `if record.at <= since:` |
| `x_day_counts__mutmut_6` | survived | `excluded += 1` → `excluded = 1` |
| `x_newest_stored__mutmut_15` | survived | `return at, value if isinstance(value, str) else None` → `return at, value if (isinstance(value, str)) or True else None` |
| `x_stored_records__mutmut_23` | survived | `kind if isinstance(kind, str) else None,` → `kind if (isinstance(kind, str)) or True else None,` |
| `x_stored_records__mutmut_27` | survived | `clean_text(app) if isinstance(app, str) else None,` → `clean_text(app) if (isinstance(app, str)) or True else None,` |

### computer_history.sources.backfill

| mutant | status | change |
|---|---|---|
| `x__backfill_stream__mutmut_25` | survived | `if incomplete_from is not None and first_incomplete is None:` → `if incomplete_from is not None or first_incomplete is None:` |
| `x__backfill_stream__mutmut_60` | survived | `result.held_back += pulled.held_back` → `result.held_back = pulled.held_back` |
| `x__backfill_stream__mutmut_62` | survived | `result.seconds += seconds` → `result.seconds = seconds` |
| `x__backfill_stream__mutmut_63` | survived | `result.seconds += seconds` → `result.seconds -= seconds` |
| `x_plan_all_backfills__mutmut_2` | survived | `stream = None` → `stream = ""` |
| `x_plan_all_backfills__mutmut_26` | survived | `return Planning(failure=failure_of(stream, exc))` → `return Planning(failure=failure_of(None, exc))` |
| `x_plan_backfill__mutmut_1` | survived | `if chunk <= timedelta(0):` → `if chunk < timedelta(0):` |
| `x_plan_backfill__mutmut_38` | survived | `if begin is None or begin >= stop:` → `if begin is None or begin > stop:` |
| `x_plan_backfill__mutmut_39` | survived | `return BackfillPlan(stream, parts, begin, stop, settled, (), has_progress=has_progress)` → `return BackfillPlan(None, parts, begin, stop, settled, (), has_progress=has_progress)` |
| `x_plan_backfill__mutmut_4` | survived | `raise ValueError(f"chunk width must be positive: {chunk}")` → `raise ValueError(None)` |
| `x_plan_backfill__mutmut_40` | survived | `return BackfillPlan(stream, parts, begin, stop, settled, (), has_progress=has_progress)` → `return BackfillPlan(stream, None, begin, stop, settled, (), has_progress=has_progress)` |
| `x_plan_backfill__mutmut_41` | survived | `return BackfillPlan(stream, parts, begin, stop, settled, (), has_progress=has_progress)` → `return BackfillPlan(stream, parts, None, stop, settled, (), has_progress=has_progress)` |
| `x_plan_backfill__mutmut_42` | survived | `return BackfillPlan(stream, parts, begin, stop, settled, (), has_progress=has_progress)` → `return BackfillPlan(stream, parts, begin, None, settled, (), has_progress=has_progress)` |
| `x_plan_backfill__mutmut_43` | survived | `return BackfillPlan(stream, parts, begin, stop, settled, (), has_progress=has_progress)` → `return BackfillPlan(stream, parts, begin, stop, None, (), has_progress=has_progress)` |
| `x_plan_backfill__mutmut_45` | survived | `return BackfillPlan(stream, parts, begin, stop, settled, (), has_progress=has_progress)` → `return BackfillPlan(stream, parts, begin, stop, settled, (), has_progress=None)` |
| `x_plan_backfill__mutmut_52` | survived | `return BackfillPlan(stream, parts, begin, stop, settled, (), has_progress=has_progress)` → `return BackfillPlan(stream, parts, begin, stop, settled, (), )` |
| `x_plan_backfill__mutmut_55` | survived | `while edge < stop:` → `while edge <= stop:` |
| `x_run_backfill__mutmut_11` | survived | `continue` → `break` |
| `x_run_backfill__mutmut_9` | survived | `stream = None` → `stream = ""` |

### computer_history.sources.projection

| mutant | status | change |
|---|---|---|
| `x_reproject_signals__mutmut_1` | survived | `allow_shrink: bool = False,` → `allow_shrink: bool = True,` |

### computer_history.sources.runner

| mutant | status | change |
|---|---|---|
| `x__claim__mutmut_2` | survived | `raise ValueError(f"stream {stream!r} is fed by more than one source")` → `raise ValueError(None)` |
| `x__claim__mutmut_3` | survived | `seen.add(stream)` → `seen.add(None)` |
| `x_watch__mutmut_3` | survived | `clock = clock or (lambda: datetime.now(UTC))` → `clock = clock or (lambda: None)` |

### computer_history.store.db

| mutant | status | change |
|---|---|---|
| `x__applied_by_another_process__mutmut_2` | survived | `return schema_version(conn) >= migration.version` → `return schema_version(conn) > migration.version` |
| `x__open__mutmut_3` | survived | `uri=True,` → `uri=None,` |
| `x__open__mutmut_6` | survived | `uri=True,` → `` |
| `x__open__mutmut_7` | survived | `timeout=BUSY_TIMEOUT_SECONDS,` → `` |
| `x__open__mutmut_9` | survived | `uri=True,` → `uri=False,` |
| `x__split_statements__mutmut_12` | survived | `if buffer.strip() != ";":` → `if buffer.strip() != "XX;XX":` |
| `x__split_statements__mutmut_16` | survived | `if buffer[:-1].strip():` → `if buffer[:+1].strip():` |
| `x__split_statements__mutmut_17` | survived | `if buffer[:-1].strip():` → `if buffer[:-2].strip():` |
| `x__split_statements__mutmut_19` | survived | `statements.append(buffer[:-1])` → `statements.append(buffer[:+1])` |
| `x__split_statements__mutmut_20` | survived | `statements.append(buffer[:-1])` → `statements.append(buffer[:-2])` |
| `x_connect__mutmut_16` | survived | `conn = _open(path, "rwc" if create else "rw")` → `conn = _open(path, "rwc" if (create) or True else "rw")` |
| `x_connect__mutmut_23` | survived | `conn.execute("PRAGMA foreign_keys = ON")` → `conn.execute("pragma foreign_keys = on")` |
| `x_connect__mutmut_24` | survived | `conn.execute("PRAGMA foreign_keys = ON")` → `conn.execute("PRAGMA FOREIGN_KEYS = ON")` |
| `x_load_migrations__mutmut_10` | survived | `use_cache = True` → `use_cache = False` |
| `x_load_migrations__mutmut_11` | survived | `use_cache = False` → `use_cache = None` |
| `x_load_migrations__mutmut_12` | survived | `use_cache = False` → `use_cache = True` |
| `x_load_migrations__mutmut_18` | survived | `continue` → `break` |
| `x_load_migrations__mutmut_2` | survived | `if _default_migrations is not None:` → `if _default_migrations is None:` |
| `x_load_migrations__mutmut_22` | survived | `raise RuntimeError(f"migration file {entry.name!r} is not named NNN_description.sql")` → `raise RuntimeError(None)` |
| `x_load_migrations__mutmut_24` | survived | `migrations.append(Migration(int(match[1]), entry.name, entry.read_text(encoding="utf-8")))` → `migrations.append(Migration(None, entry.name, entry.read_text(encoding="utf-8")))` |
| `x_load_migrations__mutmut_25` | survived | `migrations.append(Migration(int(match[1]), entry.name, entry.read_text(encoding="utf-8")))` → `migrations.append(Migration(int(match[1]), None, entry.read_text(encoding="utf-8")))` |
| `x_load_migrations__mutmut_26` | survived | `migrations.append(Migration(int(match[1]), entry.name, entry.read_text(encoding="utf-8")))` → `migrations.append(Migration(int(match[1]), entry.name, None))` |
| `x_load_migrations__mutmut_32` | survived | `migrations.append(Migration(int(match[1]), entry.name, entry.read_text(encoding="utf-8")))` → `migrations.append(Migration(int(match[1]), entry.name, entry.read_text(encoding=None)))` |
| `x_load_migrations__mutmut_34` | survived | `migrations.append(Migration(int(match[1]), entry.name, entry.read_text(encoding="utf-8")))` → `migrations.append(Migration(int(match[1]), entry.name, entry.read_text(encoding="UTF-8")))` |
| `x_load_migrations__mutmut_37` | survived | `_default_migrations = list(migrations)` → `_default_migrations = None` |
| `x_load_migrations__mutmut_38` | survived | `_default_migrations = list(migrations)` → `_default_migrations = list(None)` |
| `x_load_migrations__mutmut_4` | survived | `directory = resources.files(__package__).joinpath("migrations")` → `directory = None` |
| `x_load_migrations__mutmut_5` | survived | `directory = resources.files(__package__).joinpath("migrations")` → `directory = resources.files(__package__).joinpath(None)` |
| `x_load_migrations__mutmut_6` | survived | `directory = resources.files(__package__).joinpath("migrations")` → `directory = resources.files(None).joinpath("migrations")` |
| `x_load_migrations__mutmut_7` | survived | `directory = resources.files(__package__).joinpath("migrations")` → `directory = resources.files(__package__).joinpath("XXmigrationsXX")` |
| `x_load_migrations__mutmut_8` | survived | `directory = resources.files(__package__).joinpath("migrations")` → `directory = resources.files(__package__).joinpath("MIGRATIONS")` |
| `x_load_migrations__mutmut_9` | survived | `use_cache = True` → `use_cache = None` |
| `x_migrate__mutmut_11` | survived | `latest = migrations[-1].version if migrations else 0` → `latest = migrations[-1].version if migrations else 1` |
| `x_migrate__mutmut_16` | survived | `raise NewerSchema(current, latest)` → `raise NewerSchema(current, None)` |
| `x_migrate__mutmut_26` | survived | `continue` → `break` |
| `x_migrate__mutmut_8` | survived | `latest = migrations[-1].version if migrations else 0` → `latest = migrations[-1].version if (migrations) or True else 0` |
| `x_schema_version__mutmut_3` | survived | `return conn.execute("PRAGMA user_version").fetchone()[0]` → `return conn.execute("pragma user_version").fetchone()[0]` |
| `x_schema_version__mutmut_4` | survived | `return conn.execute("PRAGMA user_version").fetchone()[0]` → `return conn.execute("PRAGMA USER_VERSION").fetchone()[0]` |
| `xǁNewerSchemaǁ__init____mutmut_3` | survived | `self.supported = supported` → `self.supported = None` |

### computer_history.store.observations

| mutant | status | change |
|---|---|---|
| `x__prepare__mutmut_10` | survived | `f"observation {observation.source}/{observation.source_id} ends before it starts"` → `None` |
| `x__prepare__mutmut_2` | survived | `raise ValueError(f"observation {observation.source_id!r} has no source")` → `raise ValueError(None)` |
| `x__prepare__mutmut_4` | survived | `raise ValueError(f"observation from {observation.source!r} has no source_id")` → `raise ValueError(None)` |
| `x_insert_observations__mutmut_2` | survived | `"insert_observations opens its own transaction; "` → `"XXinsert_observations opens its own transaction; XX"` |
| `x_insert_observations__mutmut_3` | survived | `"insert_observations opens its own transaction; "` → `"INSERT_OBSERVATIONS OPENS ITS OWN TRANSACTION; "` |
| `x_insert_observations__mutmut_4` | survived | `"it must not be called inside transaction()"` → `"XXit must not be called inside transaction()XX"` |

### computer_history.store.opening

| mutant | status | change |
|---|---|---|
| `x__is_busy__mutmut_6` | survived | `code = getattr(exc, "sqlite_errorcode", None)` → `code = getattr(exc, "sqlite_errorcode", )` |
| `x__open_for_read__mutmut_19` | survived | `state = StoreState.OUTDATED if version < supported else StoreState.NEWER` → `state = StoreState.OUTDATED if version <= supported else StoreState.NEWER` |
| `x_open_store__mutmut_22` | survived | `conn = connect(path, create=purpose is Purpose.WRITE)` → `conn = connect(path, )` |
| `x_open_store__mutmut_38` | survived | `return OpenedStore(path, state, supported, error=str(exc))` → `return OpenedStore(path, state, None, error=str(exc))` |
| `x_open_store__mutmut_45` | survived | `return OpenedStore(path, StoreState.UNREADABLE, supported, error=str(exc))` → `return OpenedStore(None, StoreState.UNREADABLE, supported, error=str(exc))` |
| `x_open_store__mutmut_47` | survived | `return OpenedStore(path, StoreState.UNREADABLE, supported, error=str(exc))` → `return OpenedStore(path, StoreState.UNREADABLE, None, error=str(exc))` |
| `x_open_store__mutmut_9` | survived | `return OpenedStore(path, StoreState.MISSING, supported)` → `return OpenedStore(path, StoreState.MISSING, None)` |

### computer_history.store.progress

| mutant | status | change |
|---|---|---|
| `x_get_progress__mutmut_7` | survived | `"SELECT position, settled_until, advanced_at FROM ingest_progress WHERE source = ?",` → `"select position, settled_until, advanced_at from ingest_progress where source = ?",` |
| `x_write_with_batch__mutmut_3` | survived | `raise RuntimeError("ingest progress only moves inside a batch's transaction")` → `raise RuntimeError("XXingest progress only moves inside a batch's transactionXX")` |
| `xǁProgressUpdateǁ__post_init____mutmut_2` | survived | `raise ValueError("progress update has no source")` → `raise ValueError(None)` |
| `xǁProgressUpdateǁ__post_init____mutmut_3` | survived | `raise ValueError("progress update has no source")` → `raise ValueError("XXprogress update has no sourceXX")` |
| `xǁProgressUpdateǁ__post_init____mutmut_4` | survived | `raise ValueError("progress update has no source")` → `raise ValueError("PROGRESS UPDATE HAS NO SOURCE")` |
| `xǁProgressUpdateǁ__post_init____mutmut_8` | survived | `raise ValueError(f"progress update for {self.source!r} has no position")` → `raise ValueError(None)` |

### computer_history.store.signals

| mutant | status | change |
|---|---|---|
| `x__refuse_unclaimed__mutmut_10` | survived | `raise _unclaimed(conn, source) from UnclaimedSource(source)` → `raise _unclaimed(conn, source) from UnclaimedSource(None)` |
| `x__refuse_unclaimed__mutmut_3` | survived | `for (source,) in conn.execute("SELECT DISTINCT source FROM observations ORDER BY source"):` → `for (source,) in conn.execute("select distinct source from observations order by source"):` |
| `x__refuse_unclaimed__mutmut_4` | survived | `for (source,) in conn.execute("SELECT DISTINCT source FROM observations ORDER BY source"):` → `for (source,) in conn.execute("SELECT DISTINCT SOURCE FROM OBSERVATIONS ORDER BY SOURCE"):` |
| `x__unclaimed__mutmut_11` | survived | `plural = "" if count == 1 else "s"` → `plural = "" if (count == 1) or True else "s"` |
| `x__unclaimed__mutmut_15` | survived | `plural = "" if count == 1 else "s"` → `plural = "" if count == 1 else "XXsXX"` |
| `x__unclaimed__mutmut_16` | survived | `plural = "" if count == 1 else "s"` → `plural = "" if count == 1 else "S"` |
| `x__unclaimed__mutmut_7` | survived | `"SELECT COUNT(*), MIN(id) FROM observations WHERE source = ?", (source,)` → `"select count(*), min(id) from observations where source = ?", (source,)` |
| `x__unclaimed__mutmut_8` | survived | `"SELECT COUNT(*), MIN(id) FROM observations WHERE source = ?", (source,)` → `"SELECT COUNT(*), MIN(ID) FROM OBSERVATIONS WHERE SOURCE = ?", (source,)` |
| `x_rebuild_signals__mutmut_100` | survived | `if failed > MAX_LOGGED_FAILURES:` → `if failed >= MAX_LOGGED_FAILURES:` |
| `x_rebuild_signals__mutmut_105` | survived | `"rebuild-signals: %d more observations skipped (not logged individually)",` → `"XXrebuild-signals: %d more observations skipped (not logged individually)XX",` |
| `x_rebuild_signals__mutmut_112` | survived | `and before >= SHRINK_CHECK_MIN_SIGNALS` → `and before > SHRINK_CHECK_MIN_SIGNALS` |
| `x_rebuild_signals__mutmut_117` | survived | `failed_ids=tuple(failed_ids),` → `failed_ids=None,` |
| `x_rebuild_signals__mutmut_120` | survived | `failed=failed,` → `` |
| `x_rebuild_signals__mutmut_121` | survived | `failed_ids=tuple(failed_ids),` → `` |
| `x_rebuild_signals__mutmut_18` | survived | `f"too many malformed payloads: {failed:,} observations failed to project," / f" more than {MAX_FAILURE_RATIO:.0%} of the at most {bound:,} content" / " observations",` → `None,` |
| `x_rebuild_signals__mutmut_24` | survived | `" observations",` → `"XX observationsXX",` |
| `x_rebuild_signals__mutmut_25` | survived | `" observations",` → `" OBSERVATIONS",` |
| `x_rebuild_signals__mutmut_3` | survived | `"rebuild_signals opens its own transaction; it must not be called inside transaction()"` → `"XXrebuild_signals opens its own transaction; it must not be called inside transaction()XX"` |
| `x_rebuild_signals__mutmut_36` | survived | `before = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]` → `before = conn.execute("select count(*) from signals").fetchone()[0]` |
| `x_rebuild_signals__mutmut_37` | survived | `before = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]` → `before = conn.execute("SELECT COUNT(*) FROM SIGNALS").fetchone()[0]` |
| `x_rebuild_signals__mutmut_42` | survived | `total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]` → `total = conn.execute("select count(*) from observations").fetchone()[0]` |
| `x_rebuild_signals__mutmut_43` | survived | `total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]` → `total = conn.execute("SELECT COUNT(*) FROM OBSERVATIONS").fetchone()[0]` |
| `x_rebuild_signals__mutmut_47` | survived | `conn.execute("DELETE FROM signals")` → `conn.execute("delete from signals")` |
| `x_rebuild_signals__mutmut_48` | survived | `conn.execute("DELETE FROM signals")` → `conn.execute("DELETE FROM SIGNALS")` |
| `x_rebuild_signals__mutmut_52` | survived | `"SELECT id, source, started_at, ended_at, payload FROM observations ORDER BY id"` → `"select id, source, started_at, ended_at, payload from observations order by id"` |
| `x_rebuild_signals__mutmut_53` | survived | `"SELECT id, source, started_at, ended_at, payload FROM observations ORDER BY id"` → `"SELECT ID, SOURCE, STARTED_AT, ENDED_AT, PAYLOAD FROM OBSERVATIONS ORDER BY ID"` |
| `x_rebuild_signals__mutmut_62` | survived | `raise _unclaimed(conn, exc.source) from exc` → `raise _unclaimed(None, exc.source) from exc` |
| `x_rebuild_signals__mutmut_63` | survived | `raise _unclaimed(conn, exc.source) from exc` → `raise _unclaimed(conn, None) from exc` |
| `x_rebuild_signals__mutmut_64` | survived | `raise _unclaimed(conn, exc.source) from exc` → `raise _unclaimed(exc.source) from exc` |
| `x_rebuild_signals__mutmut_65` | survived | `raise _unclaimed(conn, exc.source) from exc` → `raise _unclaimed(conn, ) from exc` |
| `x_rebuild_signals__mutmut_73` | survived | `source,` → `None,` |
| `x_rebuild_signals__mutmut_74` | survived | `exc,` → `None,` |
| `x_rebuild_signals__mutmut_79` | survived | `"rebuild-signals: skipping observation %d (%s): cannot project its"` → `"XXrebuild-signals: skipping observation %d (%s): cannot project itsXX"` |
| `x_rebuild_signals__mutmut_81` | survived | `" payload: %r",` → `"XX payload: %rXX",` |
| `x_rebuild_signals__mutmut_91` | survived | `if len(batch) >= batch_size:` → `if len(batch) > batch_size:` |

### computer_history.store.status

| mutant | status | change |
|---|---|---|
| `x_find_gaps__mutmut_1` | survived | `min_gap_seconds: float = 0,` → `min_gap_seconds: float = 1,` |
| `x_find_gaps__mutmut_13` | survived | `"SELECT started_at, ended_at FROM observations "` → `"select started_at, ended_at from observations "` |
| `x_find_gaps__mutmut_14` | survived | `"SELECT started_at, ended_at FROM observations "` → `"SELECT STARTED_AT, ENDED_AT FROM OBSERVATIONS "` |
| `x_find_gaps__mutmut_16` | survived | `"WHERE source = ? AND started_at < ? AND ended_at > ? AND ended_at > started_at "` → `"where source = ? and started_at < ? and ended_at > ? and ended_at > started_at "` |
| `x_find_gaps__mutmut_17` | survived | `"WHERE source = ? AND started_at < ? AND ended_at > ? AND ended_at > started_at "` → `"WHERE SOURCE = ? AND STARTED_AT < ? AND ENDED_AT > ? AND ENDED_AT > STARTED_AT "` |
| `x_find_gaps__mutmut_19` | survived | `"ORDER BY started_at",` → `"order by started_at",` |
| `x_find_gaps__mutmut_20` | survived | `"ORDER BY started_at",` → `"ORDER BY STARTED_AT",` |
| `x_find_gaps__mutmut_30` | survived | `if covered_until < end_text:` → `if covered_until <= end_text:` |
| `x_find_gaps__mutmut_39` | survived | `return [gap for gap in result if gap.seconds >= min_gap_seconds]` → `return [gap for gap in result if gap.seconds > min_gap_seconds]` |
| `x_payload_values__mutmut_15` | survived | `"WHERE source = ? AND started_at <= ? AND ended_at >= ? ORDER BY started_at, id",` → `"where source = ? and started_at <= ? and ended_at >= ? order by started_at, id",` |
| `x_payload_values__mutmut_16` | survived | `"WHERE source = ? AND started_at <= ? AND ended_at >= ? ORDER BY started_at, id",` → `"WHERE SOURCE = ? AND STARTED_AT <= ? AND ENDED_AT >= ? ORDER BY STARTED_AT, ID",` |
| `x_payload_values__mutmut_2` | survived | `raise ValueError("payload_values needs at least one JSON path")` → `raise ValueError(None)` |
| `x_payload_values__mutmut_3` | survived | `raise ValueError("payload_values needs at least one JSON path")` → `raise ValueError("XXpayload_values needs at least one JSON pathXX")` |
| `x_payload_values__mutmut_4` | survived | `raise ValueError("payload_values needs at least one JSON path")` → `raise ValueError("payload_values needs at least one json path")` |
| `x_payload_values__mutmut_5` | survived | `raise ValueError("payload_values needs at least one JSON path")` → `raise ValueError("PAYLOAD_VALUES NEEDS AT LEAST ONE JSON PATH")` |
| `x_table_counts__mutmut_5` | survived | `"SELECT name FROM sqlite_master "` → `"select name from sqlite_master "` |
| `x_table_counts__mutmut_6` | survived | `"SELECT name FROM sqlite_master "` → `"SELECT NAME FROM SQLITE_MASTER "` |
| `x_table_counts__mutmut_8` | survived | `"WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"` → `"where type = 'table' and name not like 'sqlite_%' order by name"` |

### computer_history.text

| mutant | status | change |
|---|---|---|
| `x__sanitize_url__mutmut_1` | survived | `return _scrub(value).translate(_URL_CONTROL_CHARS).strip(" ")` → `return _scrub(value).translate(_URL_CONTROL_CHARS).strip(None)` |
| `x__sanitize_url__mutmut_4` | survived | `return _scrub(value).translate(_URL_CONTROL_CHARS).strip(" ")` → `return _scrub(value).translate(_URL_CONTROL_CHARS).strip("XX XX")` |
| `x__scrub__mutmut_11` | survived | `return value.encode("utf-8", "replace").decode("utf-8")` → `return value.encode("utf-8", "replace").decode("UTF-8")` |
| `x__scrub__mutmut_7` | survived | `return value.encode("utf-8", "replace").decode("utf-8")` → `return value.encode("UTF-8", "replace").decode("utf-8")` |
| `x_extract_domain__mutmut_16` | survived | `host = host.rstrip(".")` → `host = host.rstrip("XX.XX")` |

