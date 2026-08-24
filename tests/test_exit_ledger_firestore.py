import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.api_core.exceptions import AlreadyExists
from state import firestore_state


class _Snapshot:
    def __init__(self, data=None, exists=True, update_time=None):
        self._data = data or {}
        self.exists = exists
        self.update_time = update_time

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
        return _Snapshot(
            self.collection.docs[self.key],
            update_time=getattr(self.collection, "update_time", None),
        )

    def update(self, data, option=None, **kwargs):
        self.collection.last_option = option
        self.collection.docs.setdefault(self.key, {}).update(data)

    def set(self, data, merge=False, **kwargs):
        if merge:
            self.collection.docs.setdefault(self.key, {}).update(data)
        else:
            self.collection.docs[self.key] = dict(data)


class _Collection:
    def __init__(self):
        self.docs = {}
        self.update_time = None
        self.last_option = None

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

    def write_option(self, **kwargs):
        return kwargs


class _FailingDb(_Db):
    def collection(self, name):
        raise TimeoutError("firestore unavailable")


class _SnapshotRef:
    def __init__(self, data=None):
        self.data = data

    def get(self, **kwargs):
        return _Snapshot(self.data, exists=self.data is not None)


class _SnapshotCollection:
    def __init__(self, docs):
        self.docs = docs

    def document(self, key):
        return _SnapshotRef(self.docs.get(key))


class _SnapshotDb:
    def __init__(self, docs):
        self.collection_data = {"polaris": _SnapshotCollection(docs)}

    def collection(self, name):
        return self.collection_data[name]


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

    def test_updates_use_last_update_precondition_when_snapshot_has_timestamp(self):
        collection = self.db.collection("polaris_exit_ledger")
        with patch.object(firestore_state, "_get_db", return_value=self.db):
            claimed = firestore_state.claim_exit_intent("position-1", self.intent)
            collection.update_time = "version-1"
            self.assertTrue(firestore_state.update_exit_intent(
                claimed["ledger_id"], {"status": "submitted"}
            ))
        self.assertEqual(collection.last_option, {"last_update_time": "version-1"})

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

    def test_snapshot_intent_survives_empty_dedicated_collection(self):
        key = "legacy-position"
        snapshot = {
            "payload": {
                "exit_intents": {key: {
                    "status": "submitted", "reason": "legacy-stop",
                    "order_ids": ["legacy-order"],
                }},
                "exit_history": [],
                "open_broker_orders": [],
            }
        }
        db = _SnapshotDb({date.today().isoformat(): snapshot})
        with patch.object(firestore_state, "_get_db", return_value=db), patch.object(
            firestore_state, "read_active_exit_ledger", return_value={}
        ):
            ledger = firestore_state.read_exit_ledger(max_days=2)
        self.assertEqual(ledger["source"], "dedicated+snapshot")
        self.assertIn(key, ledger["exit_intents"])
        self.assertTrue(ledger["exit_intents"][key]["ledger_id"].startswith("exit-"))

    def test_dedicated_read_failure_is_reported_with_legacy_snapshot(self):
        key = "legacy-position"
        snapshot = {
            "payload": {
                "exit_intents": {key: {
                    "status": "submitted", "reason": "legacy-stop",
                    "order_ids": ["legacy-order"],
                }},
                "exit_history": [],
                "open_broker_orders": [],
            }
        }
        db = _SnapshotDb({date.today().isoformat(): snapshot})
        with patch.object(firestore_state, "_get_db", return_value=db), patch.object(
            firestore_state, "read_active_exit_ledger", return_value=None
        ):
            ledger = firestore_state.read_exit_ledger(max_days=2)
        self.assertTrue(ledger["dedicated_read_failed"])
        self.assertIn(key, ledger["exit_intents"])

    def test_claim_failure_is_not_authorized_to_send(self):
        with patch.object(firestore_state, "_get_db", return_value=_FailingDb()):
            result = firestore_state.claim_exit_intent("position-1", self.intent)
        self.assertFalse(result["claimed"])
        self.assertTrue(result["unavailable"])


if __name__ == "__main__":
    unittest.main()
