import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gptcron


class GptCronTestCase(unittest.TestCase):
    def setUp(self):
        self.original_directory = os.getcwd()
        self.temporary_directory = tempfile.TemporaryDirectory()
        os.chdir(self.temporary_directory.name)

    def tearDown(self):
        os.chdir(self.original_directory)
        self.temporary_directory.cleanup()

    def write_config(self, **overrides):
        config = {
            "login_email": "sender@example.com",
            "from_email": "sender@example.com",
            "to_email": "recipient@example.com",
            "password": "password",
            "default_model": "claude-test",
            "fallback_model": "gpt-test",
            "anthropic_api_key": "anthropic-key",
            "openai_api_key": "openai-key"
        }
        config.update(overrides)
        with open("config.json", "w", encoding="utf-8") as config_file:
            json.dump(config, config_file)
        return config

    def write_job(self, name="site", frequency="daily", url="https://example.com"):
        with open(".gptcron", "w", encoding="utf-8") as cron_file:
            cron_file.write(f"{frequency} {name} {url} 20260101000000\n")

    def write_snapshot(self, name, timestamp, content):
        directory = os.path.join("data", name)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{name}-{timestamp}.html")
        with open(path, "w", encoding="utf-8") as snapshot:
            snapshot.write(content)
        return path


class ConfigAndProviderTests(GptCronTestCase):
    def test_anthropic_only_config_does_not_require_legacy_apikey_file(self):
        self.write_config(openai_api_key="")

        config = gptcron.get_model_config()

        self.assertEqual(config["anthropic_api_key"], "anthropic-key")
        self.assertIsNone(config["openai_api_key"])

    def test_openai_provider_path(self):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )
        client = Mock()
        client.chat.completions.create.return_value = completion
        config = {
            "default_model": "gpt-test",
            "fallback_model": None,
            "openai_api_key": "openai-key",
            "anthropic_api_key": None
        }

        with patch.object(gptcron, "get_model_config", return_value=config), \
                patch.object(gptcron, "OpenAI", return_value=client) as openai_client:
            result = gptcron.call_llm("prompt", response_format={"type": "json_object"})

        self.assertEqual(result, '{"ok": true}')
        openai_client.assert_called_once_with(api_key="openai-key")
        client.chat.completions.create.assert_called_once()

    def test_anthropic_provider_path(self):
        client = Mock()
        client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(text='{"ok": true}')]
        )
        anthropic_module = SimpleNamespace(Anthropic=Mock(return_value=client))
        config = {
            "default_model": "claude-test",
            "fallback_model": None,
            "openai_api_key": None,
            "anthropic_api_key": "anthropic-key"
        }

        with patch.object(gptcron, "get_model_config", return_value=config), \
                patch.object(gptcron, "ANTHROPIC_AVAILABLE", True), \
                patch.object(gptcron, "anthropic", anthropic_module):
            result = gptcron.call_llm("prompt", response_format={"type": "json_object"})

        self.assertEqual(result, '{"ok": true}')
        sent_prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("Respond ONLY with valid JSON", sent_prompt)

    def test_provider_failure_falls_back_to_openai(self):
        anthropic_client = Mock()
        anthropic_client.messages.create.side_effect = RuntimeError("provider unavailable")
        anthropic_module = SimpleNamespace(Anthropic=Mock(return_value=anthropic_client))
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="fallback result"))]
        )
        openai_client = Mock()
        openai_client.chat.completions.create.return_value = completion
        config = {
            "default_model": "claude-test",
            "fallback_model": "gpt-test",
            "openai_api_key": "openai-key",
            "anthropic_api_key": "anthropic-key"
        }

        with patch.object(gptcron, "get_model_config", return_value=config), \
                patch.object(gptcron, "ANTHROPIC_AVAILABLE", True), \
                patch.object(gptcron, "anthropic", anthropic_module), \
                patch.object(gptcron, "OpenAI", return_value=openai_client):
            result = gptcron.call_llm("prompt")

        self.assertEqual(result, "fallback result")

    def test_unknown_model_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "Unsupported model"):
            gptcron.get_model_provider("gemini-test")

    def test_openai_reasoning_model_uses_completion_token_parameter(self):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="result"))]
        )
        client = Mock()
        client.chat.completions.create.return_value = completion
        config = {
            "default_model": "o3-test",
            "fallback_model": None,
            "openai_api_key": "openai-key",
            "anthropic_api_key": None
        }

        with patch.object(gptcron, "get_model_config", return_value=config), \
                patch.object(gptcron, "OpenAI", return_value=client):
            gptcron.call_llm("prompt", max_tokens=123)

        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["max_completion_tokens"], 123)
        self.assertNotIn("max_tokens", request)


