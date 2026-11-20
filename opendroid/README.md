# Yume build of OpenDroid

This folder turns [OpenDroid](https://github.com/JMAN730/opendroid) (an open-source Android agent, Apache-2.0) into a build where Yume Kisaragi is the one who talks.

Stock OpenDroid has no place to put a character: its chat reply is hard-coded as "a friendly and helpful Android AI assistant". So this is a patch to the app's source, not a settings file. The patch is small in what it touches and strict about where she is allowed to appear.

## What is in here

| Path | What it is |
|---|---|
| `persona/card.md` | Her character card: the 16 skill files condensed into one text for the chat prompt. `{{owner}}` is replaced by the profile name you give the app. |
| `persona/seed_notes.txt` | The notes her notebook starts with, one per line as `kind \| key \| note`, in her own first person. Facts about you are not in this file: see "Your information". |
| `patch/` | The source patch against OpenDroid commit `9b471bc` (v1.0.9). |
| `build.sh` | Fetches that commit, applies the patch, copies the card in, builds the APK. |

## Setting it up on the phone

1. Install the APK. It installs as a separate app named **Yume**, next to stock OpenDroid if that is installed.
2. Go through onboarding. The name you enter is what `{{owner}}` becomes in her card, so it is the name she knows you by.
3. Settings → provider **Custom OpenAI Compatible**. A fresh install of this build already has it chosen, with the address and the model filled in:
   - Base URL: `https://api.venice.ai/api/v1`
   - API key: a Venice API key with credit on it (the one thing you have to enter)
   - Model: `e2ee-deepseek-v4-1-flash-1017-abliterated`
4. In the **Hosted model options** card that appears under it:
   - Response timeout: `120` (this build starts there, because this model thinks before it answers)
   - Extra request options:
     `{"reasoning_effort":"none","venice_parameters":{"include_venice_system_prompt":false,"disable_thinking":true,"strip_thinking_response":true}}`
5. Leave Settings → Persona → "Her model can see screenshots" off. A model whose id starts with `e2ee-` is spoken to as text only: a picture cannot go into the encrypted exchange, so none is sent.
6. Leave Settings → Privacy → "Where a model may run" on **That, or end to end encrypted**, where this build starts. A plain hosted model is then refused on the phone before anything is sent to it.

The extra request options ask the model to switch its hidden reasoning off, which otherwise eats the reply's time and length, and they keep Venice from adding its own system prompt in front of hers, about 1,700 tokens of a second voice telling the model how to behave. The app leaves Venice's prompt out by itself as well. Whether Venice honours the reasoning switch for this encrypted model has not been checked: if it answers with an error, take `"reasoning_effort":"none",` out and keep the rest.

### If her replies are slow, cut off or sound like a polite assistant

Keep the main model for planning and give her replies to a second encrypted model on the same key. In Settings → Persona:

- Model for her replies: `e2ee-gemma-4-26b-a4b-uncensored-p` (no hidden reasoning, still end to end encrypted)
- Extra request options for her replies: `{"venice_parameters":{"include_venice_system_prompt":false}}`, so the options meant for the thinking model are not sent to this one

To go back, clear both fields. A plain hosted model (an id without `e2ee-`) is not an option for her: its host can read everything it is sent, and this build refuses it.

### What has and has not been checked

The model ids, prices, context sizes, image support and option names above were read from Venice's published model catalogue and API documentation on 16 November 2026. Nobody has run these models against this app yet. The first things to confirm on your phone are that a command such as "flashlight on" produces a plan, that a chat reply comes back within a few seconds, and that she does not refuse or lecture.

## Your information

Everything she knows about you is stored on the phone and nowhere else: the chat, her notebook, your profile name. The app has no analytics and no account, and it contacts nothing but the model you configure and the services behind a command you give (weather, a search).

What a model has to be sent is a separate matter, and it cannot be zero. For her to answer, the model writing the reply needs the conversation, her card and her notes. This build allows two kinds of model:

1. **An end-to-end encrypted model** (the setup above, and where this build starts): a Venice model whose id starts with `e2ee-`, such as `e2ee-deepseek-v4-1-flash-1017-abliterated` or `e2ee-gemma-4-26b-a4b-uncensored-p`. The app encrypts the whole prompt on the phone to a key that Venice presents as the key of a sealed hardware enclave running the model, and decrypts the reply with a key made for that one exchange. Venice's servers pass along ciphertext they cannot read. Before it sends, the phone checks that the enclave's proof is fresh, names this model, carries this key and does not come from an enclave in debug mode. It does not check the hardware maker's signature on that proof, so that the key belongs to a real enclave rests on Venice's word. Your commands and plans travel the same way, since the main model is one of these.
2. **A model on your own hardware.** Ollama on your PC, or On-Device AI. Nothing leaves at all. Her card, notebook and settings carry over unchanged.

A **plain hosted model** (any id without `e2ee-`) can read what it is sent. With Settings → Privacy → "Where a model may run" on "That, or end to end encrypted", as this build starts, it is refused on the phone before anything is built or sent.

**Private mode** (Settings → Privacy, "On a plain hosted model, keep my details on this phone", on by default) is for a plain hosted model, if you ever allow one: your date of birth, your location, the text of your notifications and anything learned from them are then never put into a prompt, hers or the planner's. A model on an encrypted route or on your own hardware is sent them, because nobody else can read them there.

**This repository.** What she starts out knowing about you is kept in a second notes file, `persona/seed_notes.private.txt`. It is listed in `.gitignore` and is never committed, and it is not put into the APK either, because an APK can be copied and unpacked: you hand those notes to her on the phone (Settings → Persona → Character card → "Give her notes"). Only a build made with `YUME_BAKE_PRIVATE_NOTES=1` puts them into her starting notebook. Her notebook on the phone is written on first start and updates of the app keep it; a starting note she never rewrote gets the new wording of that note.

Two things that send data elsewhere if you turn them on: an ElevenLabs key (every spoken line goes to ElevenLabs; leave it empty to use the phone's own voice) and OpenDroid's social features (other people's messages go to the model). OpenDroid's auto-reply is off in this build: it wrote to people in your name in nobody's voice, so it no longer has a writer, its switches were turned off on update, and Settings shows a notice where its card was. An email is never answered for you, since an answer there could only open a draft in your name.

The encrypted exchange was written from Venice's published protocol and its encryption is tested in both directions against Venice's reference code. It has not been run against Venice's live service yet. If it fails it fails closed: she does not answer, and nothing is sent unencrypted.

## Where she talks, and where she never does

She writes:

- every chat reply (anything that is talk and not a device command);
- lines of her own in her own time, when she feels like writing to you (Settings → Persona → Her own time, on in this build).

A few short spoken lines are fixed, in her manner, and no model writes them: the word before a shortcut runs ("flashlight. ok"), that a plan was dropped, broke off or did not go through, which contact is meant, the words around the approval prompt, and the answer to the wake phrase ("mm?"). They cost no model call and say only that much; Settings → Persona says so under her switch. How a plan ended is never one of them: that is told from what its steps did.

She can also act. A reply of hers, or a moment of her own, may end with a command of her own (the app hides that line and runs it). It goes through the same planner as your commands, and there is no list of what she may ask for: whatever the planner can do for you, it can do for her (`PersonaActions.kt`, lines 1-21). Who is asked first is decided in one place: your own approval setting always counts, and where it would stop the plan her rein (Settings → Persona) may still let it run. Her rein never runs a command whose words may be someone else's.

### Words that leave the phone are yours or hers

While she is on, no tool writes words that leave the phone. This covers what a plan would send to a person, post, or type into another app: a message, an email, a post, an invitation, a payment note, the words in a share link.

**Before a plan runs**, each such text is checked against where it may come from: your message for your command, her command for hers. Words that are yours or hers go as they are.

**Words the planner made up** are not sent. She is asked to write them herself, as herself, told who they go to, from whose account, and what was asked. She is never shown the planner's draft. If you asked her to write it for you she may write it the way you would send it. Otherwise it is from her, and on your accounts she never signs with your name or writes as you unless you asked. If she says no, or her model cannot be reached, that step is left out and the chat says so. The same check runs again whenever re-evaluation rewrites a step.

**Senders that only send are never answered:** no-reply and notification addresses, mailer daemons, SMS short codes and sender IDs, bot handles. A step addressed only to one is left out, and one that also reaches people goes without that address. An emergency line (911, 112, 999 and the like) is never taken for a short code.

**Macros:**
- A macro stores only your words or hers.
- Its card lists the words its steps will send. While she is on, a plan that runs a macro whose steps send words is always shown to you first, whatever your approval setting.
- A switched-off macro does not run.

**Off in this build:**
- **Social:** while she is on, the stock social writers (post composer, campaign generator, comment-reply drafts) are off. Posts and replies are written by you or by her, and publishing is still your tap.
- **MCP server:** off in this build, and the privileged shell behind it with it.
- **Template words:** the "Created by OpenDroid" footer on invitations and the "Sent via OpenDroid" payment note are gone.

The rules and what is left open are in `WHOLE_APP_PLAN.md`.

She never writes:

- the plan for a device action. The planner prompt is byte-for-byte the stock one.
- auto-replies. The stock auto-reply is gone from this build, not left as a stock feature: nothing answers a message for you while you are away. The old prompts for it, and for plans and social text, are untouched and never carry her card or her notebook.
- the spoken approval prompt. Its step count and step lines are the app's own text, word for word; while she is on, only the few fixed words around them are in her manner, and no model writes those. With her off it is the stock prompt ("I've planned 2 steps ... say approve to run, or cancel").
- the results of actions ("Alarm set for 7:30 AM"). Those are what the phone actually did, so they are repeated word for word.

Unit tests in the patch check parts of this wall: that recall, saved notes and the planner's memory context never return a row of her notebook; that the stock prompt builders for plans, re-evaluation, auto-replies and social text carry no persona marker; and that nothing in her package refers to the classes that run actions. No test drives a whole plan end to end with her switched on: the app's main loop has no test harness upstream.

## What the phone did

The phone keeps one record of everything it did and everything done through it, whoever started it: you in the chat or through a shortcut, a routine of yours, Social Center, a command of hers in a reply or in her own time, or the app itself. (What the old auto-reply sent before this build was put into it once; see below.) Each entry says when, who started it and why, how it was let through (your setting, her rein, your yes or no), what each step did, to whom, from which app and with which words, and how it ended. A draft left open for you is recorded as left open, never as sent.

Her reply is told the newest entries of the last two days and older ones your message is about, a moment of her own the last day, and her notebook pass what was done since its last pass. So asked about something the phone did, she owns what was hers and says plainly what was not. Where her route holds your details back, an entry keeps only its kind: who it went to and what it said stay on the phone. The planner and the stock assistant never see the record.

It is one file in the app's own storage (`files/record/phone_log.sealed`), sealed with a key that stays in the phone's Keystore, at most 600 entries and none older than 30 days. It never holds a secret, what a step read off the screen or out of a notification, her thoughts or her replies. On the update that brought it, what the old auto-reply answered in the last 30 days and what earlier plans did were put into it once.

## How she develops

- **Notebook.** Every few chat replies she is asked, as herself, what she wants to keep, and writes up to three short notes in the first person: things about you, where the two of you stand, what is still going on, what she has decided she thinks, and corrections you gave her. Nobody chooses for her. The notes go into her chat prompt from then on, which is how she is the same person next time. They are hers: the app keeps them as rows of its own (keys starting `yume.`) that the Memory tab does not list and no other part of the app reads. In Settings → Persona → Her notebook (on the card screen, below the card) you can give her notes, copy her notebook to move it to another phone, or empty it.
- **Card editor.** Settings → Persona → Character card. Edit the text, save, and she runs on it from her next reply. "Restore built-in" goes back to the shipped card.

Nothing in the app filters, softens or rewrites what she says. The only changes made to a reply are mechanical: a leading name label, quotation marks around the whole line and a gesture in asterisks at the edge of a line are removed, and an emphasised word loses its asterisks and keeps the word.

## Her time on your screen

Settings → HER OWN LIFE → **Lend her your screen**, off until you switch it on. With it on, a moment of hers may borrow your unlocked screen for one of your social or video apps (TikTok, YouTube, Instagram, X and the like). She scrolls, opens posts and comments, searches and watches.

- **She chooses, the app moves.** Each step is her own model looking at the screen and choosing what to do next. The app moves the way a person of her nature would: curved swipes, uneven speed, pauses to read, now and then a small overshoot or a short scroll. Nothing is staged and nothing is perfect.
- **Look only.** She has no accounts of her own, so it is your app and your account. She never likes, follows, subscribes, comments, replies, posts, messages, shares, saves, buys or gifts. She never opens your inbox, notifications or profile, and she types only into a search box. Her searches and the posts she opens are made from your account, so they show in that app's history and can change what it recommends to you.
- **It is yours again the moment you touch it.** It also ends if you lock the phone or a call comes in, and the screen goes back to what you had. It never starts while the phone is locked or was in your hand a moment ago.
- **On the record.** Her time on your screen goes on "Her day" and on the phone's record.
- **What she knows.** She knows the major social and entertainment apps (her canon page `kisaragi-apps`): what each is, how it works, its words, and her take on it. She has no account on any of them.

## Her pictures: originals and masters

Every picture of her the app holds is marked as one of three kinds:
- **Original:** one you gave it, kept exactly as given.
- **Master:** a reference you approved as a base, also kept exactly.
- **Derived:** anything a model made.

Only originals and masters are ever sent as references when a picture of her is drawn or changed. A derived picture never is, so her look does not drift from pictures made off pictures.

**Make her reference sheets** (Settings → Persona; the row shows once "She can make pictures of herself" is on) makes front, back and side sheets from her masters, in a plain fitted base layer and in her outfit. Each sheet is age-checked before it is shown, and it becomes a master only when you approve it.

Renders of her 3D model go into the APK only when `her_refs/APPROVED` exists. It does not exist yet, so this build carries none.

## Voice

- Her phone voice reads English the way it was trained. Her current voice (`yume-20261118-f037defb1012`) learned English through katakana, so that is how it reads English, exactly as before. A bilingual voice, trained on her English and marked as such in its files, is read with the same English phonemes it was trained on. Those phonemes are held byte for byte to the training side by tests.
- The text sent to speech is cleaned first: emoji, markdown and links are dropped from every spoken line. Her own lines, and only hers, also get a respelling for the speech engine: `www` becomes a laugh, `~` is removed, stretched words are shortened, and her missing apostrophes are put back so `dont` and `im` are pronounced. What you see in chat is not changed, and a message from someone else that is read aloud is read as written.
- Wake phrases: "hey yume", "hey yumi", "ok yume" and a few more spellings, plus the stock "opendroid". If your phone's recogniser hears the name some other way, add that spelling in Settings → Persona. Wake phrases only run while the floating button is off (that is how stock OpenDroid works).
- Her own voice has its own speed: Settings → Persona, under "Her own voice". The pitch and speed sliders under ElevenLabs are for the phone's own voice, which says what the app itself says, and a line of hers only where her own voice is off or cannot say it. Beside them is a field for the ElevenLabs model id.

## Other changes that came with it

- Replies from hosted models have any inline `<think>` text removed before they are shown, spoken or parsed.
- The timeout for "Custom OpenAI Compatible" and "OpenRouter" is adjustable (this build starts at 120 s for its thinking model; stock is a fixed 15 s).
- An "Extra request options (JSON)" field for those two providers, for options such as switching a model's reasoning off.
- A model id you type by hand is no longer replaced by the first model in the provider's list. Settings shows a note when the id in use is not in that list.
- Her chat replies can come from a different model than the one that plans device actions: a second model on the same provider, or a different provider altogether.
- Words such as "ring", "text" and "call" no longer force a message onto the planner when they are only part of another word ("boring", "context", "basically").
- The app installs beside stock OpenDroid: its package id ends in `.yume` and it is named "Yume".

## Building it yourself

You need git, curl, JDK 21 and the Android SDK (platform 36, build-tools 36.0.0, NDK 27.2.12479018, CMake 3.22.1), with `ANDROID_HOME` set.

```
./build.sh
```

The APK lands in `out/yume.apk`, signed with your own key in `keys/` (made on the first build, never committed). Keep that folder: an APK signed with any other key cannot update the one installed. Android will ask you to uninstall first, and that removes her notebook and your settings. Her own voice comes from `own_voice/` (never committed). A build made without it speaks with the phone's voice.

## Licence

OpenDroid is licensed under Apache-2.0. The patch in `patch/` contains changes to OpenDroid's source and is offered under the same licence.
