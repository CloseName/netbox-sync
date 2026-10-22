# ESXi adoption review timeout investigation

Test deployment: `11a48eb5368383e128029122200fbf3549d1ce92` upgraded to
`cc53a01178cd7d8776311f5d31c29add6ff8710c`. Production was not changed.

The affected source reports 257 inventory objects. Two PLAN attempts collected
ESXi data in 3.7–4 seconds and completed `netbox_mapping` in about 0.23 seconds,
then hit the 120-second child deadline inside `netbox_review`. A different source
with 31 objects completed planning. These are different sources, not evidence
that retrying the affected source fixed it.

Comparing Python ASTs after excluding docstrings shows no executable changes in
`esxi_adoption.py` between those releases. The expensive algorithm predates the
refactoring; this comparison does not rule out changes elsewhere in planning.

For every unmanaged discovered object, classification visits target candidates.
Previously each candidate network lookup scanned and serialized every interface,
IP and MAC record again. With D discovered objects, T target candidates and N
network records, that part could require O(D*T*N) work. Managed objects bypass
this fallback, so inventory size alone does not determine runtime.

The fix builds assignment indexes once per `_NetworkIndex`, keyed by object kind
or assigned content type as well as ID. Immutable network evidence is reused for
candidate visits within that index. New plans and apply-time evidence checks
construct fresh indexes. Ownership checks, ambiguous candidates, primary IP/MAC
fallbacks, address normalization, and write confirmation remain unchanged.

An isolated local comparison using 256 candidate records, 256 VM interfaces and
256 IPs, with 32 visits to every candidate, took 8.233 seconds with the old index
and 0.005 seconds with the new index; returned evidence was identical. This is a
synthetic measurement of network lookup only, not an end-to-end QA benchmark.
Regression tests assert bounded serialization work rather than timing thresholds,
and preserve ambiguous shared-IP matches, host/VM ID isolation, primary addresses,
and fresh evidence on a new index.

Acceptance still requires a new read-only PLAN for the affected source on the test
installation, with schedules off. Check phase timings, plan classifications and
conflicts before approving any write. The 120-second deadline is unchanged.
The live timeout may have additional contributors within `netbox_review`; a
successful synthetic benchmark does not establish that all live latency is fixed.
