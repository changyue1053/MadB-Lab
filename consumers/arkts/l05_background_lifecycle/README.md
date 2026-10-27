# L05 real background and foreground lifecycle

This independent development consumer uses the frozen ordinary C HAR and the
separately pinned public `StateObservation`/`ArkUIStateModel` source delivery.
It adds no SDK export and imports no MadB private module. The source supplement
is not a published package or a new C07 candidate.

The page owns one model/observation. The application owns one Runtime, Engine,
ordinary observer and all asynchronous background/resume drain attempts. A real
UI button requests `UIAbilityContext.moveAbilityToBackground()`; only actual
`UIAbility.onBackground()` counts as background entry. That synchronous callback
requests stop and retains the complete asynchronous close in the application.
It does not claim that the OS awaits a Promise returned by this callback.

After the close confirms, while the same ability remains in background, a real
native publication must reach the shared ordinary observer. The page model must
retain its last foreground value, and the same Engine must still roundtrip. Only
after these observations does the runner use `aa start` to restore the ability.
The actual `onForeground()` callback waits for the retained attempt, checks its
lifecycle generation and reattaches once. An actual UI hierarchy must show
`EMPTY` before the next publication. Three cycles retain the same ability/page,
Runtime/Engine and ordinary observer; a fourth foreground publication precedes
the fully awaited page/ordinary/Engine/Runtime close.

The independent oracle requires 21 ordered frames and 9 UI phases. Ordinary
values are exactly `[1, 2, 11, 12, 21, 22, 31]`; the three even values occur after
confirmed page drain and before the corresponding foreground callback. A reused
nonce/PID, duplicate, missing, reordered or differently valued frame is rejected.
The runner stores raw commands, layout captures, lifecycle logs, source archive,
Release HAP/signing identity and before/after public/tool/Lab input observations.

Use the Lab-pinned Python and the existing locked platform toolchain:

```sh
python3 -B scripts/verify_l05_background_lifecycle.py \
  --candidate /absolute/path/to/c-ordinary/candidate \
  --expected-candidate-digest sha256:trusted_candidate_digest \
  --observation-source /absolute/path/to/public-source-delivery \
  --expected-state-sha256 trusted_state_sha256 \
  --expected-ui-sha256 trusted_ui_sha256 \
  --command-line-tools /absolute/path/to/locked/command-line-tools \
  --java-home /absolute/path/to/locked/jbr/Contents/Home \
  --target explicit-device-id --target-kind emulator \
  --community-debug-signing --output /absolute/path/to/new-output
```

`--build-only` performs public/tool/target admission and Release HAP compilation,
without installing or running the consumer. It reports `result=build_only` and
`target_execution/native/ui=not_run`. Real target execution requires a clean
frozen Lab revision; compilation of uncommitted sources is development evidence.
The fixed bundle is `com.madb.l05background`. Only this consumer is installed,
stopped and uninstalled. Shared hdc, the emulator and unrelated applications are
not stopped. Device cleanup is separate from public native close confirmation.

The result covers only this finite ordinary C scenario on the recorded target.
It does not establish long-lived background execution permission, process
survival, rotation, destruction, concurrent pages, physical-device coverage or
all ArkTS routes. A target that cannot complete the work before foreground
restoration fails with the actual missing evidence; restoration is never used
to relabel deferred work as background delivery. Post-drain publication is not
an already queued late-callback interleaving. Native close failure/retry injection,
strict native resource counters and test-companion gates remain separate work.
Community debug signing is not production signing. Old C07/L05 reports and
candidate certifications remain unchanged.
