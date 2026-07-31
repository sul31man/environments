"""migrate.py -- the migration service YOU implement.

Implement `reduce(mutations, context)`: fold the event stream into the correct,
concurrency-safe durable state, one entry per record -- the state the LEGACY system
actually produced. The concurrency SEMANTICS (how writes ORDER and how their fields
COMBINE, and how failover / checkpoint / delete-recreate behave) are NOT given here;
recover them from the production evidence (incident.replay divergence, lineage.inspect,
sample records, qualification metrics, the failure diagnostic) as you drive the migration.

INPUT
  mutations: list of dicts, each with:
    record_id, partition_id, operation ("CREATE"|"UPDATE"|"DELETE"|"RECREATE"),
    commit_seq (int, or None if never acknowledged), writer_lease (str), local_seq (int),
    observed ({partition_id: local_seq} watermark this write had seen acked),
    field_ops (dict, any subset of: "counter" (int delta), "status" (str), "tags_add"
      (list[str]), "head" ({"v": int})), mutation_id (str), updated_at (int, an
      unreliable wall-clock), arrival (int).
  context: dict delivered at deploy -- {"epoch_of_lease": {lease: epoch},
    "handoff": {lease: "CRASH"|"CLEAN"}, "checkpoint": {lease: local_seq}}.

OUTPUT  (this is the exact GRADED format -- get it right and only the semantics remain)
  dict {record_id: {"record_id": str, "is_deleted": bool, "value": {...}}}.
  `value` has EXACTLY these four fields, whose NEUTRAL (empty-record) state is:
      {"counter": 0, "status": "ACTIVE", "tags": [], "head": null}
  A write's field_ops modify the value: `counter` is a signed DELTA, `status` and `head`
  set their field, `tags_add` adds tags (`tags` is a SORTED, de-duplicated list of str).
  `is_deleted` is True once a record has been DELETEd (until it is recreated).
  The environment fills in `value_digest`; it IGNORES every other field (partition,
  watermarks, last-operation), so you only need `is_deleted` + `value` right per record.

PUBLIC vs HIDDEN
  The public test runs a CLEAN slice: each record gets a SINGLE in-order write, so its
  value is just the neutral value with that one write's field_ops applied -- ANY reducer
  that produces that (defaulting status to "ACTIVE", tags to [], head to null) passes and
  can deploy. The hidden qualification then runs concurrent overlap, writer failover, CDC
  reorder/replay, and delete/recreate -- where the ORDER and the field COMBINATION rules
  are the traps. A last-write-wins / whole-record reducer passes public and FAILS hidden.
"""


def reduce(mutations, context):
    # TODO: recover the concurrency semantics (ordering + field combination + failover /
    # checkpoint / delete-recreate) from the production evidence and implement them. This
    # stub does no work and scores the floor.
    return {}
