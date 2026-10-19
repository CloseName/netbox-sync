# Product findings separated from browser maintenance

Baseline: main `0f74ac1c89905dcadbf5880f27e98f7cd05d3281` after PR #5.
The browser-maintenance change modifies tests and documentation only. These
findings are not silently fixed by changing expectations.

## Confirmed: light-theme control boundary contrast

Reproduction, from `frontend`:

```sh
npx playwright test ui-hardening.spec.ts --grep "semantic text and control contrast light" --workers=1
```

The existing test requires control-border/surface-raised contrast of at least 3.0.
Computed tokens are `#819da6` and `#ffffff`, giving **2.874016064136418**.
`src/ui/workspace.css` overrides the earlier tokens from `src/ui/tokens.css`;
`src/main.tsx` imports workspace styles last. `src/ui/foundation.css` uses these
tokens for ordinary buttons, inputs, selects and textareas. This is an actual
style-token mismatch with the existing accessibility requirement, not an obsolete
selector. Dark theme has a separate token set.

A separate visual change should choose a darker light-theme boundary token,
verify its computed ratio and inspect ordinary, hover, focused and disabled
controls in both themes. Preserve the 3.0 test threshold. No color change,
expected-failure annotation, retry or skip is included in browser maintenance.

## Investigated: expired plan blocked for operator/admin

This was incomplete test data, not a confirmed product defect. `SourceSync`
requires a successful lifecycle read before enabling Plan or Discovery. The old
fixture returned 404 for that request. It now supplies the active source state
with a valid 64-character revision. Viewer restrictions, expired-result notices,
reload behavior and the zero-write assertion remain exercised.

## Investigated: filtered source missing

The old scenario expected Source 001 while opening `site=obsolete`, `schedule=off`
and `attention=yes`. `querySources` intentionally still applies supported URL
filters. The test now verifies the empty result, then navigates explicitly to the
provider-only scope before testing refresh and bulk actions. No filtering behavior
was changed or declared obsolete merely because its controls moved.

## Independent Selectel limitations

Mocked browser success does not resolve Selectel import/matching failures or
native NetBox permission failures. [Selectel remains experimental](selectel-status.md).
No production service was accessed or deployed during this work.

## Contrast resolution follow-up

After PR #6, the separate contrast change starts from main
`08126e98d00196eee391cfd4863509b5af433228`. It changes only the light-theme
`--control-border` token in `workspace.css` from `#819da6` to `#718d96`.
The boundary-to-white ratio becomes **3.528**, with **3.107** against the light
hover surface `#eaf2f3`. This gives margin above the existing 3.0 requirement
without altering the dark-theme override or any interaction behavior.

Desktop and mobile screenshots of destination settings and the source connection
form were inspected. The existing contrast assertion remains unchanged; no tests
are skipped or marked as expected failures. Validation results follow below.

Validation: complete Chromium suite **367 passed, 0 failed, 0 skipped**,
with three workers and retries disabled (`npx playwright test --workers=3 --reporter=json`).
Frontend unit tests: 93 passed. Typecheck/build passed with the existing large-chunk
warning. `git diff --check` passed. No deployment or live-provider acceptance is implied.
