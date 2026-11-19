# The whole app is her

What the owner asked for: no part of OpenDroid writes or acts behind her back. Every writer and every actor in the app either goes through her or is switched off. She never answers automated senders. On his accounts she does not sign as him unless he asked her to. She knows, and owns, what the phone did.

What set it off: an email draft to Tumblr, signed with his name, that she knew nothing about.

This plan builds on the save point (app tree at `328231b`, patch at repo commit `000bf09`). Paths are relative to `app/src/main/java/com/opendroid/ai/` (written `ai/`).

**Status:** being built. None of this is in `patch/yume-persona.patch` yet.

---

## 1. What the map found

Every place in the app that writes words that leave the phone, or acts on the phone, was traced. These are the ones that are not her.

| Writer or actor | Where the words come from | Today |
|---|---|---|
| Auto-reply (WhatsApp, Telegram, Discord, SMS, email) | A stock prompt on the main model: "auto-replying on behalf of <his name>", with a greeting, a sign-off and "never reveal you are an AI" (`core/llm/prompts/AutoReplyPrompts.kt`). The email channel opens a `Re: <sender>` draft. | Off by default, but a plan step (`AUTO_REPLY_TOGGLE`) can switch it on. No filter for no-reply, bots, OTP codes or newsletters. No row, no record, nothing to her. |
| Plan bodies for his commands | The stock planner writes the message, email and post text itself. Its context always carries "User Name: <his name>". | His approval card shows the words; she never sees them. |
| Plan bodies for her `>>` commands | The planner, used as a tool, is told to copy her words but still composes what her command left out. `SEND_EMAIL` requires a subject and body, so `>> email Tumblr about X` gets a planner-written email. | The chat row keeps only "Send email to <address>". She never sees the body. |
| Re-evaluation and re-plan | A third prompt on the main model may rewrite bodies while a plan runs. | Same as above. |
| Macros and routines | `RUN_MACRO` replays stored steps, words and all, under one approval of "Run macro". `CREATE_MACRO` stores planner-written steps whose words the card hides. | No record; `RUN_MACRO` ignores a disabled macro. |
| Social | Composer, campaign generator and comment-reply engine: stock prompts ("Social Media AI Manager for OpenDroid") on the main model. | Drafts only; he taps to publish. Not her. |
| MCP server | Any local client runs any action or a privileged shell. | Off by default, no way to see its token. |
| Fixed templates sent to people | "Sent via OpenDroid" on a UPI note; "Created by OpenDroid" on calendar invites. | Words in nobody's voice. |

The Tumblr draft fits two of these: the auto-reply email channel (if its switches were ever on) and a planner-written `SEND_EMAIL` body. Both are closed below.

## 2. The rules

1. **Words that leave the phone are his or hers, never a tool's.** Before a plan runs, every text a step would send to a person, post publicly or type into another app is checked against where it may come from: his message for his command, her command for hers. A text that is not his or her own words is not sent as the planner wrote it: she is asked to write it herself, as herself, knowing who it goes to, from whose account, and what he asked. Her words replace the planner's on the card and in the step. If she will not write it, or her model cannot be reached, that step does not run, and the plan says why. The same check runs again whenever re-evaluation rewrites a step.
   - Out of scope, on purpose: search words (web search, weather, news, translate) and the clipboard. They go to a search engine or stay on the phone. The record keeps them.
   - Words pasted from an earlier step's result (`$$sN`) are the phone's own output, not anyone's composition. They pass, and the card shows them as such.
2. **On his accounts she does not sign as him unless he asked.** Her words prompt says so. Whether he asked is hers to judge from his message.
3. **Never answer an automated sender.** One classifier (`core/agent/AutomatedSender.kt`) knows no-reply and notification addresses, mailer daemons, SMS short codes and sender IDs, and bot handles. A step addressed to one does not run.
4. **Auto-reply has no writer in this build.** The stock prompt is gone, its switches are turned off once on update, the plan step that switched it on refuses, and Settings shows a notice in place of its card. Nothing answers a message for him.
5. **Social writers are hers or off.** While she is on, the composer, the campaign generator and the comment-reply engine do not run: posts and replies are written by him or by her. `SOCIAL_CREATE_POST` carries its words in the step and goes through rule 1. Publishing stays his tap, and goes on the record.
6. **The MCP server is off in this build**, and so is the privileged shell behind it. The switch is turned off once on update and is no longer in Settings.
7. **Macros and routines.** `CREATE_MACRO`'s stored words go through rule 1 when it is created. `RUN_MACRO`'s card lists the words its steps will send, a disabled macro does not run, and every inner step goes on the record.
8. **No words in nobody's voice.** The UPI note and the calendar-invite footer are removed.

## 3. The record of what the phone did

One record of everything the phone did and everything done through it, whoever started it.

- **Who started it:** him in the chat, by voice, a shortcut or the app's screens; her in a reply or in her own time; a macro or a routine; the app itself.
- **Why:** his message, her command, or the macro's name, cut short.
- **How it was let through:** his setting, her rein, his yes, his no.
- **What each step did:** the action, to whom, from which app, the words it sent, and how it ended. A draft left open for him is recorded as left open, never as sent.

**What it never holds:** secrets, what a step read off the screen or out of a notification, her thoughts, or her replies.

**Where it lives:** one file in the app's own storage, `files/record/phone_log.sealed`. It is sealed with an AES-GCM key that stays in the phone's Keystore. It holds at most 600 entries, none older than 30 days. On the update that brings it, the plans already in the app's history are put into it once.

**What she is told:**
- Her reply gets the newest entries of the last two days, and older ones his message is about.
- A moment of her own gets the last day.
- Her notebook pass gets what was done since its last pass.
- Where her route holds his details back, an entry keeps only its kind and time: who it went to and what it said stay on the phone.

The planner and the stock assistant never see the record.

## 4. What is unchanged

- His approval setting and her rein decide what runs without asking, exactly as before.
- The planner prompt stays the stock one. It never carries her card, and her prompts never carry the planner's.
- With her switched off the app is stock OpenDroid, except for the switch-offs in rules 4, 6 and 8.
