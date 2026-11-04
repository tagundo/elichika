"""RAM-only catalog replacement facts; no real updater/Android execution."""
import unittest
from unittest import mock

import mod_loss_control as qa
from test_mod_fixture import stock_inputs, user_data, android_for, UID


class LossCatalogTests(unittest.TestCase):
    def setUp(self):
        self.stock = stock_inputs()
        self.modded = qa.mod.build_copies(self.stock)
        self.fixture = {"source_suit_id": qa.mod.SOURCE_SUIT, "custom_suit_id": qa.mod.CUSTOM_SUIT,
                        "components": qa.mod.public_components(self.modded),
                        "selection": qa.mod.selected_state(android_for(self.modded), UID)}

    def test_missing_custom_master_with_retained_selection_is_a_distinct_fact(self):
        # Separate stock bytes represent a replacement payload in this unit
        # test; the runtime control never deletes/restores database content.
        with mock.patch.object(qa.positive, "verify_imported_content", return_value={"live_id": 13001}), \
             mock.patch.object(qa.positive, "verify_titles", return_value={}):
            result = qa.catalog_loss(android_for(self.stock), self.fixture, UID)
        self.assertTrue(result["custom_master_missing"])
        self.assertTrue(result["selection_retained"])
        self.assertEqual(result["selection"]["selected_suit_id"], qa.mod.CUSTOM_SUIT)
        self.assertTrue(all(count == 0 for count in result["custom_master_rows"].values()))
        self.assertEqual(result["catalog_components"][qa.mod.ASSET_PATH]["crypto_alias_rows"], 0)

    def test_a_preserved_clone_does_not_count_as_expected_loss(self):
        with self.assertRaisesRegex(qa.policy.ModLossControlError, "negative_expected_catalog_loss_not_observed"):
            qa.catalog_loss(android_for(self.modded), self.fixture, UID)

    def test_stock_selection_or_ownership_loss_cannot_be_observed_as_this_control(self):
        for userdata in (user_data(selected=qa.mod.SOURCE_SUIT), user_data(owned=False)):
            with self.subTest(), self.assertRaises(qa.mod.ModFixtureError):
                qa.catalog_loss(android_for(self.stock, userdata), self.fixture, UID)


if __name__ == "__main__":
    unittest.main()
