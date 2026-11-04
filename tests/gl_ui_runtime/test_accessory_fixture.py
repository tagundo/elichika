import base64
from email import policy
from email.parser import BytesParser
import io
import json
import sqlite3
import unittest
from unittest import mock
import urllib.error

import accessory_fixture as fixture


SESSION = b"test-session-data".ljust(32, b"!")
UID = 123
FIRST_INSTANCE = 2**53 + 11


class Device:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("""
            CREATE TABLE u_status(user_id INTEGER PRIMARY KEY);
            INSERT INTO u_status VALUES(123);
            CREATE TABLE u_authentication(user_id INTEGER,session_key BLOB,command_id INTEGER);
            CREATE TABLE u_accessory(user_id INTEGER,user_accessory_id INTEGER,accessory_master_id INTEGER);
            CREATE TABLE u_present_item(user_id INTEGER,id INTEGER,content_type INTEGER,
                content_id INTEGER,content_amount INTEGER,present_route_type INTEGER);
        """)
        self.db.execute("INSERT INTO u_authentication VALUES(?,?,?)", (UID, SESSION, 17))
        self.db.commit()
        self.commands = []
        self.api = []
        self.posts = []
        self.next_instance = FIRST_INSTANCE
        self.http_status = 200
        self.grant_changes_state = True
        self.api_error = None
        self.fetch_override = None

    def shell(self, *args):
        self.commands.append(args)

    def read(self, path):
        assert path == f"{fixture.FILES}/userdata.db"
        self.db.commit()
        return self.db.serialize()

    def present(self, master, route=2, amount=1):
        present_id = self.db.execute("SELECT COALESCE(MAX(id),0)+1 FROM u_present_item").fetchone()[0]
        self.db.execute("INSERT INTO u_present_item VALUES(?,?,?,?,?,?)", (UID, present_id, 23, master, amount, route))
        self.db.commit()
        return present_id

    def owned(self, master, instance=FIRST_INSTANCE - 1):
        self.db.execute("INSERT INTO u_accessory VALUES(?,?,?)", (UID, instance, master))
        self.db.commit()


class FakeClient:
    def __init__(self, device):
        self.device = device

    def request(self, endpoint, payload):
        d = self.device
        d.api.append((endpoint, payload))
        assert self.uid == UID and self.session == SESSION and type(self.command) is int
        if d.api_error:
            raise RuntimeError(d.api_error)
        self.command += 1
        if endpoint == "/present/fetch":
            if d.fetch_override is not None:
                return d.fetch_override
            items = [{"id": row[0], "content": {"content_type": row[1], "content_id": row[2],
                      "content_amount": row[3]}, "present_route_type": row[4]}
                     for row in d.db.execute("SELECT id,content_type,content_id,content_amount,present_route_type FROM u_present_item")]
            return {"present_items": items}
        assert endpoint == "/present/receive" and len(payload["ids"]) <= 2
        for present_id in payload["ids"]:
            assert type(present_id) is int and 0 < present_id < 2**31
            row = d.db.execute("SELECT content_id,content_amount,present_route_type FROM u_present_item WHERE id=?", (present_id,)).fetchone()
            assert row[0] in fixture.TARGETS and row[1:] == (1, 2)
            d.owned(row[0], d.next_instance)
            d.next_instance += 1
            d.db.execute("DELETE FROM u_present_item WHERE id=?", (present_id,))
        d.db.commit()
        return {"limit_exceeded_items": []}


class FakeResponse:
    status = 200

    def read(self, *_):
        raise AssertionError("WebUI HTML must not be read")

    def close(self):
        pass


class FakeOpener:
    def __init__(self, device):
        self.device = device

    def open(self, request, timeout):
        d = self.device
        assert request.full_url == fixture.WEBUI_URL and timeout == 30 and request.get_method() == "POST"
        message = BytesParser(policy=policy.default).parsebytes(
            ("Content-Type: " + request.get_header("Content-type") + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + request.data)
        fields = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True).decode()
                  for part in message.iter_parts()}
        assert fields == {"user_id": str(UID), "user_session_key": base64.b64encode(SESSION).decode(),
                          "content_type": "23", "content_id": fields["content_id"], "content_amount": "1"}
        master = int(fields["content_id"])
        assert master in fixture.TARGETS
        d.posts.append(master)
        if d.grant_changes_state:
            d.present(master)
        if d.http_status != 200:
            raise urllib.error.HTTPError(request.full_url, d.http_status, "unrecorded-html",
                {"Location": "https://never-follow.invalid/?session=" + base64.b64encode(SESSION).decode()},
                io.BytesIO(SESSION))
        return FakeResponse()


