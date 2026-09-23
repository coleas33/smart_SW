# Contract: One Review per Model, Kept

Normative for FR-020 to FR-023, SC-005 and the session edge cases.

## 1. The host's record

`SessionRecord` gains `Document` (the `PageDocument` `review.started` names, captured before the
dump), `StartedAt` (`ReviewHostOptions.Now` when tracked) and `RunId` (the run folder's name).
`TrackSession(chatId, runDirectory, document, startedAt)` sets them for a review; `TrackCheck`
records none of them. The records live for the SOLIDWORKS session (the host), not for the backend
process: a settings save restarts the backend and keeps every record.

## 2. Page-to-host rows

| Row | Payload | Reply | Refusal |
|---|---|---|---|
| `sessions.list` | `{}` | `sessions {items: [{chat_id, run_id, run_dir, path, configuration, started_at}]}` - reviews only, in the order tracked; `started_at` ISO 8601 with offset | none |
| `session.forget` | `{chat_id}` | `sessions {items}` after removing that review's record; `LatestSession` becomes null if it was that record | a chat id the host never recorded, or a check record, refused as `report.open` refuses one |
| `entity.show` | `{persist_ref, persist_ref_scope, component_id, chat_id?}` | `entity.shown` as today | a `chat_id` the host never recorded, refused as `report.open` refuses one |

With `chat_id`, `PaneActions` resolves the run folder through the same `PaneRunLookup` that
`report.open` uses and passes it on `EntityShowRequest.RunDirectory`; the resolver's
`document_id → path` and `component_id → full path` lookups read that folder's package. Without it
they read `LatestSession`'s folder, as today (the check tabs). The page never names a path. The
Review page always sends the shown chat's id.

`document.changed` is also posted when the active document's configuration changes (section 7).

## 3. The live snapshot

`GET /sessions/{chat_id}/snapshot` → `200` with `review_snapshot(run.session, run.context.ir,
run_id=<run folder name>, usage=run.usage_ledger, chat_state=chat.state, last_seq=run.sink.seq)`
(data-model section 8). It computes and writes nothing (as the attention route).
`404 UnknownChat` for a chat this backend does not hold.

## 4. The run folder

`GET /reviews/{run_id}` → `200` with `review_snapshot(load_session(...), load_package(...).package,
run_id=run_id, read_only_reason=<words.read_only>)`. `run_id` is a folder name under the run root,
resolved by `resolve_run_dir` as `check_id` is. `404 UnknownReview`, with no reason that would let
the route probe the workstation, when: the rule refuses the name; the folder does not exist; it holds
no `session.json`; it holds a `check.json` (a check folder); either file cannot be read. It writes
nothing: every file under the folder has the same bytes and modification time before and after.

## 5. The chips and choosing one

`<nav id="review-chips">` under the header: one chip per `sessions` item in the host's order, reading
"{file name} [{configuration}] {HH:MM}" (the time from `started_at`, the page's local clock), the
shown one `aria-current="true"`. The page asks `sessions.list` after `init` and after each
`review.started`, and uses the reply of `session.forget`.

`showReview(chatId)`:

1. Refused while a turn runs or a start is in flight (as Clear review is), with nothing changed.
2. Keeps the current chat's drafts and pins in page memory; closes the stream; clears Results and
   Transcript; sets the chat, `run_dir`, the reviewed document (the item's `path` and
   `configuration`) and `readOnly = null`.
3. `GET /sessions/{chat_id}/snapshot`; on `404 UnknownChat`, `GET /reviews/{run_id}`; on
   `404 UnknownReview`, the chip reads "This review can no longer be restored." with a Remove button
   that sends `session.forget`, and the pane shows no review.
4. Renders the snapshot into Results: the findings' cards in order, the coverage fold from
   `coverage`, the not-loaded warning, the ranking and its summary through the same functions the
   end of a turn uses, the pins and drafts kept for that chat. No `POST` is made and no `review.start`
   is sent (SC-005).
5. `readOnly = read_only_reason`: the follow-up, every disposition control and the questions panel
   are disabled and one line under the status line says the reason; Open report and Open run folder
   stay enabled.
6. When `chat_state` is `running` (a page reload mid-turn), the turn state is set and the stream is
   opened with `last_event_id = last_seq`.
7. The landed U8 binding then judges the reviewed document against the active one.

## 6. Returning to a document

On `document.changed`, and after `init`: when no turn runs and no start is in flight, the shown
review (if any) is not of the new active document (`web/shared/document.js` `same`), and the host's
list holds a review of that document, the page shows the **last** such item in the host's order
through `showReview`. Otherwise the landed binding applies: the shown review hides behind the stale
line, with Stop still enabled while a turn runs. The stale line gains nothing when a chip exists,
because this rule would already have shown it.

## 7. The configuration change

`ActiveConfigurationWatch` follows the active document: on every `ActiveDocChangeNotify` it
unsubscribes the previous document and subscribes the new one's `ActiveConfigChangePostNotify`
(`DPartDocEvents_...` for a part, `DAssemblyDocEvents_...` for an assembly; nothing for a drawing).
The event calls the add-in's document fan-out, so the Review, Model check, Remodel and Standards hosts
each post `document.changed` with the new configuration. It never throws out of the COM sink.

## 8. The transcript of a restored review

Restored from `/snapshot`: Transcript is empty until chosen; then the page opens the stream from seq
0 with `replayUntil = last_seq`. Until an event with `seq >= replayUntil` has been handled: events
build Transcript only (a `finding` event appends its marker and never a second card; a `coverage`,
`usage` or `evidence` event updates Transcript's head and records only); `session.ended` neither
closes the stream nor reloads the ranking; Transcript scrolls to its end once, when the replay ends.
After that the stream behaves as live.

Restored from `/reviews/{run_id}`: Transcript reads "This review was restored from its run folder;
its transcript is in events.jsonl there." with an Open run folder button.
