"""Normal unique-costume gift behavior, matching the Nov3.4 server."""
import json
import sqlite3
import unittest
from unittest import mock
import urllib.error

import mod_fixture as qa


class DirectSuitGrantTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.executescript("CREATE TABLE u_status(user_id);INSERT INTO u_status VALUES(7);"
                                      "CREATE TABLE u_suit(user_id,suit_master_id);"
                                      "CREATE TABLE u_authentication(user_id,session_key,command_id);")
        self.connection.execute("INSERT INTO u_authentication VALUES(7,?,4)", (b"Q" * 32,))
        self.connection.commit()
        self.android = mock.Mock()
        self.android.read.side_effect = lambda _path: self.connection.serialize()
        self.client, self.opener = mock.Mock(), mock.Mock()

    def grant(self, request, timeout):
        self.assertEqual(request.method, "POST")
        self.assertIn(b'\r\n\r\n7\r\n', request.data)
        self.assertIn(str(qa.CUSTOM_SUIT).encode(), request.data)
        self.connection.execute("INSERT INTO u_suit VALUES(7,?)", (qa.CUSTOM_SUIT,))
        self.connection.commit()
        return mock.Mock(status=200)

    def call(self):
        with mock.patch.object(qa.urllib.request, "build_opener", return_value=self.opener), \
             mock.patch.object(qa.smoke, "Client", return_value=self.client):
            return qa.grant_and_select(self.android, 7, 100200400, "ko")

    def test_unique_suit_is_read_back_directly_then_selected_without_present_calls(self):
        self.opener.open.side_effect = self.grant
        result = self.call()
        self.assertEqual(result["grant_mode"], "unique_suit_direct")
        self.assertFalse(result["present_fetch_used"])
        self.assertFalse(result["present_receive_used"])
        self.assertEqual(self.client.request.call_args_list, [
            mock.call("/communicationMember/setTheme", {"member_master_id": 2, "suit_master_id": qa.CUSTOM_SUIT, "custom_background_master_id": 100200400}),
            mock.call("/communicationMember/setFavoriteMember", {"member_master_id": 2})])
        self.assertNotIn("Q" * 32, json.dumps(result))
        self.android.write.assert_not_called()

    def test_http200_without_actual_ownership_is_not_a_success(self):
        self.opener.open.return_value = mock.Mock(status=200)
        with self.assertRaisesRegex(qa.ModFixtureError, "mod_unique_suit_grant_missing"):
            self.call()
        self.client.request.assert_not_called()

    def test_preexisting_clone_ownership_refuses_before_any_gift(self):
        self.connection.execute("INSERT INTO u_suit VALUES(7,?)", (qa.CUSTOM_SUIT,))
        self.connection.commit()
        with self.assertRaisesRegex(qa.ModFixtureError, "mod_fresh_clone_already_owned"):
            self.call()
        self.opener.open.assert_not_called()

    def test_multiple_accounts_refuse_before_any_gift(self):
        self.connection.execute("INSERT INTO u_status VALUES(8)")
        self.connection.commit()
        with self.assertRaisesRegex(qa.ModFixtureError, "mod_unique_disposable_gift_user_required"):
            self.call()
        self.opener.open.assert_not_called()

    def test_failed_http_never_selects_or_exposes_response_text(self):
        secret = "private-session-material"
        self.opener.open.side_effect = urllib.error.HTTPError("http://127.0.0.1", 403, secret, {}, None)
        with self.assertRaisesRegex(qa.ModFixtureError, "mod_gift_request_rejected") as caught:
            self.call()
        self.assertNotIn(secret, str(caught.exception))
        self.client.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