class AccessoryFixtureTests(unittest.TestCase):
    def setUp(self):
        self.device = Device()
        self.addCleanup(self.device.db.close)

    def invoke(self, uid=UID):
        self.report = {}
        with mock.patch.object(fixture, "Client", side_effect=lambda *_: FakeClient(self.device)), \
                mock.patch.object(fixture.time, "sleep") as sleep, \
                mock.patch.object(fixture.urllib.request, "build_opener", return_value=FakeOpener(self.device)) as build:
            result = fixture.seed_accessories(self.device, uid, self.report)
        sleep.assert_called_once_with(2)
        self.assertEqual(self.device.commands, [("am", "force-stop", fixture.GAME)])
        self.assertTrue(result["game_stopped"])
        if self.device.posts:
            self.assertTrue(any(isinstance(handler, fixture.NoRedirect) for handler in build.call_args.args))
        self.assertNotIn(SESSION.decode(), json.dumps(self.report))
        self.assertNotIn(base64.b64encode(SESSION).decode(), json.dumps(self.report))
        return result

    def test_grants_exact_two_and_preserves_int64_instance_ids(self):
        result = self.invoke()
        self.assertEqual(self.device.posts, list(fixture.TARGETS))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["granted_count"], 2)
        ids = [row["user_accessory_ids"][0] for row in result["owned_after"]]
        self.assertEqual(ids, [FIRST_INSTANCE, FIRST_INSTANCE + 1])
        self.assertTrue(all(type(value) is int for value in ids))

    def test_owned_target_skips_grant_and_existing_admin_present_is_reused(self):
        self.device.owned(303313)
        existing = self.device.present(304511)
        result = self.invoke()
        self.assertEqual(self.device.posts, [])
        self.assertEqual(result["reused_present_count"], 1)
        self.assertEqual([p for ep, p in self.device.api if ep == "/present/receive"], [{"ids": [existing]}])

    def test_already_owned_both_is_a_noop(self):
        for i, master in enumerate(fixture.TARGETS):
            self.device.owned(master, FIRST_INSTANCE + i)
        result = self.invoke()
        self.assertEqual(self.device.posts, [])
        self.assertEqual(self.device.api, [])
        self.assertEqual(result["received_present_count"], 0)

    def test_only_exact_admin_targets_are_received(self):
        self.device.present(999999)
        self.device.present(304511, route=3)
        existing = self.device.present(303313)
        result = self.invoke()
        self.assertEqual(self.device.posts, [304511])
        self.assertEqual(result["received_present_count"], 2)
        self.assertEqual(self.device.db.execute("SELECT COUNT(*) FROM u_present_item").fetchone()[0], 2)
        self.assertIn(existing, next(p["ids"] for ep, p in self.device.api if ep == "/present/receive"))

    def test_redirects_are_not_followed_and_signed_fetch_confirms_grant(self):
        for status in (302, 303):
            with self.subTest(status=status):
                self.device.db.execute("DELETE FROM u_accessory")
                self.device.http_status = status
                self.device.commands.clear()
                self.device.posts.clear()
                result = self.invoke()
                self.assertEqual([row["status"] for row in result["webui_http_statuses"]], [status, status])
                self.assertIsNone(fixture.NoRedirect().redirect_request(None, None, status, "", {}, "https://never-follow.invalid"))

    def test_200_without_grant_fails_without_receiving_anything(self):
        self.device.grant_changes_state = False
        with self.assertRaisesRegex(fixture.AccessoryFixtureError, "accessory_grant_not_confirmed"):
            self.invoke()
        self.assertFalse(any(ep == "/present/receive" for ep, _ in self.device.api))

    def test_pending_target_outside_fetch_page_does_not_trigger_duplicate_grant(self):
        self.device.present(303313)
        self.device.fetch_override = {"present_items": []}
        with self.assertRaisesRegex(fixture.AccessoryFixtureError, "accessory_pending_present_not_visible"):
            self.invoke()
        self.assertEqual(self.device.posts, [])

    def test_raw_errors_and_authentication_never_reach_report_or_exception(self):
        secret = base64.b64encode(SESSION).decode()
        self.device.api_error = "raw response with session " + secret
        with self.assertRaises(fixture.AccessoryFixtureError) as caught:
            self.invoke()
        self.assertEqual(str(caught.exception), "accessory_fixture_operation_failed")
        self.assertNotIn(secret, json.dumps(self.report))

    def test_webui_error_status_is_safe_and_never_received(self):
        self.device.http_status = 403
        self.device.grant_changes_state = False
        with self.assertRaisesRegex(fixture.AccessoryFixtureError, "accessory_webui_http_rejected"):
            self.invoke()
        self.assertEqual(self.report["accessory_fixture"]["http_status"], 403)
        self.assertNotIn(base64.b64encode(SESSION).decode(), json.dumps(self.report))
        self.assertFalse(any(ep == "/present/receive" for ep, _ in self.device.api))

    def test_boolean_present_id_and_wrong_quantity_are_not_claimed_or_regranted(self):
        self.device.present(303313)
        for present_id, amount in ((True, 1), (1, 2), (2**31, 1)):
            self.device.fetch_override = {"present_items": [{"id": present_id, "present_route_type": 2,
                "content": {"content_type": 23, "content_id": 303313, "content_amount": amount}}]}
            with self.assertRaisesRegex(fixture.AccessoryFixtureError, "accessory_target_present_invalid"):
                self.invoke()
        self.assertEqual(self.device.posts, [])
        self.assertFalse(any(ep == "/present/receive" for ep, _ in self.device.api))

    def test_owned_instance_schema_rejects_non_integer_without_logging_value(self):
        secret = base64.b64encode(SESSION).decode()
        self.device.owned(303313, secret)
        with self.assertRaisesRegex(fixture.AccessoryFixtureError, "accessory_owned_schema_invalid"):
            self.invoke()
        self.assertNotIn(secret, json.dumps(self.report))
        self.assertEqual(self.device.posts, [])

    def test_missing_user_and_bad_session_fail_before_api_mutation(self):
        self.device.db.execute("DELETE FROM u_status")
        with self.assertRaisesRegex(fixture.AccessoryFixtureError, "accessory_user_missing"):
            self.invoke()
        self.device.db.execute("INSERT INTO u_status VALUES(?)", (UID,))
        self.device.db.execute("UPDATE u_authentication SET session_key=?", (b"short",))
        with self.assertRaisesRegex(fixture.AccessoryFixtureError, "accessory_authentication_invalid"):
            self.invoke()
        self.assertEqual(self.device.posts, [])
        self.assertEqual(self.device.api, [])


if __name__ == "__main__":
    unittest.main()
