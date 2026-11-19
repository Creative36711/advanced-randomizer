// OpenBFME. GPL-3.0.
//
// ChaosMode (lane CHAOS-1): the punk mode. NOT a randomizer of the start: the MATCH changes, every ~25 seconds, for everyone, announced to
// everyone. Chaos Mode in RotWK 2.02 picks two builders and a fortress once and then plays like a normal game; here the game itself is the
// event schedule.
//
// WHY THIS IS POSSIBLE HERE AND WAS NOT IN SAGE: SAGE fixed the command sets, the factions and the rules when the map loaded. OpenBFME owns
// the simulation, so it can spawn anything anywhere, hand a unit to the other player and put a banner on every screen at any frame.
//
// THE THREE PILLARS (all of them existing, compiled code):
//   - the spawn recipe of CheatMode::Command::Spawn (GameLogic/CheatMode.cpp:185-215): a free spot around the point, newObject, orientation,
//     position, the pathfinder footprint, onBuildComplete. Every check that refuses a structure / a projectile / a Create-a-Hero is reused,
//     so an event can never spawn a missile or a map marker;
//   - the template list: ThingFactory::templateCount() with ids packed from 1 (ThingFactory.cpp:208 is `m_list[id - 1]`), so "every unit in
//     the game" is a loop, and the candidate list is built once at the start of the match;
//   - GetGameLogicRandomValue (Common/RandomValue.h:135) and NOTHING ELSE: rand(), std::random, the clock or a pointer would desync every
//     peer. The whole mode is deterministic and replays.
//
// THE ONE RULE THAT KEEPS IT A GAME: an event never favours a side. Every event runs on every player, or on a random player and then the
// same event on the others. "A bonus for me" is a bug, not chaos.
//
// THE OTHER RULE: every event is announced. A player who is not told what happened does not think "chaos", he thinks "the game broke".
//
// Where it plugs in:
//   GameLogic::chaosMode()          the state (GameLogic.h, next to cheatMode())
//   GameLogic::update(phase 1)      ChaosMode::update, after the command list
//   GameLogic::crc / xferCore       the state is hashed and saved (a desync must show, a savegame must restore it)
//   GameLogicDispatch               MSG_OPENBFME_CHAOS, an ordinary frame command: every peer runs it on the same frame
//   LiveGame                        takeAnnouncements, the same way the cheat lines reach the screen
//
// The events themselves: GameLogic/ChaosEvents.cpp.
#pragma once

#include "Common/StateHash.h"

#include <cstddef>
#include <string>
#include <string_view>
#include <vector>

class GameLogic;
class GameLogicDispatch;
class GameMessage;
class Xfer; // forward only: this header is included by GameLogic.h, which every test includes, and Xfer.h declares `class Snapshot`, a name
            // several test files use for their own struct. The full include is in ChaosMode.cpp where xfer() is defined

namespace ChaosMode
{
// ---- the events ---------------------------------------------------------------------------------------------------------------
enum class Event : int
{
	None = 0,
	// "trash": always on, they read at a glance
	Menagerie = 1,  ///< five units of a RANDOM faction at the player's fortress
	JunkRain = 2,   ///< ten random units anywhere on the map, for everyone
	GoldRush = 3,   ///< gold and command points for EVERY player at once (a race, not a gift)
	Armageddon = 4, ///< every player gets a level-10 hero
	// "action": the screen moves
	Meteor = 5,     ///< damage and fire over an area, the camera shakes on the client only
	Quake = 6,      ///< the same, wider, with debris
	SecondWind = 7, ///< every unit is healed and unstuck: the "breathe" event (the LOGIC has no time scale; only the client has one)
	Titles = 8,     ///< a line of lore across the screen, nothing else: a breather between the real events
	// "what is happening": the match is not the same match any more
	SwapArmies = 9, ///< two players trade every unit they own
	Doppelganger = 10, ///< a copy of your army appears under the other player
	Betrayal = 11,  ///< one of your units changes sides
	Silence = 12,   ///< every unit on the map loses its commands for eight seconds
	Count = 13
};
constexpr int kFirstEvent = 1;
constexpr int kLastEvent = 12;

// the weights and the earliest frame of a match (docs/CHAOS-EVENTS.md): a mode that opens with "SwapArmies" is broken, not punk
struct Weight
{
	Event event;
	int weight;
	int minFrame;
};
const Weight &weights();
const Weight &weightAt(int index); ///< the schedule's row (the test and the Rules tab read it)
int weightCount();
const char *eventName(Event e);            ///< "menagerie": the id, for the localization key chaos.event.<id>
int eventFromName(const std::string &name);
// the announcement's catalog id for an event ("chaos.event.menagerie"). Every id appears here as a literal on purpose: tools/l10n reads the ids
// the code uses from OpenBFMEText::text calls, and a key built by concatenation is one the catalog check cannot see
const char *eventTextId(Event e);
// the announcement in `language` (English where that language has no translation): the string every peer draws on the banner. The ids are named
// here as literals, which is how tools/l10n finds them (a key built by concatenation is invisible to the catalog check)
std::u16string bannerText(std::string_view language, Event e);

// ---- the rhythm ---------------------------------------------------------------------------------------------------------------
constexpr int kFramesPerSecond = 5;         ///< OpenBFME's logic frame (the engine's own rate)
constexpr int kSecondsBetweenEvents = 25;   ///< the pulse: dense, but a normal fight fits between two events
constexpr int kFirstEventFrame = 150;       ///< 30 s: the starting base is allowed to exist first
constexpr int kMaxSpawn = 10;               ///< the spawn limit of one event (CheatMode's own kMaxSpawn)
constexpr int kMaxSummons = 40;             ///< foreign units one event may leave on the map: a slow machine must still run
constexpr std::size_t kLogCap = 256;        ///< the announcements

// ---- the state ---------------------------------------------------------------------------------------------------------------
// display data is NOT hashed and NOT saved: a replay announces the same lines again as it plays
struct LogEntry
{
	unsigned frame = 0;
	Event event = Event::None;
	std::string text;    ///< the announcement (chaos.msg.*), in the language of the build
	int player = -1;     ///< the player the event hit hardest, or -1 when it hit everyone
};

class State
{
public:
	void configure(bool enabled) { m_enabled = enabled; }
	bool enabled() const { return m_enabled; }

	void reset();                                        ///< a new match: the schedule starts again
	void setNextFrame(unsigned f) { m_nextFrame = f; }
	unsigned nextFrame() const { return m_nextFrame; }

	// the one entry point the game calls: phase 1, after the command list, on every peer
	void update(GameLogic &logic);

	// an event by its number: MSG_OPENBFME_CHAOS carries it (a replay of a hand-run event), and update() calls it directly
	bool run(GameLogic &logic, Event e, int player);

	int eventsRun() const { return m_eventsRun; }         ///< hashed: a peer that skipped one desyncs at once
	const std::vector<LogEntry> &log() const { return m_log; }
	std::vector<LogEntry> takeAnnouncements();

	void crc(StateHasher &h) const;
	void xfer(Xfer &x);

private:
	void announce(GameLogic &logic, Event e, int player, std::string text);

	bool m_enabled = false;
	unsigned m_nextFrame = 0;
	int m_eventsRun = 0;
	std::vector<LogEntry> m_log;
	std::vector<LogEntry> m_announce;
};

// ---- the dispatch ------------------------------------------------------------------------------------------------------------
void registerHandlers(GameLogicDispatch &dispatch);
bool execute(GameLogic &logic, const GameMessage &msg);

} // namespace ChaosMode
