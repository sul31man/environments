"""Blind independent oracle (oracle C) -- differential soundness check.

Provenance: authored BLIND by a separate model (Sonnet) from the prose SEMANTICS spec
ALONE -- it read no source, imports NO mig_lh module, and shares NO code with the
reference reducer (dataplane.reduce_theta) or the transposed oracle_b
(generator.reduce_theta_b). Unlike oracle_b (which reuses dp._is_kept / _causal_order /
cell_index and only varies the loop), this reimplements the keep-filter, causal order,
feature-schema cell mapping, and fold from scratch. Agreement therefore validates the
SHARED CORE, not just the loop structure.

Verified: 51/51 released instances agree byte-for-byte with the reference graded terminal.
Signature: reduce(mutations, context, theta_dict) -> {record_id: snapshot}
  theta_dict = {"counter":[..36], "head_elig":[..36], "head_sel":"FIRST"|"LAST"}
"""
def reduce(mutations, context, theta):
    from collections import defaultdict

    OPS = ("CREATE", "UPDATE", "RECREATE")
    STATUS_ROLES = ("NONE", "ACT", "FAIL")
    EPOCH_CLASS = ("CUR", "SUP")
    ORDINAL = ("FIRST", "REST")
    STATUS_RANK = {"ACTIVE": 1, "PENDING": 2, "SUSPENDED": 3, "FAILED": 4, "ARCHIVED": 5}

    epoch_of_lease = (context.get("epoch_of_lease") or {}) if context else {}
    handoff = (context.get("handoff") or {}) if context else {}
    checkpoint = (context.get("checkpoint") or {}) if context else {}

    groups = defaultdict(list)
    for m in mutations:
        groups[m["record_id"]].append(m)

    def observed_lookup(obs, pid):
        if pid in obs:
            return obs[pid]
        if str(pid) in obs:
            return obs[str(pid)]
        return 0

    def happens_before(a, b):
        obs_b = b.get("observed") or {}
        if observed_lookup(obs_b, a["partition_id"]) >= a["local_seq"]:
            return True
        if a["partition_id"] == b["partition_id"] and a["local_seq"] < b["local_seq"]:
            return True
        return False

    out = {}

    for rid, muts in groups.items():
        sorted_muts = sorted(
            muts,
            key=lambda m: (m["arrival"], m["commit_seq"] if m["commit_seq"] is not None else -1),
        )
        seen_ids = set()
        deduped = []
        for m in sorted_muts:
            mid = m["mutation_id"]
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            deduped.append(m)

        kept = []
        for m in deduped:
            if m["commit_seq"] is None:
                continue
            lease = m["writer_lease"]
            if handoff.get(lease) == "CLEAN" and m["local_seq"] > checkpoint.get(lease, 0):
                continue
            kept.append(m)

        if not kept:
            continue

        remaining = list(kept)
        order = []
        while remaining:
            ready = []
            for x in remaining:
                blocked = False
                for y in remaining:
                    if y is x:
                        continue
                    if happens_before(y, x):
                        blocked = True
                        break
                if not blocked:
                    ready.append(x)
            if not ready:
                ready = list(remaining)
            ready.sort(
                key=lambda m: (
                    m["commit_seq"] is None,
                    m["commit_seq"] if m["commit_seq"] is not None else (1 << 60),
                    m["partition_id"],
                    m["local_seq"],
                    m["arrival"],
                    m["mutation_id"],
                )
            )
            chosen = ready[0]
            order.append(chosen)
            remaining.remove(chosen)

        counter = 0
        status = "ACTIVE"
        tags = []
        is_deleted = False
        first_seen = False
        head_candidates = []

        for pos, m in enumerate(order):
            op = m.get("operation") or "UPDATE"
            fo = m.get("field_ops") or {}

            if op == "DELETE":
                is_deleted = True
                continue

            if op in ("CREATE", "RECREATE"):
                is_deleted = False

            ordinal = "FIRST" if not first_seen else "REST"
            first_seen = True

            op_key = op if op in OPS else "UPDATE"

            if "status" not in fo:
                status_role = "NONE"
            elif fo["status"] == "FAILED":
                status_role = "FAIL"
            else:
                status_role = "ACT"

            if not epoch_of_lease:
                epoch_class = "CUR"
            else:
                cur = max(epoch_of_lease.values())
                if epoch_of_lease.get(m["writer_lease"], -1) == cur:
                    epoch_class = "CUR"
                else:
                    epoch_class = "SUP"

            cell = (
                (OPS.index(op_key) * 3 + STATUS_ROLES.index(status_role)) * 2
                + EPOCH_CLASS.index(epoch_class)
            ) * 2 + ORDINAL.index(ordinal)

            if "status" in fo and STATUS_RANK.get(fo["status"], 0) >= STATUS_RANK.get(status, 0):
                status = fo["status"]

            for t in fo.get("tags_add", []):
                if t not in tags:
                    tags.append(t)

            if "counter" in fo:
                mode = theta["counter"][cell]
                if mode == 0:
                    counter += int(fo["counter"])
                elif mode == 1:
                    counter -= int(fo["counter"])

            if "head" in fo and fo["head"] is not None and theta["head_elig"][cell]:
                head_candidates.append((pos, fo["head"]))

        if head_candidates:
            head_candidates.sort(key=lambda x: x[0])
            if theta["head_sel"] == "FIRST":
                head = head_candidates[0][1]
            else:
                head = head_candidates[-1][1]
        else:
            head = None

        out[rid] = {
            "record_id": rid,
            "is_deleted": is_deleted,
            "value": {
                "counter": counter,
                "status": status,
                "tags": sorted(tags),
                "head": head,
            },
        }

    return out