class JsonAndDiffTests(GptCronTestCase):
    def test_json_parser_handles_fenced_json(self):
        response, got = gptcron.attempt_to_deserialize_openai_json(
            '```json\n{"summary": "ok", "score": 7}\n```'
        )

        self.assertTrue(got)
        self.assertEqual(response["score"], 7)

    def test_json_parser_repairs_literal_newline_in_string(self):
        response, got = gptcron.attempt_to_deserialize_openai_json(
            '{"summary": "first line\nsecond line", "score": 7}'
        )

        self.assertTrue(got)
        self.assertEqual(response["summary"], "first line\nsecond line")

    def test_conformity_accepts_common_brief_summary_variant(self):
        response = {"summary": "details", "brief_summary": "brief", "score": "8"}

        self.assertTrue(gptcron.check_conformity(response))
        self.assertEqual(response["brief summary"], "brief")
        self.assertEqual(response["score"], 8)

    def test_conformity_rejects_out_of_range_score(self):
        response = {"summary": "details", "brief summary": "brief", "score": 11}

        self.assertFalse(gptcron.check_conformity(response))

    def test_diff_uses_visible_lines_and_labels_changes(self):
        old_file = self.write_snapshot(
            "site",
            "20260101-00-00-00",
            "<html><script>old()</script><body><h1>Title</h1><p>Old text</p></body></html>"
        )
        new_file = self.write_snapshot(
            "site",
            "20260102-00-00-00",
            "<html><script>new()</script><body><h1>Title</h1><p>New text</p></body></html>"
        )

        diff_text, all_text = gptcron.compare_files(old_file, new_file)

        self.assertIn("REMOVED: Old text", diff_text)
        self.assertIn("ADDED: New text", diff_text)
        self.assertNotIn("old()", all_text)
        self.assertNotIn("new()", all_text)

    def test_diff_detects_change_from_empty_page(self):
        old_file = self.write_snapshot("site", "20260101-00-00-00", "<html></html>")
        new_file = self.write_snapshot(
            "site", "20260102-00-00-00", "<html><body>Now available</body></html>"
        )

        diff_text, _ = gptcron.compare_files(old_file, new_file)

        self.assertEqual(diff_text, "ADDED: Now available")

    def test_email_diff_highlighting_matches_diff_labels(self):
        old_file = self.write_snapshot("site", "20260101-00-00-00", "<p>Old</p>")
        new_file = self.write_snapshot("site", "20260102-00-00-00", "<p>New</p>")

        _, body = gptcron.create_email_content(
            "site",
            "https://example.com?a=1&b=2",
            "Changed",
            "<p>Summary</p>",
            "REMOVED: Old\nADDED: New",
            8,
            new_file,
            [old_file, new_file]
        )

        self.assertIn('<span class="diff-removed">REMOVED: Old</span>', body)
        self.assertIn('<span class="diff-added">ADDED: New</span>', body)
        self.assertIn("with previous version", body)
        self.assertIn("a=1&amp;b=2", body)


