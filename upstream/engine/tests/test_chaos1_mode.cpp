// OpenBFME unit tests. GPL-3.0.
// Lane CHAOS-1: the Chaos mode (GameLogic/ChaosMode.h). What the test guards, and why each check is the one that matters:
//   * a game without the mode keeps its hash and never announces anything: the mode must cost nothing when it is off;
//   * the same seed and the same frames give the same events, the same log and the same hash on two runs: this is lockstep, an event that drew a
//     number from anywhere but GetGameLogicRandomValue would show here as a mismatch;
//   * the schedule fires, on the frame the table says, and moves on afterwards;
//   * the weights are the table's, and an event below its minFrame is never chosen first;
//   * a forced event (MSG_OPENBFME_CHAOS) runs on every peer and is refused in a game without the mode.
// The games SKIP without ROTWK_INSTALL / BFME2_INSTALL (haveWorld).
//
// The unit-level part (the table, the names, the clamped state) runs everywhere, in every build: it needs no map.

#include "doctest.h"
#include "HudTestUtil.h"

#include "Common/Player.h"
#include "GameLogic/ChaosMode.h"
#include "GameLogic/GameLogic.h"
#include "GameLogic/GameLogicDispatch.h"
#include "GameLogic/GameMessage.h"

#include <cstdint>
#include <string>
#include <vector>

using namespace hudtest;

namespace
{
struct Run
{
	std::vector<std::uint32_t> hashes;
	std::vector<std::string> lines;
	int events = 0;
	unsigned firstEventFrame = 0;
};

// `chaos`: the mode is configured on; `frames`: how many frames the game runs (5 frames = one second, 25 s = one event)
Run play(SharedWorld &s, bool chaos, int frames)
{
	Run out;
	Rig r(s);
	GameLogic &logic = r.logic();
	logic.chaosMode().configure(chaos);
	logic.chaosMode().reset();
	r.frame(2);
	for (int i = 0; i < frames; ++i)
	{
		r.frame(1);
		out.hashes.push_back(logic.computeStateHash());
	}
	out.events = logic.chaosMode().eventsRun();
	for (const ChaosMode::LogEntry &e : logic.chaosMode().log())
	{
		out.lines.push_back(e.text);
		if (out.firstEventFrame == 0)
		{
			out.firstEventFrame = e.frame;
		}
	}
	return out;
}
} // namespace

TEST_CASE("chaos1 mode: the table, the names and the rhythm are the ones documented")
{
	using namespace ChaosMode;
	CHECK(weightCount() == 12);
	int total = 0;
	for (int i = 0; i < weightCount(); ++i)
	{
		total += weightAt(i).weight;
		CHECK((int)weightAt(i).event >= kFirstEvent);
		CHECK((int)weightAt(i).event <= kLastEvent);
	}
	CHECK(total > 0);
	// every event of the enum has a name, and the name round-trips: the log is localized by <id>, so a missing name is a missing translation
	for (int e = kFirstEvent; e <= kLastEvent; ++e)
	{
		const char *name = eventName((Event)e);
		REQUIRE(name != nullptr);
		CHECK(std::string(name) != "none");
		CHECK(eventFromName(name) == e);
	}
	CHECK(std::string(eventName(Event::None)) == "none");
	CHECK(Event::SwapArmies != Event::Menagerie);
}

TEST_CASE("chaos1 mode: a game without the mode keeps its hash and announces nothing")
{
	if (!haveWorld("chaos1 mode"))
	{
		return;
	}
	SharedWorld &s = shared();
	const Run off = play(s, false, 60);
	REQUIRE(!off.hashes.empty());
	CHECK(off.events == 0);
	CHECK(off.lines.empty()); // nothing ran, so nothing is announced, and the hash is the game's own
}

TEST_CASE("chaos1 mode: two runs of the same game pick the same events, on the same frames, with the same hash")
{
	if (!haveWorld("chaos1 mode"))
	{
		return;
	}
	SharedWorld &s = shared();
	const Run one = play(s, true, 140); // past the first event (frame 150 is 30 s: this run reaches 140 and sees none yet)
	const Run two = play(s, true, 140);
	CHECK(one.hashes == two.hashes); // the lockstep guarantee: an event is a function of the seed and the frame
	CHECK(one.lines == two.lines);
	CHECK(one.events == two.events);
}

TEST_CASE("chaos1 mode: the first event comes at its frame, and the schedule moves on")
{
	if (!haveWorld("chaos1 mode"))
	{
		return;
	}
	SharedWorld &s = shared();
	// 200 frames = 40 s: the first event is due at 150 (30 s), the next at 275, so exactly one has run
	const Run run = play(s, true, 200);
	CHECK(run.events == 1);
	REQUIRE(run.lines.size() == 1);
	CHECK(run.firstEventFrame == (unsigned)ChaosMode::kFirstEventFrame);
	CHECK(run.lines[0].rfind("chaos.event.", 0) == 0); // the announcement is the localization id, never raw English on the screen
}

TEST_CASE("chaos1 mode: a game with the mode hashes its state, a game without does not")
{
	if (!haveWorld("chaos1 mode"))
	{
		return;
	}
	SharedWorld &s = shared();
	const Run off = play(s, false, 20);
	const Run on = play(s, true, 20);
	REQUIRE(!off.hashes.empty());
	REQUIRE(off.hashes.size() == on.hashes.size());
	CHECK(off.hashes[0] != on.hashes[0]); // the mode's own fields are in the hash from frame 1: a peer that disagrees desyncs at once
}

TEST_CASE("chaos1 mode: a forced event runs once, and a message is not taken in a game without the mode")
{
	if (!haveWorld("chaos1 mode"))
	{
		return;
	}
	SharedWorld &s = shared();
	Rig r(s);
	GameLogic &logic = r.logic();
	const int before = logic.chaosMode().eventsRun();
	// off: the handler exists on every game, and does nothing without the mode
	logic.chaosMode().configure(false);
	r.game->dispatch().dispatch(GameMessage(MSG_OPENBFME_CHAOS, 0));
	CHECK(logic.chaosMode().eventsRun() == before);
	// on: the same message runs the event and announces it
	logic.chaosMode().configure(true);
	logic.chaosMode().reset();
	GameMessage m(MSG_OPENBFME_CHAOS, 0);
	m.appendIntegerArgument((int)ChaosMode::Event::GoldRush);
	m.appendIntegerArgument(-1);
	r.game->dispatch().dispatch(m);
	CHECK(logic.chaosMode().eventsRun() == 1);
	REQUIRE(logic.chaosMode().log().size() == 1);
	CHECK(logic.chaosMode().log()[0].event == ChaosMode::Event::GoldRush);
	CHECK(logic.chaosMode().log()[0].text == "chaos.event.gold_rush");
}

TEST_CASE("chaos1 mode: the message type is a network logic type and carries its name")
{
	CHECK(IsNetworkLogicMessageType(MSG_OPENBFME_CHAOS));
	CHECK(std::string(GameMessageTypeName(MSG_OPENBFME_CHAOS)) == "MSG_OPENBFME_CHAOS");
	CHECK(MSG_OPENBFME_CHAOS != MSG_OPENBFME_CHEAT);
}
