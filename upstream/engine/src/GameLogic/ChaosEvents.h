// OpenBFME. GPL-3.0.
//
// The events of ChaosMode (lane CHAOS-1). Split from ChaosMode.cpp because that file is the schedule and this one is the content: an event is a
// function that returns true when it changed the game, and nothing else. Adding an event is adding a row to the table in ChaosMode.cpp and a
// case here.
//
// Every function here is simulation code: it runs inside GameLogic::update on every peer, in the same order, drawing from the same random
// stream (GetGameLogicRandomValue, never rand()). Anything that is only seen (a camera shake, a sound, a banner's animation) is NOT here: the
// announcement LogEntry is the client's cue (LiveGame's takeAnnouncements).
#pragma once

class GameLogic;

namespace ChaosMode
{
enum class Event : int;

namespace ChaosEvents
{
// true when the event changed the game (it still runs, and is still counted and announced, when it changes nothing: a map with no units)
bool run(GameLogic &logic, Event e, int player);
} // namespace ChaosEvents
} // namespace ChaosMode
