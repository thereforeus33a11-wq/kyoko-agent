# Work in progress: the whole app is her

These are the three parts of `opendroid/WHOLE_APP_PLAN.md`, saved as patches so the work survives the build machine. None of it is in `patch/yume-persona.patch` yet, so a build made with `build.sh` does not include it.

Each patch applies to the app tree at the save point, meaning upstream `9b471bc` with `patch/yume-persona.patch` applied. Each includes the shared `core/agent/AutomatedSender.kt`, so apply one part with `git apply`, or merge them as branches.

| Patch | Part | State |
|---|---|---|
| `words.patch` | Rules 1-3 and `CREATE_MACRO`: words that leave the phone are his or hers. Her words pass at plan start and after re-evaluation, with automated recipients left out. | Built, reviewed twice, all 11 findings fixed. Full suite: 3,745 tests, 1 failure, the known flaky `AutoReplySettingsScreenTest`, which passes alone. **Done.** |
| `record.patch` | Section 3: the sealed record of what the phone did, fed to her reply, her moments and her notebook pass. | Built and reviewed. Full suite: 3,737 tests, 1 failure, the same flaky test. Review fixes not finished. |
| `record-unfinished-fixes.patch` | A review-fix pass on top of `record.patch`, cut off by a machine restart. | Unverified: it has not been compiled or tested. |
| `off.patch` | Rules 4-8: auto-reply has no writer, the MCP server is off, social writers are hers or off, no template words, and `RUN_MACRO` checks. | Built and reviewed. Full suite: 3,625 tests, 0 failed. Review fixes not applied. |

## Review findings still to fix

**record**
- **Major:** the import marks old email auto-replies as "left open". The email channel tried an inline reply first, so one may have been sent.
- **Major:** entries are dated when the plan was made, not when it ran or ended.
- The one-time import lists the first plan after the update twice.
- A step's fallback is recorded under the primary action's name.
- On a held-back route, entries are still picked by matching his message against recipients and words.
- A plan that ends with an exception after some steps ran is not recorded.
- Clipboard words are not recorded.
- The value he typed for a missing step is not recorded.

**off**
- While she is on, the Comments tab still pre-fills the reply box with text the stock reply engine wrote earlier.
- Settings still shows an "MCP setup must be redone" card.
- An old macro with an `AUTO_REPLY_TOGGLE` step now stops at that step.
- `RUN_MACRO` treats a 3-digit number in an SMS step as a short code.
- The macro checks also apply with her off. The plan says only rules 4, 6 and 8 apply then.
