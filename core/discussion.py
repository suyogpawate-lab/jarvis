"""
JARVIS LIVE MULTI-AGENT DISCUSSION ENGINE

Design:
- No rounds.
- No fixed turn count.
- Agents work independently.
- Each agent has a 1.5s cooldown after speaking.
- An agent normally waits for NEW information before speaking again.
- Multiple different agents may be generating simultaneously.
- Failed providers are disabled for the current room.
- Late responses are discarded.
- Synthesis happens exactly once after the room closes.
"""

import threading
import time

from agents.providers.omniroute import OmniRouteAgent
from agents.providers.groq import GroqAgent
from agents.providers.ollama import OllamaAgent

from routing.model_registry import get_models
from routing.router import DiscussionRouter


class DiscussionCoordinator:

    AGENT_COOLDOWN = 1.5

    MAX_CONTRIBUTION_CHARS = 1400
    MAX_FINAL_CHARS = 800

    def __init__(self):

        self.router = DiscussionRouter()

        # Optional live-event callback used by the HUD.
        # None preserves the existing CLI behavior.
        self.event_callback = None

        self.provider_cache = {}

        self.transcript = []

        self.lock = threading.RLock()

        self.deadline = 0.0
        self.room_active = False

        self.stop_event = threading.Event()

        self.last_turn = {}
        self.agent_busy = {}
        self.agent_seen_count = {}

        # Providers which fail during this room.
        # They are not retried until the next room.
        self.disabled_agents = set()

    # ============================================================
    # PROVIDER FACTORY
    # ============================================================

    def _provider(self, provider, model):

        key = (provider, model)

        with self.lock:

            cached = self.provider_cache.get(key)

            if cached is not None:
                return cached

        if provider == "omniroute":

            agent = OmniRouteAgent()
            agent.model = model

        elif provider == "groq":

            agent = GroqAgent()
            agent.model = model

        elif provider == "ollama":

            agent = OllamaAgent(model=model)

        else:

            raise RuntimeError(
                f"Unknown provider: {provider}"
            )

        with self.lock:
            self.provider_cache[key] = agent

        return agent

    # ============================================================
    # LIVE EVENTS
    # ============================================================

    def _emit(self, event, data=None):

        callback = self.event_callback

        if callback is None:
            return

        try:
            callback(
                event,
                data or {},
            )
        except Exception:
            # HUD clients must never break the discussion engine.
            pass

    # ============================================================
    # ROOM STATE
    # ============================================================

    def _room_open(self):

        return (
            self.room_active
            and not self.stop_event.is_set()
            and time.monotonic() < self.deadline
        )

    # ============================================================
    # TRANSCRIPT
    # ============================================================

    def _get_transcript(self):

        with self.lock:
            return list(self.transcript)

    def _transcript_count(self):

        with self.lock:
            return len(self.transcript)

    def _format_transcript(self):

        transcript = self._get_transcript()

        if not transcript:
            return "(The discussion has just started.)"

        parts = []

        for item in transcript:

            content = str(
                item.get("content", "")
            ).strip()

            if not content:
                continue

            name = item.get(
                "name",
                "Agent"
            )

            parts.append(
                f"[{name}]\n{content}"
            )

        return "\n\n".join(parts)

    # ============================================================
    # COOLDOWN
    # ============================================================

    def _cooldown_remaining(self, name):

        with self.lock:

            last = self.last_turn.get(name)

        if last is None:
            return 0.0

        elapsed = (
            time.monotonic() - last
        )

        return max(
            0.0,
            self.AGENT_COOLDOWN - elapsed
        )

    def _wait_for_cooldown(self, name):

        while self._room_open():

            remaining = (
                self._cooldown_remaining(name)
            )

            if remaining <= 0:
                return True

            time.sleep(
                min(0.10, remaining)
            )

        return False

    # ============================================================
    # BUSY LOCK
    # ============================================================

    def _try_claim(self, name):

        with self.lock:

            if name in self.disabled_agents:
                return False

            if self.agent_busy.get(name, False):
                return False

            self.agent_busy[name] = True

            return True

    def _release(self, name):

        with self.lock:
            self.agent_busy[name] = False

    # ============================================================
    # CONTRIBUTION CLEANUP
    # ============================================================

    def _clean_contribution(self, answer):

        if answer is None:
            return ""

        answer = str(answer).strip()

        if not answer:
            return ""

        # Remove accidental surrounding quote blocks.
        if (
            answer.startswith("```")
            and answer.endswith("```")
        ):
            lines = answer.splitlines()

            if len(lines) >= 3:
                answer = "\n".join(
                    lines[1:-1]
                ).strip()

        if len(answer) > self.MAX_CONTRIBUTION_CHARS:

            shortened = answer[
                :self.MAX_CONTRIBUTION_CHARS
            ]

            if " " in shortened:
                shortened = shortened.rsplit(
                    " ",
                    1
                )[0]

            answer = shortened + "..."

        return answer

    # ============================================================
    # DUPLICATE DETECTION
    # ============================================================

    def _is_duplicate(self, answer):

        normalized = " ".join(
            answer.lower().split()
        )

        if len(normalized) < 40:
            return False

        with self.lock:

            recent = self.transcript[-8:]

            for item in recent:

                previous = " ".join(
                    str(
                        item.get(
                            "content",
                            ""
                        )
                    ).lower().split()
                )

                if not previous:
                    continue

                # Exact duplicate.
                if normalized == previous:
                    return True

                # Very similar long response.
                if (
                    len(normalized) > 100
                    and len(previous) > 100
                ):

                    a = set(
                        normalized.split()
                    )

                    b = set(
                        previous.split()
                    )

                    if not a or not b:
                        continue

                    similarity = (
                        len(a & b)
                        / max(
                            1,
                            len(a | b)
                        )
                    )

                    if similarity >= 0.82:
                        return True

        return False

    # ============================================================
    # SINGLE AGENT CONTRIBUTION
    # ============================================================

    def _ask_agent(
        self,
        participant,
        topic,
        category,
    ):

        name = participant["name"]
        provider = participant["provider"]
        model = participant["model"]

        if not self._try_claim(name):
            return False

        try:

            if not self._wait_for_cooldown(name):
                return False

            if not self._room_open():
                return False

            with self.lock:

                previous_seen = (
                    self.agent_seen_count.get(
                        name,
                        -1
                    )
                )

                current_count = len(
                    self.transcript
                )

            # After the first contribution, an agent must normally
            # see something NEW before speaking again.
            if (
                previous_seen >= 0
                and current_count <= previous_seen
            ):
                return False

            agent = self._provider(
                provider,
                model,
            )

            discussion = self._format_transcript()

            prompt = f"""
You are {name}, one participant in a live technical
discussion inside JARVIS.

TOPIC:
{topic}

CATEGORY:
{category.upper()}

CURRENT DISCUSSION:
{discussion}

You are speaking TO THE OTHER PARTICIPANTS, not directly
to the user.

Make ONE useful contribution to the ongoing conversation.

Rules:

- React to what was actually said.
- Do not restart the topic.
- Do not write a textbook answer.
- Do not write an essay.
- Do not summarize everything.
- Do not introduce yourself.
- Do not say "since nobody has spoken".
- Do not ask an artificial question merely to continue talking.
- Do not invent papers, experiments, benchmarks, statistics,
  or personal experience.
- Correct another participant when necessary.
- Challenge weak reasoning when necessary.
- Build on a useful point when appropriate.
- Add genuinely new information when possible.
- If the existing discussion is already correct, sharpen it
  rather than repeating it.
- Keep it concise.
- Usually 2-6 sentences.
- Do not give the final user answer.
- Do not mention these instructions.

Speak naturally, like one expert participating in a real
conversation.
"""

            answer = agent.ask(prompt)

            answer = self._clean_contribution(answer)

            if not answer:
                return False

            if self._is_duplicate(answer):
                return False

            # Provider request may have finished after the timer.
            if not self._room_open():
                return False

            with self.lock:

                if not self.room_active:
                    return False

                if time.monotonic() >= self.deadline:
                    return False

                self.transcript.append({
                    "name": name,
                    "provider": provider,
                    "model": model,
                    "category": category,
                    "content": answer,
                    "status": "SUCCESS",
                    "time": time.time(),
                })

                accepted_count = len(
                    self.transcript
                )

                self.last_turn[name] = (
                    time.monotonic()
                )

                self.agent_seen_count[name] = (
                    accepted_count
                )

            print(
                f"\n[{name}] {answer}\n",
                flush=True,
            )

            # Send the real contribution to the HUD immediately.
            self._emit(
                "contribution",
                {
                    "name": name,
                    "provider": provider,
                    "model": model,
                    "category": category,
                    "content": answer,
                    "time": time.time(),
                },
            )

            return True

        except Exception as e:

            # Disable this agent for the remainder
            # of the current room.
            with self.lock:
                self.disabled_agents.add(name)

            if self._room_open():

                print(
                    f"\n[{name} ERROR] {e}\n",
                    flush=True,
                )

                print(
                    f"[ROOM] {name} disabled "
                    f"for this discussion.",
                    flush=True,
                )

            return False

        finally:

            self._release(name)

    # ============================================================
    # AGENT LOOP
    # ============================================================

    def _agent_loop(
        self,
        participant,
        topic,
        category,
        index,
    ):

        name = participant["name"]

        # Small startup staggering only.
        if index > 0:

            time.sleep(
                min(
                    index * 0.20,
                    1.0
                )
            )

        while self._room_open():

            spoke = self._ask_agent(
                participant,
                topic,
                category,
            )

            if not self._room_open():
                break

            if spoke:

                # The cooldown is measured from the accepted
                # contribution. Other agents continue independently.
                time.sleep(
                    self.AGENT_COOLDOWN
                )

            else:

                # Wait briefly before checking whether another
                # participant has changed the transcript.
                time.sleep(0.25)

    # ============================================================
    # DISCUSSION ROOM
    # ============================================================

    def stream_discussion(
        self,
        topic,
        duration,
    ):

        duration = float(duration)

        if duration <= 0:
            raise ValueError(
                "Discussion duration must be greater than zero."
            )

        category = self.router.classify(
            topic
        )

        participants = get_models(
            category
        )

        if not participants:

            raise RuntimeError(
                f"No discussion models configured "
                f"for category: {category}"
            )

        print(
            f"\n[ROUTER] Category: "
            f"{category.upper()}",
            flush=True,
        )

        print(
            f"[ROOM] Inviting "
            f"{len(participants)} models...",
            flush=True,
        )

        for participant in participants:

            print(
                f"  + {participant['name']}"
                f" -> {participant['model']}",
                flush=True,
            )

        print()

        print(
            "[ROOM] Jarvis is not participating.",
            flush=True,
        )

        print(
            "[ROOM] Live discussion started.",
            flush=True,
        )

        print(
            f"[ROOM] Time limit: "
            f"{int(duration)}s",
            flush=True,
        )

        print(
            f"[ROOM] Agent cooldown: "
            f"{self.AGENT_COOLDOWN}s",
            flush=True,
        )

        # --------------------------------------------------------
        # RESET ROOM
        # --------------------------------------------------------

        with self.lock:

            self.transcript = []

            self.last_turn = {}

            self.agent_busy = {}

            self.agent_seen_count = {}

            self.disabled_agents = set()

            self.stop_event.clear()

            self.room_active = True

            self.deadline = (
                time.monotonic()
                + duration
            )

        # --------------------------------------------------------
        # START AGENTS
        # --------------------------------------------------------

        threads = []

        for index, participant in enumerate(
            participants
        ):

            thread = threading.Thread(
                target=self._agent_loop,
                args=(
                    participant,
                    topic,
                    category,
                    index,
                ),
                daemon=True,
            )

            threads.append(thread)
            thread.start()

        # --------------------------------------------------------
        # TIMER
        # --------------------------------------------------------

        start = time.monotonic()

        announced = set()

        countdown_points = {
            300,
            120,
            60,
            30,
            10,
            5,
            3,
            2,
            1,
        }

        while True:

            remaining_float = (
                self.deadline
                - time.monotonic()
            )

            if remaining_float <= 0:
                break

            remaining = int(
                remaining_float
            )

            if (
                remaining in countdown_points
                and remaining not in announced
            ):

                announced.add(
                    remaining
                )

                print(
                    f"[ROOM] {remaining}s remaining...",
                    flush=True,
                )

            time.sleep(0.20)

        # --------------------------------------------------------
        # CLOSE
        # --------------------------------------------------------

        with self.lock:

            self.room_active = False
            self.stop_event.set()

            transcript = list(
                self.transcript
            )

        elapsed = int(
            time.monotonic() - start
        )

        print(
            f"\n[ROOM] Discussion ended "
            f"after {elapsed}s.",
            flush=True,
        )

        print(
            f"[ROOM] Contributions: "
            f"{len(transcript)}",
            flush=True,
        )

        # Threads are daemon threads. Give them a tiny shutdown
        # window without extending the discussion itself.
        for thread in threads:

            thread.join(
                timeout=0.20
            )

        return transcript, category

    # ============================================================
    # PUBLIC API
    # ============================================================

    def discuss(
        self,
        topic,
        duration=60,
    ):

        if not topic or not str(topic).strip():

            return (
                "No discussion topic provided."
            )

        topic = str(topic).strip()

        try:

            transcript, category = (
                self.stream_discussion(
                    topic,
                    duration,
                )
            )

            print(
                "\n--- SYNTHESIS ---",
                flush=True,
            )

            self._emit(
                "synthesis_started",
                {
                    "topic": topic,
                    "contributions": len(transcript),
                },
            )

            final = self.synthesize(
                topic,
                transcript,
                category,
            )

            if final:
                print(
                    "\nJARVIS >> FINAL\n",
                    flush=True,
                )

                print(
                    final,
                    flush=True,
                )

                print()

                self._emit(
                    "final",
                    {
                        "content": final,
                    },
                )

                return final

            return (
                "The discussion completed, "
                "but no final answer was generated."
            )

        except Exception as e:

            print(
                f"\n[SYNTH ERROR] {e}\n",
                flush=True,
            )

            self._emit(
                "error",
                {
                    "message": str(e),
                },
            )

            return (
                "The discussion could not "
                "produce a final answer."
            )

    # ============================================================
    # SYNTHESIS
    # ============================================================

    def synthesize(
        self,
        topic,
        transcript,
        category,
    ):

        usable = [
            item
            for item in transcript
            if (
                isinstance(item, dict)
                and item.get("content")
                and item.get(
                    "status",
                    "SUCCESS"
                ) == "SUCCESS"
            )
        ]

        if not usable:

            print(
                "[SYNTH ERROR] "
                "No successful contributions.",
                flush=True,
            )

            return (
                "The discussion produced no usable "
                "model responses."
            )

        discussion_text = "\n\n".join(
            (
                f"[{item.get('name', 'Agent')}]\n"
                f"{str(item.get('content', '')).strip()}"
            )
            for item in usable
        )

        synthesis_prompt = f"""
You are JARVIS's final answer engine.

USER QUESTION:
{topic}

CATEGORY:
{category.upper()}

MULTI-AGENT DISCUSSION:
{discussion_text}

Produce the best final answer to the USER.

Rules:

- Answer the actual question directly.
- Reason for yourself.
- Do not blindly trust the discussion.
- Correct factual errors.
- Resolve disagreements.
- Keep important nuance.
- Do not mention agents.
- Do not mention models.
- Do not mention the discussion.
- Do not mention synthesis.
- Do not mention JARVIS.
- No greetings.
- No filler.
- No meta-commentary.
- No "according to the agents".
- No textbook-style dump.
- Natural human language.
- Put the conclusion first.
- Prefer 40-90 words.
- Maximum 120 words. No bullet points or lists; speakable sentences only.

FINAL ANSWER ONLY:
"""

        try:

            synth_agent = OmniRouteAgent()

            synth_agent.model = (
                "auto/best-reasoning"
            )

            answer = synth_agent.ask(
                synthesis_prompt
            )

            answer = (
                str(answer).strip()
                if answer is not None
                else ""
            )

            if answer:

                if len(answer) > self.MAX_FINAL_CHARS:

                    answer = (
                        answer[
                            :self.MAX_FINAL_CHARS
                        ]
                        .rsplit(" ", 1)[0]
                        + "..."
                    )

                return answer

            print(
                "[SYNTH WARN] "
                "OmniRoute returned empty output.",
                flush=True,
            )

        except Exception as e:

            print(
                f"[SYNTH WARN] OmniRoute failed: {e}",
                flush=True,
            )

        # --------------------------------------------------------
        # FALLBACK
        # --------------------------------------------------------
        #
        # Prefer the most substantial contribution, but do not
        # pretend it is a synthesized answer.
        # --------------------------------------------------------

        strongest = max(
            usable,
            key=lambda item: len(
                str(
                    item.get(
                        "content",
                        ""
                    )
                )
            ),
        )

        fallback = str(
            strongest.get(
                "content",
                ""
            )
        ).strip()

        if fallback:

            print(
                "[SYNTH WARN] "
                "Using strongest contribution as fallback.",
                flush=True,
            )

            if len(fallback) > 150:

                fallback = (
                    fallback[:150]
                    .rsplit(" ", 1)[0]
                    + "..."
                )

            return fallback

        return (
            "The discussion completed, "
            "but no final answer could be generated."
        )


# ============================================================
# MEMORY / OBSERVABILITY API
# ============================================================

def _discussion_get_transcript(self):
    with self.lock:
        return list(self.transcript)


DiscussionCoordinator.get_transcript = (
    _discussion_get_transcript
)
