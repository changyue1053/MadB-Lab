"""Independent C09 admission supplement; never grants C07 or whole-C09 status."""
import json

from c07_companion_observations import _frame_error, _predicates
from c07_kotlin_observations import normal_shutdown
from c07_kotlin_thread_observations import parse as parse_thread


def expected_labels(route):
    labels = ({"first-runtime-open": "kotlin", "thread-armed": "thread"}
              if route == "kotlin" else {"work-held": "native", "operation-held": "operation"})
    for sample in range(2):
        if route == "kotlin":
            labels[f"thread-held-{sample}"] = "thread"
        labels[f"pending-native-{sample}"] = "kotlin" if route == "kotlin" else "native"
        if route != "kotlin":
            labels[f"pending-facade-{sample}"] = "facade"
        labels[f"reopen-rejected-{sample}"] = "vector"
        labels[f"thread-after-attempt-{sample}" if route == "kotlin" else f"after-attempt-native-{sample}"] = "thread" if route == "kotlin" else "native"
    if route == "kotlin":
        labels.update({"thread-released": "thread", "thread-final": "thread",
                       "first-runtime-closed": "kotlin", "first-js-final": "settling"})
    else:
        labels.update({"first-physical-closed": "native", "first-facade-closed": "facade"})
    labels["first-close-outcome"] = "vector"
    if route == "kotlin":
        labels.update({"second-runtime-open": "kotlin", "second-runtime-closed": "kotlin",
                       "second-js-final": "settling"})
    else:
        labels.update({"second-physical-closed": "native", "second-facade-closed": "facade"})
    labels["reopened-result"] = "vector"
    return labels


def predicates(frames, route):
    errors = []
    def need(condition, reason):
        if not condition:
            errors.append(reason)
    need(frames["first-close-outcome"] == [1, 0], "original normal close did not succeed")
    need(frames["reopened-result"] == [42], "new runtime positive control differs")
    for sample in range(2):
        pending = frames[f"pending-native-{sample}"]
        need(frames[f"reopen-rejected-{sample}"] == [1, 0, 0], "reopen did not reject while original close stayed pending")
        if route == "kotlin":
            need([pending[i] for i in (2, 12, 13)] == [0, 1, 0], "Kotlin checkpoint is not before physical join/receipt")
            for label in (f"thread-held-{sample}", f"thread-after-attempt-{sample}"):
                thread = parse_thread(frames[label])
                need(thread[3:10] == ["1"] * 7 and thread[12:14] == ["0", "0"] and thread[17:20] == ["0"] * 3,
                     label + ": actual worker hold/join no longer live")
        else:
            need([pending[i] for i in (17, 30, 32, 56, 58, 59, 60)] == [0, 1, 0, 2, 1, 0, 0]
                 and pending[55] != 2, "native checkpoint is not normal close before physical ACK/receipt")
            after = frames[f"after-attempt-native-{sample}"]
            need([after[i] for i in (17, 56, 58, 59, 60)] == [0, 2, 1, 0, 0], "rejected admission changed held worker")
            js = frames[f"pending-facade-{sample}"]
            need([js[i] for i in (5, 8, 9, 10)] == [1, 1, 0, 0], "facade is not normal pending close")
    if route == "kotlin":
        threads = [parse_thread(value) for label, value in frames.items() if label.startswith("thread-")]
        identity = threads[0][1:3]
        need(all(part != "0" for part in identity) and all(t[1:3] == identity and t[20] == "0" for t in threads),
             "thread observations cross runtime/generation or report a probe error")
        need(threads[0][10] == "1" and threads[0][12] == "0", "exit hold was not armed before close")
        need(parse_thread(frames["thread-released"])[12] == "1", "same hold release is absent")
        final = parse_thread(frames["thread-final"])
        need(final[4:7] == ["0"] * 3 and all(final[i] == "1" for i in range(10, 20)), "actual held executor did not join and retire")
        for prefix, engine_count in (("first-", 1), ("second-", 2)):
            errors.extend(normal_shutdown({"runtime-open": frames[prefix + "runtime-open"],
                "runtime-closed": frames[prefix + "runtime-closed"],
                "js-final": frames[prefix + "js-final"], "runtime-complete": [1]}, expected_engines=engine_count))
    else:
        held = frames["work-held"]
        need([held[i] for i in (14, 17, 55, 56, 57, 58, 59, 60, 65, 69)] == [1, 0, 1, 2, 1, 1, 0, 0, 1, 0],
             "no actual phase2 worker barrier")
        need(held[13] > 0 and held[62] > 0 and held[63] > 0 and held[62] != held[63], "held worker identity/work absent")
        need(frames["operation-held"][3:7] == [1, 2, 1, 0], "hold does not belong to actual operation")
        for prefix in ("first-", "second-"):
            need(frames[prefix + "physical-closed"][32] == 1, prefix + "normal receipt was not consumed")
            errors.extend(_predicates("c09-close-window", {"physical-closed": frames[prefix + "physical-closed"],
                "facade-closed": frames[prefix + "facade-closed"]}))
    return errors


def parse_observation(raw, *, nonce, pid, route):
    lines = [line for line in raw.splitlines() if nonce in line]
    errors, frames = [], {}
    if not isinstance(pid, str) or not pid.isdigit() or int(pid) <= 0:
        errors.append("probe process absent or non-unique")
    elif any(len(line.split()) < 3 or line.split()[2] != pid for line in lines):
        errors.append("nonce/PID binding mismatch")
    wanted = expected_labels(route)
    for line in lines:
        prefix = "C09_CLOSE_FRAME " + nonce + " "
        if prefix not in line:
            continue
        try:
            label, encoded = line.split(prefix, 1)[1].split(" ", 1)
            value = json.loads(encoded)
            if label in frames or label not in wanted:
                raise ValueError("duplicate or unexpected label")
            kind = wanted[label]
            if kind == "thread":
                parse_thread(value)
            elif kind in ("kotlin", "settling"):
                length = 110 if kind == "kotlin" else 9
                if (not isinstance(value, list) or len(value) != length or
                        any(type(v) is not int or not 0 <= v <= 2**53 - 1 for v in value) or
                        kind == "kotlin" and value[0] != 70501):
                    raise ValueError("malformed Kotlin observation")
            elif problem := _frame_error(value, kind):
                raise ValueError(problem)
            frames[label] = value
        except (ValueError, TypeError) as error:
            errors.append("invalid frame: " + str(error))
    failures = [line for line in lines if "PROBE_FAILED " + nonce in line]
    complete = sum("C09_CLOSE_COMPLETE " + nonce in line for line in lines)
    if complete > 1:
        errors.append("duplicate completion")
    if complete:
        if list(frames) != list(wanted):
            errors.append("required ordered observations are missing or different")
        else:
            errors.extend(predicates(frames, route))
        for marker in ("PROBE_STARTED", "PROBE_PAGE_READY", "PROBE_FINISHED"):
            if sum(marker + " " + nonce in line for line in lines) != 1:
                errors.append("missing/duplicate " + marker)
    return {"status": "failed" if errors or failures else "passed" if complete else "incomplete",
            "nonce": nonce, "pid": pid, "frames": frames, "problems": errors, "failures": failures,
            "lines": lines, "scope": "normal close before physical ACK only", "certifies_c07": False}
