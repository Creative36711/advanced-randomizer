// OpenBFME. GPL-3.0.
// See GameLogic/ChaosMode.h. Lane CHAOS-1.

#include "GameLogic/ChaosMode.h"

#include "Common/Player.h"
#include "Common/PlayerList.h"
#include "Common/RandomValue.h"
#include "Common/Xfer.h"
#include "GameLogic/ChaosEvents.h"
#include "GameLogic/GameLogic.h"
#include "GameLogic/GameLogicDispatch.h"
#include "GameLogic/GameMessage.h"
#include "GameClient/OpenBFMEText.h"

#include <algorithm>
#include <utility>

namespace ChaosMode
{
namespace
{
// the table (docs/CHAOS-EVENTS.md): SwapArmies is rare because it breaks the match, and that is exactly why it is worth waiting for
const Weight kWeights[] = {
	{ Event::GoldRush, 30, 0 },
	{ Event::Menagerie, 25, 250 },
	{ Event::Meteor, 20, 500 },
	{ Event::Titles, 10, 0 },
	{ Event::SecondWind, 10, 750 },
	{ Event::JunkRain, 15, 400 },
	{ Event::Quake, 12, 900 },
	{ Event::Armageddon, 8, 1200 },
	{ Event::Betrayal, 8, 1000 },
	{ Event::Doppelganger, 5, 1500 },
	{ Event::Silence, 5, 800 },
	{ Event::SwapArmies, 3, 2000 },
};

const char *const kNames[] = { "none",   "menagerie", "junk_rain",    "gold_rush", "armageddon", "meteor", "quake",
							   "second_wind", "titles",   "swap_armies", "doppelganger", "betrayal", "silence" };
} // namespace

const Weight &weights()
{
	return kWeights[0];
}

const Weight &weightAt(int index)
{
	return kWeights[index];
}

int weightCount()
{
	return (int)(sizeof(kWeights) / sizeof(kWeights[0]));
}

const char *eventName(Event e)
{
	const int i = (int)e;
	return i >= 0 && i < (int)Event::Count ? kNames[i] : "none";
}

int eventFromName(const std::string &name)
{
	for (int i = 0; i < (int)Event::Count; ++i)
	{
		if (name == kNames[i])
		{
			return i;
		}
	}
	return 0;
}

const char *eventTextId(Event e)
{
	switch (e)
	{
	case Event::Menagerie: return "chaos.event.menagerie";
	case Event::JunkRain: return "chaos.event.junk_rain";
	case Event::GoldRush: return "chaos.event.gold_rush";
	case Event::Armageddon: return "chaos.event.armageddon";
	case Event::Meteor: return "chaos.event.meteor";
	case Event::Quake: return "chaos.event.quake";
	case Event::SecondWind: return "chaos.event.second_wind";
	case Event::Titles: return "chaos.event.titles";
	case Event::SwapArmies: return "chaos.event.swap_armies";
	case Event::Doppelganger: return "chaos.event.doppelganger";
	case Event::Betrayal: return "chaos.event.betrayal";
	case Event::Silence: return "chaos.event.silence";
	case Event::None:
	case Event::Count: return "";
	}
	return "";
}

std::u16string bannerText(std::string_view language, Event e)
{
	switch (e)
	{
	case Event::Menagerie: return OpenBFMEText::text(language, "chaos.event.menagerie");
	case Event::JunkRain: return OpenBFMEText::text(language, "chaos.event.junk_rain");
	case Event::GoldRush: return OpenBFMEText::text(language, "chaos.event.gold_rush");
	case Event::Armageddon: return OpenBFMEText::text(language, "chaos.event.armageddon");
	case Event::Meteor: return OpenBFMEText::text(language, "chaos.event.meteor");
	case Event::Quake: return OpenBFMEText::text(language, "chaos.event.quake");
	case Event::SecondWind: return OpenBFMEText::text(language, "chaos.event.second_wind");
	case Event::Titles: return OpenBFMEText::text(language, "chaos.event.titles");
	case Event::SwapArmies: return OpenBFMEText::text(language, "chaos.event.swap_armies");
	case Event::Doppelganger: return OpenBFMEText::text(language, "chaos.event.doppelganger");
	case Event::Betrayal: return OpenBFMEText::text(language, "chaos.event.betrayal");
	case Event::Silence: return OpenBFMEText::text(language, "chaos.event.silence");
	case Event::None:
	case Event::Count: return {};
	}
	return {};
}

void State::reset()
{
	m_nextFrame = 0;
	m_eventsRun = 0;
	m_log.clear();
	m_announce.clear();
}

void State::announce(GameLogic &logic, Event e, int player, std::string text)
{
	LogEntry entry;
	entry.frame = logic.getFrame();
	entry.event = e;
	entry.player = player;
	entry.text = std::move(text);
	if (m_log.size() >= kLogCap)
	{
		m_log.erase(m_log.begin());
	}
	m_log.push_back(entry);
	if (m_announce.size() < kLogCap)
	{
		m_announce.push_back(std::move(entry));
	}
}

// the pulse: one event every kSecondsBetweenEvents, forever; the first one is late enough that a starting base exists
void State::update(GameLogic &logic)
{
	if (!m_enabled)
	{
		return;
	}
	const unsigned frame = logic.getFrame();
	if (m_nextFrame == 0)
	{
		m_nextFrame = kFirstEventFrame;
	}
	if (frame < m_nextFrame)
	{
		return;
	}
	// the schedule advances FIRST: an event that fails still costs its slot, or a silent map would run an event every frame
	m_nextFrame = frame + (unsigned)(kSecondsBetweenEvents * kFramesPerSecond);

	// the weighted pick, ONE draw: every peer draws the same number on the same frame or the game is already lost
	int total = 0;
	for (int i = 0; i < weightCount(); ++i)
	{
		if ((int)frame >= kWeights[i].minFrame)
		{
			total += kWeights[i].weight;
		}
	}
	if (total <= 0)
	{
		return;
	}
	int roll = GetGameLogicRandomValue(0, total - 1, __FILE__, __LINE__);
	Event chosen = Event::GoldRush;
	for (int i = 0; i < weightCount(); ++i)
	{
		if ((int)frame < kWeights[i].minFrame)
		{
			continue;
		}
		if (roll < kWeights[i].weight)
		{
			chosen = kWeights[i].event;
			break;
		}
		roll -= kWeights[i].weight;
	}
	run(logic, chosen, -1);
}

bool State::run(GameLogic &logic, Event e, int player)
{
	if (!m_enabled || e <= Event::None || e >= Event::Count)
	{
		return false;
	}
	++m_eventsRun; // hashed: counted even when the event changes nothing, so a skipped event shows up as a desync at once
	const bool done = ChaosEvents::run(logic, e, player);
	if (done)
	{
		announce(logic, e, player, std::string("chaos.event.") + eventName(e));
	}
	return done;
}

std::vector<LogEntry> State::takeAnnouncements()
{
	std::vector<LogEntry> out;
	out.swap(m_announce);
	return out;
}

void State::crc(StateHasher &h) const
{
	if (!m_enabled)
	{
		return; // a normal game's hash is exactly what it was: the mode costs nothing when it is off
	}
	h.addBool(m_enabled);
	h.addU32(m_nextFrame);
	h.addI32(m_eventsRun);
}

void State::xfer(Xfer &x)
{
	x.xferBool(&m_enabled);
	x.xferUnsignedInt(&m_nextFrame);
	x.xferInt(&m_eventsRun);
	if (x.isLoading() && m_eventsRun < 0)
	{
		throw XferException("the chaos event count");
	}
}

void registerHandlers(GameLogicDispatch &d)
{
	// an ordinary frame command: it travels, it is recorded in the replay and it runs on every peer on the same frame
	d.registerHandler(MSG_OPENBFME_CHAOS, "CHAOS-1", [](GameLogic &l, const GameMessage &m) { return execute(l, m); });
}

bool execute(GameLogic &logic, const GameMessage &msg)
{
	const GameMessageArgument *a0 = msg.getArgument(0), *a1 = msg.getArgument(1);
	if (!a0 || a0->type != ARGUMENTDATATYPE_INTEGER || !a1 || a1->type != ARGUMENTDATATYPE_INTEGER)
	{
		return true; // a malformed command is dropped, never the dispatcher's unhandled count
	}
	logic.chaosMode().run(logic, (Event)a0->integer, a1->integer);
	return true;
}

} // namespace ChaosMode
