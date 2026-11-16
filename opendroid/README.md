# Yume build of OpenDroid

This folder turns [OpenDroid](https://github.com/JMAN730/opendroid) (an open-source Android agent, Apache-2.0) into a build where Yume Kisaragi is the one who talks.

Stock OpenDroid has no place to put a character: its chat reply is hard-coded as "a friendly and helpful Android AI assistant". So this is a patch to the app's source, not a settings file. The patch is small in what it touches and strict about where she is allowed to appear.

## What is in here

| Path | What it is |
|---|---|
| `persona/card.md` | Her character card: the 16 skill files condensed into one text for the chat prompt. `{{owner}}` is replaced by the profile name you give the app. |
| `persona/seed_notes.txt` | The notes her notebook starts with, one per line as `kind \| key \| note`. |
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

## Where she talks, and where she never does

She writes:

- every chat reply (anything that is talk and not a device command);
- the short lines the app speaks around a command ("flashlight. ok", "done", "didnt work. try again");
- one line when the wake phrase is heard;
- an unprompted line now and then, if you switch that on.

She never writes:

- the plan for a device action. The planner prompt is byte-for-byte the stock one.
- anything sent to another person: SMS, WhatsApp, Telegram, email, social posts, auto-replies. Those prompts are untouched, and her notebook is filtered out of the memory they can see.
- the spoken approval prompt ("I've planned 2 steps ... say approve to run, or cancel"). It is a safety check and stays plain.
- the results of actions ("Alarm set for 7:30 AM"). Those are what the phone actually did, so they are repeated word for word.

Unit tests in the patch check this wall: they fail if persona text is reachable from any plan, re-evaluation, auto-reply or social prompt.

## How she develops

- **Notebook.** Every few chat replies the app re-reads the recent conversation and keeps up to three short notes: facts about you, where the two of you stand, ongoing threads, opinions she has settled on, and corrections you gave her. The notes go into her chat prompt from then on. They are ordinary rows in the app's Memory tab (keys starting `yume.`), so you can read and delete them.
- **Card editor.** Settings → Persona → Character card. Edit the text, save, and she runs on it from her next reply. "Restore built-in" goes back to the shipped card.

## Voice

- The text sent to speech is cleaned first: emoji, markdown and links are dropped, `www` becomes a laugh, `~` is removed, stretched words are shortened, and her missing apostrophes are put back so `dont` and `im` are pronounced. What you see in chat is not changed.
- Wake phrases: "hey yume" and the spellings a speech recogniser tends to produce for it, plus the stock "opendroid". You can set your own list. Wake phrases only run while the floating button is off (that is how stock OpenDroid works).
- Pitch and speed sliders for the phone's own voice, and a field for the ElevenLabs model id.

## Other changes that came with it

- Replies from hosted models have any inline `<think>` text removed before they are shown, spoken or parsed.
- The timeout for "Custom OpenAI Compatible" and "OpenRouter" is adjustable (default 60 s; stock is a fixed 15 s).
- An "Extra request options (JSON)" field for those two providers, for options such as switching a model's reasoning off.
- A model id you type by hand is no longer replaced by the first model in the provider's list.
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
