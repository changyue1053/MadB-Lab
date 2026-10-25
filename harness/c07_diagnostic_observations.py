"""Independent obligations for live thread witnesses and child ownership return."""
SCENARIOS = {
    "live-cleanup-threads": {"live-cleanup-held": "native", "live-cleanup-returned": "native"},
    "child-ownership-baseline": {"child-open-baseline": "native", "child-returned-baseline": "native",
                                 "child-baseline-values": "vector"},
}
GATED = {"live-cleanup-threads"}


def predicates(case, frames):
    problems = []
    def need(condition, message):
        if not condition:
            problems.append(message)
    if case == "live-cleanup-threads":
        held, done = frames["live-cleanup-held"], frames["live-cleanup-returned"]
        need(all(held[i] == value for i, value in {13: 1, 14: 1, 17: 0, 58: 1, 59: 0,
             60: 0, 65: 1, 66: 0, 67: 0, 68: 1, 69: 0}.items()), "cleanup witness was not captured while business work and join remained live")
        need(min(held[62:65]) > 0 and len(set(held[62:65])) == 3,
             "owner, business and cleanup thread witnesses are not concurrently distinct")
        need(all(done[i] == 1 for i in (16, 17, 59, 60, 66, 67, 68, 69, 70)),
             "live cleanup witness did not progress to actual TLS/join/executor completion")
    elif case == "child-ownership-baseline":
        before, after = frames["child-open-baseline"], frames["child-returned-baseline"]
        retained = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 24, 25, 28, 29, 35)
        need(all(after[i] == before[i] for i in retained), "child close did not restore the open-runtime retained-owner baseline")
        need(all(after[i] == value for i, value in {14: 1, 16: 0, 17: 0, 40: 1, 41: 0,
             44: 1, 45: 0, 50: 1, 51: 0}.items()), "child cleanup was substituted with whole-runtime shutdown")
        need(after[33] > before[33] and after[33] - before[33] == after[34] - before[34] and
             after[36] == before[36] + 1, "actual provider computation or paired model release delta is missing")
        need(frames["child-baseline-values"] == [42, 1], "worker value or exact callback count differs")
    return problems