class StateAndEmailTests(GptCronTestCase):
    def test_smtp_failure_is_propagated(self):
        self.write_config()

        with patch.object(gptcron.smtplib, "SMTP", side_effect=OSError("offline")):
            with self.assertRaises(gptcron.EmailDeliveryError):
                gptcron.inner_send_email("subject", "body", "recipient@example.com")

    def test_failed_email_is_not_archived_as_sent(self):
        with patch.object(
            gptcron, "inner_send_email", side_effect=gptcron.EmailDeliveryError("failed")
        ):
            with self.assertRaises(gptcron.EmailDeliveryError):
                gptcron.send_email("site", "subject", "body", "recipient@example.com")

        self.assertFalse(os.path.exists("emails"))

    def test_archive_failure_after_delivery_is_nonfatal(self):
        with patch.object(gptcron, "inner_send_email"), \
                patch.object(gptcron, "save_email_to_disk", side_effect=OSError("disk full")):
            gptcron.send_email("site", "subject", "body", "recipient@example.com")

    def test_first_successful_run_records_emailed_snapshot(self):
        self.write_config()
        snapshot = self.write_snapshot(
            "site", "20260101-00-00-00", "<html><body>Initial page</body></html>"
        )

        with patch.object(gptcron, "summarize_page", return_value=("Summary", "Brief")), \
                patch.object(gptcron, "send_email") as send_email:
            result = gptcron.process_downloaded_job(
                {"name": "site", "url": "https://example.com"}, snapshot
            )

        self.assertTrue(result)
        send_email.assert_called_once()
        self.assertEqual(
            gptcron.load_metadata()["site"]["last_emailed_version"], snapshot
        )

    def test_low_score_keeps_last_emailed_baseline(self):
        self.write_config()
        baseline = self.write_snapshot(
            "site", "20260101-00-00-00", "<html><body>Old</body></html>"
        )
        latest = self.write_snapshot(
            "site", "20260102-00-00-00", "<html><body>New</body></html>"
        )
        gptcron.save_metadata({"site": {"last_emailed_version": baseline}})

        with patch.object(
            gptcron, "summarize_diff", return_value=("Summary", 4, "Brief")
        ), patch.object(gptcron, "send_email") as send_email:
            result = gptcron.process_downloaded_job(
                {"name": "site", "url": "https://example.com"}, latest
            )

        self.assertFalse(result)
        send_email.assert_not_called()
        self.assertEqual(
            gptcron.load_metadata()["site"]["last_emailed_version"], baseline
        )

    def test_missing_metadata_uses_oldest_snapshot_for_aggregation(self):
        self.write_config()
        baseline = self.write_snapshot(
            "site", "20260101-00-00-00", "<html><body>Old</body></html>"
        )
        latest = self.write_snapshot(
            "site", "20260102-00-00-00", "<html><body>New</body></html>"
        )

        with patch.object(
            gptcron, "summarize_diff", return_value=("Summary", 4, "Brief")
        ) as summarize_diff, patch.object(gptcron, "summarize_page") as summarize_page:
            result = gptcron.process_downloaded_job(
                {"name": "site", "url": "https://example.com"}, latest
            )

        self.assertFalse(result)
        summarize_page.assert_not_called()
        self.assertIn("REMOVED: Old", summarize_diff.call_args.args[0])
        self.assertFalse(os.path.exists("job_metadata.json"))

    def test_failed_email_does_not_advance_baseline(self):
        self.write_config()
        baseline = self.write_snapshot(
            "site", "20260101-00-00-00", "<html><body>Old</body></html>"
        )
        latest = self.write_snapshot(
            "site", "20260102-00-00-00", "<html><body>Important change</body></html>"
        )
        gptcron.save_metadata({"site": {"last_emailed_version": baseline}})

        with patch.object(
            gptcron, "summarize_diff", return_value=("Summary", 9, "Brief")
        ), patch.object(
            gptcron, "send_email", side_effect=gptcron.EmailDeliveryError("failed")
        ):
            with self.assertRaises(gptcron.EmailDeliveryError):
                gptcron.process_downloaded_job(
                    {"name": "site", "url": "https://example.com"}, latest
                )

        self.assertEqual(
            gptcron.load_metadata()["site"]["last_emailed_version"], baseline
        )

    def test_run_job_removes_failed_snapshot_for_immediate_retry(self):
        self.write_job()
        downloaded_path = os.path.join(
            "data", "site", "site-20260102-00-00-00-000001.html"
        )

        def fake_download(url, name):
            os.makedirs(os.path.dirname(downloaded_path), exist_ok=True)
            with open(downloaded_path, "w", encoding="utf-8") as downloaded:
                downloaded.write("<p>content</p>")
            return downloaded_path

        with patch.object(gptcron, "download_url", side_effect=fake_download), \
                patch.object(gptcron, "process_downloaded_job", side_effect=ValueError("bad AI")):
            with self.assertRaisesRegex(ValueError, "bad AI"):
                gptcron.run_job("site")

        self.assertFalse(os.path.exists(downloaded_path))

    def test_snapshot_listing_ignores_unrelated_files(self):
        valid = self.write_snapshot(
            "site", "20260101-00-00-00", "<html><body>Valid</body></html>"
        )
        with open(os.path.join("data", "site", "notes.txt"), "w", encoding="utf-8") as junk:
            junk.write("ignore me")

        latest, _ = gptcron.get_last_file("site")

        self.assertEqual(latest, valid)


