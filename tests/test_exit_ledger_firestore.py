import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.api_core.exceptions import AlreadyExists
from state import firestore_state


class _Snapshot:
    def __init__(self, data=None, exists=True):
        self._data = data or {}
        self.exists = exists

    def to_dict(self):
        return dict(self._data)


class _Ref:
    def __init__(self, collection, key):
        self.collection = collection
        self.key = key

    def create(self, data, **kwargs):
        if self.key in self.collection.docs:
            raise AlreadyExists("already claimed")
        self.collection.docs[self.key] = dict(data)

    def get(self, **kwargs):
        if self.key not in self.collection.docs:
            return _Snapshot(exists=False)
        return _Snapshot(self.collection.docs[self.key])

    def set(self, data, merge=False, **kwargs):
        if merge:
            self.collection.docs.setdefault(self.key, {}).update(data)
        else:
            self.collection.docs[self.key] = dict(data)


class _Collection:
    def __init__(self):
        self.docs = {}

    def document(self, key):
        return _Ref(self, key)

    def where(self, field, op, value):
        self.where_args = (field, op, value)
        return self

    def stream(self, **kwargs):
        return [
            _Snapshot(data)
            for data in self.docs.values()
            if data.get("active") is True
        ]


class _Db:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        return self.collections.setdefault(name, _Collection())


class _FailingDb(_Db):
    def collection(self, name):
        raise TimeoutError("firestore unavailable")


class TestDedicatedExitLedger(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        self.intent = {
            "status": "submitting",
            "position": {"symbol": "TQQQ", "entry_ts": "2026-08-24T19:00:00"},
            "entry_ts": "2026-08-24T19:00:00",
            "order_ids": [],
        }

    def test_claim_is_unique_and_second_claim_does_not_overwrite(self):
        with patch.object(firestore_state, "_get_db", return_value=self.db):
            first = firestore_state.claim_exit_intent("position-1", self.intent)
            second = firestore_state.claim_exit_intent("position-1", self.intent)

        self.assertTrue(first["claimed"])
        self.assertFalse(second["claimed"])
        self.assertEqual(first["ledger_id"], second["ledger_id"])
        self.assertEqual(second["record"]["version"], 1)

    def test_updates_are_versioned_and_completed_intent_is_not_active(self):
        with patch.object(firestore_state, "_get_db", return_value=self.db):
            claimed = firestore_state.claim_exit_intent("position-1", self.intent)
            self.assertTrue(firestore_state.update_exit_intent(
                claimed["ledger_id"], {"status": "submitted", "order_ids": ["o1"]}
            ))
            active = firestore_state.read_active_exit_ledger()
            self.assertIn("position-1", active)
            self.assertEqual(active["position-1"]["version"], 2)
            self.assertTrue(firestore_state.complete_exit_intent(
                claimed["ledger_id"], "broker confirmed legs absent"
            ))
            self.assertEqual(firestore_state.read_active_exit_ledger(), {})

    def test_claim_failure_is_not_authorized_to_send(self):
        with patch.object(firestore_state, "_get_db", return_value=_FailingDb()):
            result = firestore_state.claim_exit_intent("position-1", self.intent)
        self.assertFalse(result["claimed"])
        self.assertTrue(result["unavailable"])


if __name__ == "__main__":
    unittest.main()
