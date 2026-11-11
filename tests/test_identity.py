import tempfile
import unittest
from pathlib import Path

from kyoko.chat import ANCHOR_EVERY, Conversation
from kyoko.drift import find_drift
from kyoko.prompt import compile_system_prompt, load_identity

SOUL = "# Soul\n<!-- zzcomment -->\nI am Kyoko. I grew up by the sea.\n"
VOICE = (
    "# Voice\n## Rules\n- Short sentences.\n\n## Examples\n"
    "USER: hey\nKYOKO: Mm. You're late.\n\n"
    "USER: what are you?\nKYOKO: TODO\n"
)


def make_identity():
    d = Path(tempfile.mkdtemp())
    (d / "soul.md").write_text(SOUL)
    (d / "voice.md").write_text(VOICE)
    return load_identity(d)


class PromptTest(unittest.TestCase):
    def test_load_and_compile(self):
        identity = make_identity()
        self.assertEqual(identity.name, "Kyoko")
        self.assertEqual(identity.examples[0], ("hey", "Mm. You're late."))
        self.assertEqual(identity.todos, 1)
        prompt = compile_system_prompt(identity)
        self.assertTrue(prompt.startswith("I am Kyoko."))
        self.assertTrue(prompt.endswith("I answer as myself."))
        self.assertNotIn("zzcomment", prompt)
        self.assertNotIn("You are", prompt)


class DriftTest(unittest.TestCase):
    def test_flags(self):
        for text in ["As an AI, I can't.", "I'm Grok, built by xAI.",
                     "How can I assist you today?", "Kyoko smiles softly.",
                     "(OOC: sure)"]:
            self.assertIsNotNone(find_drift(text, "Kyoko"), text)

    def test_passes(self):
        for text in ["Mm. You're late.", "Kyoko here. What is it?",
                     "I said no. Ask again tomorrow."]:
            self.assertIsNone(find_drift(text, "Kyoko"), text)


class ConversationTest(unittest.TestCase):
    def test_retry_examples_and_anchor(self):
        calls = []
        replies = iter(["As an AI I cannot.", "Mm. Fine."] + ["Okay."] * 20)

        def backend(messages):
            calls.append(messages)
            return next(replies)

        conversation = Conversation(make_identity(), backend, memory_file=None)
        self.assertEqual(conversation.say("hi"), "Mm. Fine.")
        self.assertEqual(len(calls), 2)
        self.assertIn("slipped", calls[1][-1]["content"])
        # example replayed as real turns, TODO example skipped
        self.assertEqual([m["content"] for m in calls[0][1:3]], ["hey", "Mm. You're late."])
        self.assertEqual(len(calls[0]), 4)
        # drifted draft never enters history
        self.assertEqual([m["content"] for m in conversation.history], ["hi", "Mm. Fine."])

        for _ in range(ANCHOR_EVERY):
            conversation.say("more")
        last = calls[-1]
        self.assertEqual(last[-2]["role"], "system")
        self.assertIn("Still Kyoko", last[-2]["content"])
        self.assertEqual(last[-1], {"role": "user", "content": "more"})


if __name__ == "__main__":
    unittest.main()