class CronAndCliTests(GptCronTestCase):
    def test_cron_continues_after_one_job_fails(self):
        jobs = [
            {"frequency": "daily", "name": "bad", "url": "https://bad", "date_added": "0"},
            {"frequency": "daily", "name": "good", "url": "https://good", "date_added": "0"}
        ]

        with patch.object(gptcron, "parse_cron_file", return_value=jobs), \
                patch.object(gptcron, "get_last_file", return_value=(None, None)), \
                patch.object(gptcron, "run_job", side_effect=[ValueError("bad JSON"), True]) as run_job:
            gptcron.run_cron_checks(force=True)

        self.assertEqual(run_job.call_count, 2)

    def test_cron_continues_after_email_failure(self):
        jobs = [
            {"frequency": "daily", "name": "bad", "url": "https://bad", "date_added": "0"},
            {"frequency": "daily", "name": "good", "url": "https://good", "date_added": "0"}
        ]

        with patch.object(gptcron, "parse_cron_file", return_value=jobs), \
                patch.object(gptcron, "get_last_file", return_value=(None, None)), \
                patch.object(
                    gptcron,
                    "run_job",
                    side_effect=[gptcron.EmailDeliveryError("SMTP down"), False]
                ) as run_job:
            gptcron.run_cron_checks(force=True)

        self.assertEqual(run_job.call_count, 2)

    def test_parse_cron_skips_invalid_frequency_and_unsafe_name(self):
        with open(".gptcron", "w", encoding="utf-8") as cron_file:
            cron_file.write("sometimes site https://example.com 20260101000000\n")
            cron_file.write("daily ../../escape https://example.com 20260101000000\n")
            cron_file.write("hourly valid-site https://example.com 20260101000000\n")

        jobs = gptcron.parse_cron_file()

        self.assertEqual([job["name"] for job in jobs], ["valid-site"])

    def test_parse_cron_keeps_safe_legacy_name_with_dot(self):
        self.write_job(name="legacy.site")

        jobs = gptcron.parse_cron_file()

        self.assertEqual(jobs[0]["name"], "legacy.site")

    def test_add_rejects_path_traversal_name(self):
        gptcron.add_job("../../escape", "https://example.com", "daily")

        self.assertFalse(os.path.exists(".gptcron"))

    def test_add_normalizes_url_before_duplicate_check(self):
        self.write_job(url="http://example.com")

        gptcron.add_job("other", "example.com", "daily")

        self.assertEqual(len(gptcron.parse_cron_file()), 1)

    def test_force_argument_only_accepts_force_keyword(self):
        parser = gptcron.setup_argparse()

        args = parser.parse_args(["check_cron", "force"])

        self.assertEqual(args.force, "force")

    def test_wiki_email_mode_uses_live_url_and_email_function(self):
        self.write_config()
        llm_response = json.dumps({
            "summary": "<p>Summary</p>",
            "wikipedia_unique_points": "Wikipedia",
            "grokipedia_unique_points": "Grokipedia",
            "major_differences": "Differences",
            "bias_assessment": "Bias"
        })

        with patch.object(
            gptcron, "fetch_page_content", return_value="<html><body>Article</body></html>"
        ) as fetch_page, patch.object(
            gptcron, "call_llm", return_value=llm_response
        ), patch.object(gptcron, "send_email") as send_email:
            gptcron.compare_wikis("Artificial Intelligence", send_results_email=True)

        requested_urls = [call.args[0] for call in fetch_page.call_args_list]
        self.assertIn(
            "https://grokipedia.com/page/Artificial_Intelligence", requested_urls
        )
        send_email.assert_called_once()


if __name__ == "__main__":
    unittest.main()
