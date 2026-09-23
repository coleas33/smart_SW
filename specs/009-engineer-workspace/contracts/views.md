# Contract: Results or Transcript

Normative for FR-017 to FR-019 and SC-006.

## 1. The switch

Under the header (and the chips, `sessions.md` section 5), two buttons, **Results** and
**Transcript**, `aria-pressed` on the chosen one. The chosen view is a class on `body`,
`view-results` (the default on every load) or `view-transcript`; the other view's container is not
displayed. Neither label carries a count.

## 2. What each view holds

| Outside both views | `#results` | `#transcript` |
|---|---|---|
| header and chips | `#results-state`: one line of page words (section 3) | `.transcript-head`: calls, rounds, the running tool, the usage line (008's `usageLine`), the stream state, the run folder path |
| the switch | `#summary` (`review-summary.md`) | prose blocks (the reviewer's and the engineer's), in order |
| the session buttons (Review, Stop, Clear review, Open report, Open run folder, View log) | `#questions` (`questions.md`) | tool cards with their call detail |
| the stale line (U8) | `#not-examined` | evidence cards (records) |
| the preparation panel | `#attention-panel` (Start here, "Show all") | system lines (review started, turn ended, session ended, unreadable frames) |
| the follow-up form | `#findings`: headline cards in arrival order, the modelling-practice group, the contacts fold | one-line finding markers ("{id} recorded: {title}") in their place |
| | `#coverage-panel` ("Not reached") | error lines naming the class and the message |
| | error cards (plain words, `plain-words.md` section 5) | |
| | `#answers`: pinned follow-up answers | |

Results shows no tool card, no tool argument and no token count; Transcript shows every prose block,
tool call and finding marker in the order the events arrived, with the counts.

"Collapse all" sits in Results over the findings. The old transcript fold (its toggle, the
`folded` class and its rules) is gone.

## 3. The status line

`#results-state` reads, from page state alone:

| State | Words |
|---|---|
| a turn is running and the stream is live | "The review is running." |
| a reconnect is pending | "Reconnecting to the review." |
| no turn running, open questions in the summary | "Waiting for your answers." |
| no turn running, a chat shown | "The review has finished." |
| no chat | nothing (the line is hidden) |

## 4. A follow-up answer

Sending a follow-up appends to `#answers` a pinned block holding the question and "Waiting for the
answer." When that turn's `text.done` arrives, the block's answer is the done text and the block is
scrolled into view within Results; the same text is also a prose block in Transcript. The view does
not change. Pins are kept per chat id in page memory and rendered again when that chat is shown
(`sessions.md` section 5). A turn that ends without `text.done` (stopped, failed) writes "No answer:
the turn ended ({reason})." into the block.

## 5. Streaming into two containers

A `finding` event renders its card into `#findings` (replacing an existing card of the same id in
place, as today) and appends a marker to `#transcript`. An `evidence.requested` event appends its
record card to `#transcript`; the question reaches Results through the summary. An `error` event
renders the plain card into Results and an error line into Transcript. Only Transcript scrolls to
its end on new content; Results never moves under the reader.

## 6. SC-006

Every finding of the big-assembly fixture is reachable from the top of Results in at most two
clicks: a headline card in `#findings` needs none (scrolling is not a click); a card inside the
modelling-practice group needs one; a Start-here or "Show all" row reaches its card in one or two.

## 7. Performance

With 1,000 findings and a 1,000-row ranking rendered from a snapshot, Results is rendered within 3 s
offscreen and its first card is in view. Paging by 100 behind "Show 100 more", in the supplied
order, is the fallback if not (research R2.25).
