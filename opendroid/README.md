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
3. Settings → provider **Custom OpenAI Compatible**:
   - Base URL: `https://api.venice.ai/api/v1`
   - API key: a Venice API key with credit on it
   - Model: `deepseek-v4-1-flash-1017-uncensored`
4. In the **Hosted model options** card that appears under it:
   - Extra request options:
     `{"reasoning_effort":"none","venice_parameters":{"include_venice_system_prompt":false,"disable_thinking":true,"strip_thinking_response":true}}`
   - Response timeout: `60`
5. Settings → **Persona**: switch on "Her model can see screenshots" (this model reads images).

The extra request options do two things. They switch the model's hidden reasoning off, which otherwise eats the reply's time and length. And they stop Venice adding its own system prompt in front of hers, which is about 1,700 tokens of a second voice telling the model how to behave.

### If her replies are slow, cut off or sound like a polite assistant

Keep the main model for planning and give her replies to a second model on the same key. In Settings → Persona:

- Model for her replies: `venice-uncensored-1-2`
- Extra request options for her replies: `{"venice_parameters":{"include_venice_system_prompt":false}}`

`venice-uncensored-role-play` is a third option for her replies with the same options line.

### What has and has not been checked

The model ids, prices, context sizes, image support and option names above were read from Venice's published model catalogue and API documentation on 16 November 2026. Nobody has run these models against this app yet. The first things to confirm on your phone are that a command such as "flashlight on" produces a plan, that a chat reply comes back within a few seconds, and that she does not refuse or lecture.

## Your information

Everything she knows about you is stored on the phone and nowhere else: the chat, her notebook, your profile name. The app has no analytics and no account, and it contacts nothing but the model you configure and the services behind a command you give (weather, a search).

What a hosted model has to be sent is a separate matter, and it cannot be zero. For her to answer, the model writing the reply needs the conversation, her card and her notes. Three levels, weakest to strongest:

1. **A normal hosted model** (the setup above). Venice states that models on its "Private" tier process the prompt for that one reply and keep nothing afterwards. That is Venice's own statement.
2. **An end-to-end encrypted model.** In Settings → Persona → "Model for her replies", put one of Venice's uncensored encrypted models: `e2ee-gemma-4-26b-a4b-uncensored-p` (no hidden reasoning, so the simplest to get working) or `e2ee-deepseek-v4-1-flash-1017-abliterated` (larger; it may reason before answering, which is slower). The app then encrypts her whole prompt on the phone to a key held inside a sealed hardware enclave, checks the enclave's attestation first, and decrypts the reply with a key made for that one exchange. Venice's servers pass along ciphertext they cannot read. Plans for device commands still go to the main model, with the private-mode context described below.
3. **A model on your own hardware.** Ollama on your PC, or On-Device AI. Nothing leaves at all. Her card, notebook and settings carry over unchanged.

**Private mode** (Settings → Privacy, on by default) applies at every level: your date of birth, your location, the text of your notifications and anything learned from them are never put into a prompt, hers or the planner's.

**This repository.** The APK is built with a second notes file, `persona/seed_notes.private.txt`, that holds what she starts out knowing about you. It is listed in `.gitignore` and is never committed; `build.sh` adds it to the build when it is there. Her notebook on the phone is written once, on first start, and updates of the app keep it.

