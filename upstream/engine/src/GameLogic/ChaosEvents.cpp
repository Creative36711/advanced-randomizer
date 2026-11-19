// OpenBFME. GPL-3.0.
// See GameLogic/ChaosEvents.h. Lane CHAOS-1.

#include "GameLogic/ChaosEvents.h"

#include "Common/Money.h"
#include "Common/Player.h"
#include "Common/PlayerList.h"
#include "Common/PlayerTemplate.h"
#include "Common/RandomValue.h"
#include "Common/Thing/ThingFactory.h"
#include "Common/Thing/ThingTemplate.h"
#include "GameLogic/AI/AIWorld.h"
#include "GameLogic/ChaosMode.h"
#include "GameLogic/Damage.h"
#include "GameLogic/Economy.h"
#include "GameLogic/FindPositionAround.h"
#include "GameLogic/GameLogic.h"
#include "GameLogic/Map/TerrainLogic.h"
#include "GameLogic/Module/BehaviorModule.h"
#include "GameLogic/Object/ExperienceTracker.h"
#include "GameLogic/Object/Object.h"
#include "GameLogic/ObjectTypes.h"
#include "GameLogic/SimMath.h"

#include <vector>

namespace ChaosMode
{
namespace ChaosEvents
{
namespace
{
// the same question CheatMode::Command::Spawn asks before it makes an object (CheatMode.cpp:145-155), plus INERT: a prop or a map marker would
// stand in the middle of the fight and mean nothing. CREATE_A_HERO is refused for the same reason it is refused there: that object is made from
// its player's own record and would be born ownerless.
bool isSpawnableUnit(GameLogic &logic, const ThingTemplate &tt)
{
	return !logic.economy().templateKindOf(tt, "STRUCTURE") && !logic.economy().templateKindOf(tt, "PROJECTILE") &&
		   !logic.economy().templateKindOf(tt, "CREATE_A_HERO") && !logic.economy().templateKindOf(tt, "INERT");
}

// every unit the game has, built once: the template ids are packed from 1 (ThingFactory.cpp:208 is `m_list[id - 1]`), so this loop has no holes
// and the list never changes during a match
const std::vector<const ThingTemplate *> &candidates(GameLogic &logic)
{
	static std::vector<const ThingTemplate *> list;
	static const ThingFactory *owner = nullptr;
	if (owner == &logic.things())
	{
		return list;
	}
	list.clear();
	owner = &logic.things();
	for (unsigned short id = 1; id <= (unsigned short)logic.things().templateCount(); ++id)
	{
		const ThingTemplate *tt = logic.things().findByTemplateID(id);
		if (tt && isSpawnableUnit(logic, *tt))
		{
			list.push_back(tt);
		}
	}
	return list;
}

const ThingTemplate *randomUnit(GameLogic &logic)
{
	const std::vector<const ThingTemplate *> &list = candidates(logic);
	if (list.empty())
	{
		return nullptr;
	}
	return list[(std::size_t)GetGameLogicRandomValue(0, (int)list.size() - 1, __FILE__, __LINE__)];
}

float randomUnitFloat(GameLogic &logic)
{
	return GetGameLogicRandomValueReal(0.0f, 1.0f, __FILE__, __LINE__);
}

bool isGamePlayer(const GameLogic &logic, int index);

Player *playerAt(GameLogic &logic, int index)
{
	Player *p = logic.players().getNthPlayer(index);
	return p && p->getPlayerIndex() == index ? p : nullptr;
}

// the players an event may touch: a playable faction's player, not the neutral one, not an observer, not a defeated one
std::vector<int> activePlayers(GameLogic &logic)
{
	std::vector<int> out;
	for (int i = 0; i < logic.players().getPlayerCount(); ++i)
	{
		Player *p = playerAt(logic, i);
		if (p && isGamePlayer(logic, i) && !p->isDefeated())
		{
			out.push_back(i);
		}
	}
	return out;
}

bool isGamePlayer(const GameLogic &logic, int index)
{
	const Player *p = logic.players().getNthPlayer(index);
	return p && p->getPlayerIndex() == index && p != logic.players().getNeutralPlayer() && !p->isObserver() && p->getPlayerTemplate() &&
		   p->getPlayerTemplate()->hasStartingBuilding();
}

// the point an event happens around: the player's own units (a fortress first), else the middle of the map
Coord3D focusOf(GameLogic &logic, int playerIndex)
{
	for (Object *o = logic.getFirstObject(); o; o = o->getNextObject())
	{
		const Player *p = o->getControllingPlayer();
		if (p && p->getPlayerIndex() == playerIndex)
		{
			const Coord3D *pos = o->getPosition();
			if (pos)
			{
				return *pos;
			}
		}
	}
	Coord3D middle{};
	if (const TerrainLogic *t = logic.terrain())
	{
		float lx, ly, hx, hy;
		t->getMapExtentIncludingBorder(lx, ly, hx, hy);
		middle.x = (lx + hx) * 0.5f;
		middle.y = (ly + hy) * 0.5f;
	}
	return middle;
}

// CheatMode::Command::Spawn's recipe (CheatMode.cpp:185-215), one object: the first free spot near the point, then the orientation, the position,
// the pathfinder footprint and onBuildComplete. Skipping the last one makes a building that is never finished and a unit that cannot move.
Object *spawnAt(GameLogic &logic, const ThingTemplate &tt, Player &player, Coord3D pos)
{
	if (!player.getDefaultTeam())
	{
		return nullptr;
	}
	FindPositionOptions around;
	around.minRadius = 0.0f;
	around.maxRadius = 200.0f;
	around.startAngle = 0.0f;
	Coord3D free;
	if (logic.aiWorld() && FindPosition::findPositionAround(logic, pos, around, free))
	{
		pos = free;
	}
	pos.z = logic.getGroundHeight(pos.x, pos.y);
	Object *o = logic.newObject(&tt, player.getDefaultTeam(), ObjectStatusMaskType{});
	if (!o)
	{
		return nullptr;
	}
	o->setOrientation(0.0f);
	o->setPosition(&pos);
	if (AIWorld *ai = logic.aiWorld())
	{
		ai->addObjectToPathfindMap(*o);
	}
	for (const std::unique_ptr<BehaviorModule> &m : o->modules())
	{
		if (CreateModuleInterface *create = m->getCreate())
		{
			create->onBuildComplete();
		}
	}
	return o;
}

// a spread of points around a centre: rows of 4 at 15 world units, the shape CheatMode's spawn uses, so ten units do not stand in one spot
std::vector<Coord3D> ring(const Coord3D &centre, int count)
{
	std::vector<Coord3D> out;
	for (int i = 0; i < count; ++i)
	{
		Coord3D p = centre;
		p.x = SimMath::addf32(centre.x, SimMath::mulf32(SimMath::sseFromInt32(i % 4), 15.0f));
		p.y = SimMath::addf32(centre.y, SimMath::mulf32(SimMath::sseFromInt32(i / 4), 15.0f));
		out.push_back(p);
	}
	return out;
}

// objects whose owner is `playerIndex`, safe against the list changing under us (newObject appends, killPlayer defers to the destroy list)
std::vector<Object *> objectsOf(GameLogic &logic, int playerIndex)
{
	std::vector<Object *> out;
	for (Object *o = logic.getFirstObject(); o; o = o->getNextObject())
	{
		const Player *p = o->getControllingPlayer();
		if (p && p->getPlayerIndex() == playerIndex && !o->isDestroyed())
		{
			out.push_back(o);
		}
	}
	return out;
}

// ---- the events --------------------------------------------------------------------------------------------------------------

// five units of a RANDOM faction at the player's fortress: the one event that reads in a screenshot
bool menagerie(GameLogic &logic, int player)
{
	std::vector<int> players = activePlayers(logic);
	if (players.empty())
	{
		return false;
	}
	const int who = player >= 0 ? player : players[(std::size_t)GetGameLogicRandomValue(0, (int)players.size() - 1, __FILE__, __LINE__)];
	Player *p = playerAt(logic, who);
	if (!p)
	{
		return false;
	}
	const Coord3D at = focusOf(logic, who);
	const std::vector<Coord3D> points = ring(at, 5);
	int made = 0;
	for (const Coord3D &pos : points)
	{
		const ThingTemplate *tt = randomUnit(logic);
		if (tt && spawnAt(logic, *tt, *p, pos) != nullptr)
		{
			++made;
		}
	}
	return made > 0;
}

// ten random units anywhere on the map, for every player at once: the map fills up and nobody owns the result
bool junkRain(GameLogic &logic)
{
	std::vector<int> players = activePlayers(logic);
	if (players.empty())
	{
		return false;
	}
	int made = 0;
	for (int i = 0; i < kMaxSpawn; ++i)
	{
		const int who = players[(std::size_t)GetGameLogicRandomValue(0, (int)players.size() - 1, __FILE__, __LINE__)];
		Player *p = playerAt(logic, who);
		if (!p)
		{
			continue;
		}
		const Coord3D at = focusOf(logic, who);
		Coord3D pos;
		pos.x = at.x + GetGameLogicRandomValueReal(-400.0f, 400.0f, __FILE__, __LINE__);
		pos.y = at.y + GetGameLogicRandomValueReal(-400.0f, 400.0f, __FILE__, __LINE__);
		pos.z = 0.0f;
		const ThingTemplate *tt = randomUnit(logic);
		if (tt && spawnAt(logic, *tt, *p, pos) != nullptr)
		{
			++made;
		}
	}
	return made > 0;
}

// gold and command points for EVERY player at once: a race, not a gift (CheatMode::AddResources and AddCommandPoints, all players)
bool goldRush(GameLogic &logic)
{
	std::vector<int> players = activePlayers(logic);
	for (int who : players)
	{
		if (Player *p = playerAt(logic, who))
		{
			p->getMoney()->deposit(5000, nullptr, false);
			p->commandPoints().addBonus(10);
		}
	}
	return !players.empty();
}

// a level-10 unit for every player: the power-spike event, and the only one that is plainly unfair on a bad draw (that is the point)
bool armageddon(GameLogic &logic)
{
	std::vector<int> players = activePlayers(logic);
	int made = 0;
	for (int who : players)
	{
		Player *p = playerAt(logic, who);
		if (!p)
		{
			continue;
		}
		const Coord3D at = focusOf(logic, who);
		const ThingTemplate *tt = randomUnit(logic);
		Object *made0 = tt ? spawnAt(logic, *tt, *p, at) : nullptr;
		if (!made0)
		{
			continue;
		}
		++made;
		if (ExperienceTracker *xp = made0->getExperienceTracker())
		{
			xp->gainLevels(9, true); // RW 0x79D7E5, the same call CheatMode::LevelUp makes
		}
	}
	return made > 0;
}

// damage over an area: the shockwave the damage core already has (DamageInfo:m_shockWave*, the fields MetaImpactNugget writes), so the hit does
// not need a weapon, a projectile or a template that may not exist in a mod
int shockwave(GameLogic &logic, const Coord3D &at, float radius, float amount, int count)
{
	int hit = 0;
	for (int i = 0; i < count; ++i)
	{
		Coord3D pos;
		pos.x = at.x + GetGameLogicRandomValueReal(-radius, radius, __FILE__, __LINE__);
		pos.y = at.y + GetGameLogicRandomValueReal(-radius, radius, __FILE__, __LINE__);
		pos.z = logic.getGroundHeight(pos.x, pos.y);
		for (Object *o = logic.getFirstObject(); o; o = o->getNextObject())
		{
			const Coord3D *op = o->getPosition();
			if (!op || o->isDestroyed())
			{
				continue;
			}
			const float dx = op->x - pos.x, dy = op->y - pos.y;
			if (dx * dx + dy * dy > 120.0f * 120.0f)
			{
				continue;
			}
			DamageInfo info;
			info.m_input.m_sourceID = 0;
			info.m_input.m_damageType = DAMAGE_UNRESISTABLE; // a meteor does not care about armour
			info.m_input.m_deathType = DEATH_BURNED;
			info.m_input.m_amount = amount;
			info.m_input.m_damageFXOverride = 29; // UNDEFINED: the weapon's own effect, there is none
			info.m_input.m_shouldPlayUnderAttackEva = false;
			info.m_input.m_shockWaveSourceID = 0;
			info.m_input.m_shockWaveVector = Coord3D{ 0.0f, 0.0f, 0.0f };
			info.m_input.m_shockWaveAmount = 40.0f;
			info.m_input.m_shockWaveRadius = 60.0f;
			info.m_input.m_shockWaveTaperOff = 1.0f;
			info.m_input.m_shockWaveZMult = 1.0f;
			info.m_input.m_shockWaveClearRadius = true;
			info.m_input.m_shockWaveClearMult = 1.0f;
			o->attemptDamage(info);
			++hit;
		}
	}
	return hit;
}

bool meteor(GameLogic &logic)
{
	std::vector<int> players = activePlayers(logic);
	if (players.empty())
	{
		return false;
	}
	int hit = 0;
	for (int who : players)
	{
		const Coord3D at = focusOf(logic, who);
		hit += shockwave(logic, at, 300.0f, 400.0f, 3);
	}
	return hit > 0;
}

bool quake(GameLogic &logic)
{
	std::vector<int> players = activePlayers(logic);
	if (players.empty())
	{
		return false;
	}
	int hit = 0;
	for (int who : players)
	{
		const Coord3D at = focusOf(logic, who);
		hit += shockwave(logic, at, 500.0f, 120.0f, 4);
	}
	return hit > 0;
}

// every unit on the map is healed to full and its special powers come back: no time scale exists in the LOGIC (GodotGameWorld holds one, the
// client's), so an event that changed "speed" would change nothing that a peer can see. This one costs nothing and reads instantly.
bool secondWind(GameLogic &logic)
{
	int healed = 0;
	for (Object *o = logic.getFirstObject(); o; o = o->getNextObject())
	{
		if (o->isDestroyed() || !o->getControllingPlayer())
		{
			continue;
		}
		DamageInfo info;
		info.m_input.m_damageType = DAMAGE_HEALING;
		info.m_input.m_amount = 1.0e9f;
		info.m_input.m_shouldPlayUnderAttackEva = false;
		info.m_input.m_damageFXOverride = 29;
		o->attemptDamage(info);
		o->clearDisabled(DISABLED_USER_PARALYZED);
		++healed;
	}
	return healed > 0;
}

// a line of lore: the breath between the real events, and the cheapest possible event
bool titles(GameLogic &logic)
{
	return !activePlayers(logic).empty();
}

// two players trade every unit they own: the event that ends civilised play, and the one people clip
bool swapArmies(GameLogic &logic)
{
	std::vector<int> players = activePlayers(logic);
	if (players.size() < 2)
	{
		return false;
	}
	const int i = (int)GetGameLogicRandomValue(0, (int)players.size() - 1, __FILE__, __LINE__);
	int j = (int)GetGameLogicRandomValue(0, (int)players.size() - 2, __FILE__, __LINE__);
	if (j >= i)
	{
		++j;
	}
	Player *a = playerAt(logic, players[(std::size_t)i]);
	Player *b = playerAt(logic, players[(std::size_t)j]);
	if (!a || !b || !a->getDefaultTeam() || !b->getDefaultTeam())
	{
		return false;
	}
	const std::vector<Object *> mine = objectsOf(logic, a->getPlayerIndex());
	const std::vector<Object *> theirs = objectsOf(logic, b->getPlayerIndex());
	// two passes, not one: setTeam moves the object between the member lists, and a single pass over a list being moved is a walk through a
	// structure that changes under it
	for (Object *o : mine)
	{
		o->setTeam(b->getDefaultTeam());
	}
	for (Object *o : theirs)
	{
		o->setTeam(a->getDefaultTeam());
	}
	return true;
}

// one of your units changes sides
bool betrayal(GameLogic &logic)
{
	std::vector<int> players = activePlayers(logic);
	if (players.size() < 2)
	{
		return false;
	}
	const int i = players[(std::size_t)GetGameLogicRandomValue(0, (int)players.size() - 1, __FILE__, __LINE__)];
	int j = (int)GetGameLogicRandomValue(0, (int)players.size() - 2, __FILE__, __LINE__);
	if (j >= i)
	{
		++j;
	}
	Player *traitor = playerAt(logic, i);
	Player *receiver = playerAt(logic, players[(std::size_t)j]);
	if (!traitor || !receiver || !receiver->getDefaultTeam())
	{
		return false;
	}
	std::vector<Object *> mine = objectsOf(logic, i);
	if (mine.empty())
	{
		return false;
	}
	Object *chosen = mine[(std::size_t)GetGameLogicRandomValue(0, (int)mine.size() - 1, __FILE__, __LINE__)];
	chosen->setTeam(receiver->getDefaultTeam());
	return true;
}

// a copy of your army under the other player: the most expensive event in object count, so it is capped by kMaxSummons
bool doppelganger(GameLogic &logic)
{
	std::vector<int> players = activePlayers(logic);
	if (players.size() < 2)
	{
		return false;
	}
	const int i = players[(std::size_t)GetGameLogicRandomValue(0, (int)players.size() - 1, __FILE__, __LINE__)];
	int j = (int)GetGameLogicRandomValue(0, (int)players.size() - 2, __FILE__, __LINE__);
	if (j >= i)
	{
		++j;
	}
	Player *source = playerAt(logic, i);
	Player *target = playerAt(logic, players[(std::size_t)j]);
	if (!source || !target)
	{
		return false;
	}
	const std::vector<Object *> mine = objectsOf(logic, i);
	if (mine.empty())
	{
		return false;
	}
	const int limit = (int)mine.size() < kMaxSummons ? (int)mine.size() : kMaxSummons;
	int made = 0;
	for (int n = 0; n < limit; ++n)
	{
		const int pick = (int)GetGameLogicRandomValue(0, (int)mine.size() - 1, __FILE__, __LINE__);
		Object *o = mine[(std::size_t)pick];
		if (!o || o->isDestroyed() || !o->getTemplate())
		{
			continue;
		}
		const Coord3D at = focusOf(logic, target->getPlayerIndex());
		if (spawnAt(logic, *o->getTemplate(), *target, at))
		{
			++made;
		}
	}
	return made > 0;
}

// every unit on the map loses its orders for eight seconds: DISABLED_USER_PARALYZED is the engine's own "cannot act", and setDisabled's expiry
// brings the unit back by itself, so no event has to remember to undo it
bool silence(GameLogic &logic)
{
	const unsigned until = logic.getFrame() + 8 * kFramesPerSecond;
	int touched = 0;
	for (Object *o = logic.getFirstObject(); o; o = o->getNextObject())
	{
		if (!o->isDestroyed() && o->getControllingPlayer())
		{
			o->setDisabled(DISABLED_USER_PARALYZED, until);
			++touched;
		}
	}
	return touched > 0;
}
} // namespace

bool run(GameLogic &logic, Event e, int player)
{
	switch (e)
	{
	case Event::Menagerie: return menagerie(logic, player);
	case Event::JunkRain: return junkRain(logic);
	case Event::GoldRush: return goldRush(logic);
	case Event::Armageddon: return armageddon(logic);
	case Event::Meteor: return meteor(logic);
	case Event::Quake: return quake(logic);
	case Event::SecondWind: return secondWind(logic);
	case Event::Titles: return titles(logic);
	case Event::SwapArmies: return swapArmies(logic);
	case Event::Doppelganger: return doppelganger(logic);
	case Event::Betrayal: return betrayal(logic);
	case Event::Silence: return silence(logic);
	case Event::None:
	case Event::Count: return false;
	}
	return false;
}
} // namespace ChaosEvents
} // namespace ChaosMode
