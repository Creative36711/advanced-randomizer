# CHAOS: события — рабочий проект

Каждый блок — конкретная реализация, проверенная по API движка.
Источник примитивов: `engine/src/GameLogic/CheatMode.cpp` (спавн, деньги),
`ThingFactory` (перебор шаблонов), `Economy::templateKindOf` (фильтр).

## Общее: как выбирается событие

```cpp
// Каждые kChaosFrames кадров логики (5 кадров = 1 с, 25 с = 125 кадров).
// RNG — ТОЛЬКО игровой генератор: rand() рассинхронизирует сеть.
const int roll = GetGameLogicRandomValue(0, totalWeight - 1, __FILE__, __LINE__);
```

**Правило номер один:** никакого `rand()`, `std::random`, времени или
указателей. Только `getGameLogicRandomValue` — он синхронизирован между
машинами и попадает в replay.

## Фильтр «это боевой отряд»

```cpp
bool isSpawnableUnit(GameLogic &logic, const ThingTemplate &tt)
{
    if (logic.economy().templateKindOf(tt, "STRUCTURE"))   return false;
    if (logic.economy().templateKindOf(tt, "PROJECTILE"))  return false;
    if (logic.economy().templateKindOf(tt, "CREATE_A_HERO"))return false;
    if (logic.economy().templateKindOf(tt, "INERT"))       return false;
    return true;
}
```

Тот же набор проверок, что делает `CheatMode::spawn`, — значит события не
смогут породить снаряд или маркер карты.

## Как перебрать ВСЕ объекты игры

`ThingFactory` держит шаблоны плотным списком от 1 до `templateCount()`
(`ThingFactory.cpp:208`: `m_list[id - 1]`, значит без дыр). Отсюда простой и
безопасный перебор:

```cpp
std::vector<const ThingTemplate *> candidates;
for (unsigned short id = 1; id <= things.templateCount(); ++id) {
    const ThingTemplate *tt = things.findByTemplateID(id);
    if (tt && isSpawnableUnit(logic, *tt)) candidates.push_back(tt);
}
// выбор: GetGameLogicRandomValue(0, candidates.size() - 1, __FILE__, __LINE__)
```

Список собирается **один раз при старте матча** (он не меняется), а выбор
случайного — каждое событие. Это дешево и детерминировано.

## Событие 1: ЗВЕРИНЕЦ

У крепости игрока появляются 5 отрядов **случайной фракции**.

```cpp
// точки: вокруг крепости (logic->getObjectByID(castleID)) или вокруг стартовой
for (int i = 0; i < 5; ++i) {
    // перебор всех шаблонов: ThingFactory::templateCount() + findByTemplateID(i)
    // отбрасываем всё, что не проходит isSpawnableUnit
    const ThingTemplate *tt = pickRandomTemplate(logic, rng);
    spawnAround(logic, tt, player, castlePos);   // рецепт из CheatMode.cpp:185-215
}
```

**Что происходит на экране:** у твоих ворот материализуются 5 чужих отрядов.
Если повезёт — балрог. Если нет — гоблины.

## Событие 2: ЗОЛОТАЯ ЛИХОРАДКА

```cpp
for (int p = 0; p < players.count(); ++p) {
    players.getPlayer(p)->getMoney().deposit(5000);           // как CheatMode::AddResources
    players.getPlayer(p)->getCommandPoints().addBonus(10);    // как CheatMode::AddCommandPoints
}
```

Просто, но **всем сразу** — поэтому это гонка, а не подарок.

## Событие 3: МЕТЕОР

```cpp
// 8 точек по карте: extent из TerrainLogic
float lx, ly, hx, hy;
terrain->getMapExtentIncludingBorder(lx, ly, hx, hy);
for (int i = 0; i < 8; ++i) {
    Coord3D pos;
    pos.x = lerp(lx, hx, GetGameLogicRandomValueReal(0.0f, 1.0f, __FILE__, __LINE__) / 100.0f);
    pos.y = lerp(ly, hy, randFloat(logic));
    pos.z = 0;
    // два эффекта: урон по площади + визуал
    // (шаблон эффекта берётся из данных игры, если он есть; иначе только урон)
}
```

**Важно:** камеру трясёт только **клиент** (как `CameraShake` в движке) —
в логику это не пишем, иначе desync.

## Событие 4: ОБМЕН АРМИЯМИ

Самое злое. Меняет владельца у **всех** отрядов двух игроков.

```cpp
// собрать все Object* игроков A и B
std::vector<Object *> a = unitsOf(logic, playerA);
std::vector<Object *> b = unitsOf(logic, playerB);
for (Object *o : a) o->setTeam(teamB);   // Object::setTeam(Team*) — Object.h:105
for (Object *o : b) o->setTeam(teamA);
```

**Риск:** камера и выделение у игроков остаются на старых юнитах — это нормально,
но UI надо сбросить (deselect), иначе игрок «управляет» чужим.

## Событие 5: ТИТРЫ

Гигантский текст поверх экрана:

```cpp
// Знакомый механизм: scripts' DISPLAY_TEXT / in-game message line.
// В OpenBFME: UI::displayText(unicode) — презентация, не логика.
```

В SAGE это делалось только скриптом карты, вшитым заранее. Здесь — **в рантайме,
по случайному выбору**.

## Событие 6: ЗАМЕДЛЕНИЕ / УСКОРЕНИЕ

```cpp
logic.setTimeScale(0.5f);   // на 10 секунд (50 кадров), потом вернуть 1.0
```

Уже есть в движке (`set_time_scale` доступен даже из GDScript).

## Ритм и вес

```cpp
struct ChaosEvent {
    const char *id;          // для локализации: chaos.event.<id>
    int weight;              // вероятность
    int minFrame;            // не раньше какого кадра матча
    void (*run)(GameLogic &, ChaosState &);
};
```

| Событие | вес | с кадра |
|---|---|---|
| goldrush | 30 | 0 |
| menagerie | 25 | 250 |
| meteor | 20 | 500 |
| titles | 10 | 0 |
| timescale | 10 | 750 |
| swap | 5 | 1500 |

`swap` — редкое, потому что оно **ломает матч**. Это и делает его ценным:
раз в пять матчей случается, и об этом рассказывают.

## Что делает режим «своим»

Баннер. Каждое событие начинается с **названия на весь экран** (2 секунды):

```
ЗВЕРИНЕЦ
```

Игрок понимает, что произошло. Без этого хаос превращается в «игра сломалась».

## Порядок реализации

1. `ChaosRules.h` — константы, веса, id событий (как `MpGameRules.h` для Legendary Heroes)
2. `ChaosMode.h/.cpp` — состояние, таймер, выбор события, три первые реализации
3. Правило в `AptSkirmishRules.cpp` — чекбокс «CHAOS (OpenBFME)»
4. Поле в `SkirmishGameInfo` — идёт в игру как `legendaryHeroes`
5. Баннер + локализация

**Первый шаг (1-2) можно проверить без игры**: юнит-тест в `engine/tests`,
который гоняет выбор 10000 раз и проверяет распределение и детерминизм.