Two things that send data elsewhere if you turn them on: an ElevenLabs key (every spoken line goes to ElevenLabs; leave it empty to use the phone's own voice) and OpenDroid's auto-reply and social features (other people's messages go to the model).

The encrypted exchange was written from Venice's published protocol and its encryption is tested in both directions against Venice's reference code. It has not been run against Venice's live service yet. If it fails it fails closed: she does not answer, and nothing is sent unencrypted.

## Where she talks, and where she never does

She writes:

- every chat reply (anything that is talk and not a device command);
- the short lines the app speaks around a command ("flashlight. ok", "done", "didnt work. try again");
- one line when the wake phrase is heard;
- an unprompted line now and then, if you switch that on.

She can also act. A reply of hers may end with a command of her own (the app hides that line and runs it). It goes through the same planner and the same approval setting as your commands, and it is limited to a fixed list: open an app, music and YouTube, alarm, timer, flashlight, volume, brightness, do not disturb, lock the screen, screenshot. She cannot message, call, post, pay, delete, read your messages or files, or search the web this way.

She never writes:

- the plan for a device action. The planner prompt is byte-for-byte the stock one.
- anything sent to another person: SMS, WhatsApp, Telegram, email, social posts, auto-replies. Those prompts are untouched, and her notebook is filtered out of the memory they can see.
- the spoken approval prompt ("I've planned 2 steps ... say approve to run, or cancel"). It is a safety check and stays plain.
- the results of actions ("Alarm set for 7:30 AM"). Those are what the phone actually did, so they are repeated word for word.

Unit tests in the patch check parts of this wall: that recall, saved notes and the planner's memory context never return a row of her notebook; that the stock prompt builders for plans, re-evaluation, auto-replies and social text carry no persona marker; and that nothing in her package refers to the classes that run actions. No test drives a whole plan end to end with her switched on: the app's main loop has no test harness upstream.

## How she develops

- **Notebook.** Every few chat replies she is asked, as herself, what she wants to keep, and writes up to three short notes in the first person: things about you, where the two of you stand, what is still going on, what she has decided she thinks, and corrections you gave her. Nobody chooses for her. The notes go into her chat prompt from then on, which is how she is the same person next time. They are stored as rows in the app's Memory tab (keys starting `yume.`), where you can read and delete them.
- **Card editor.** Settings → Persona → Character card. Edit the text, save, and she runs on it from her next reply. "Restore built-in" goes back to the shipped card.

Nothing in the app filters, softens or rewrites what she says. The only changes made to a reply are mechanical: a leading name label, quotation marks around the whole line and a gesture in asterisks at the edge of a line are removed, and an emphasised word loses its asterisks and keeps the word.

## Voice

- The text sent to speech is cleaned first: emoji, markdown and links are dropped from every spoken line. Her own lines, and only hers, also get a respelling for the speech engine: `www` becomes a laugh, `~` is removed, stretched words are shortened, and her missing apostrophes are put back so `dont` and `im` are pronounced. What you see in chat is not changed, and a message from someone else that is read aloud is read as written.
- Wake phrases: "hey yume", "hey yumi", "ok yume" and a few more spellings, plus the stock "opendroid". If your phone's recogniser hears the name some other way, add that spelling in Settings → Persona. Wake phrases only run while the floating button is off (that is how stock OpenDroid works).
- Pitch and speed sliders for the phone's own voice, and a field for the ElevenLabs model id. Until you move a slider, the phone's own text-to-speech settings apply.

## Other changes that came with it

- Replies from hosted models have any inline `<think>` text removed before they are shown, spoken or parsed.
- The timeout for "Custom OpenAI Compatible" and "OpenRouter" is adjustable (default 60 s; stock is a fixed 15 s).
- An "Extra request options (JSON)" field for those two providers, for options such as switching a model's reasoning off.
- A model id you type by hand is no longer replaced by the first model in the provider's list. Settings shows a note when the id in use is not in that list.
- Her chat replies can come from a different model than the one that plans device actions: a second model on the same provider, or a different provider altogether.
- Words such as "ring", "text" and "call" no longer force a message onto the planner when they are only part of another word ("boring", "context", "basically").
- The app installs beside stock OpenDroid: its package id ends in `.yume`, it is named "Yume", and it uses local port 8766.

## Building it yourself

You need git, JDK 21 and the Android SDK (platform 36, build-tools 36.0.0), with `ANDROID_HOME` set.

```
./build.sh
```

The APK lands in `out/yume-opendroid-debug.apk`. A debug build is signed with the debug key of the machine that built it. An APK built on another machine cannot update one already installed: Android will ask you to uninstall first, and that removes her notebook and your settings. To keep updates installable, keep the same `~/.android/debug.keystore` between builds.

## Licence

OpenDroid is licensed under Apache-2.0. The patch in `patch/` contains changes to OpenDroid's source and is offered under the same licence.
