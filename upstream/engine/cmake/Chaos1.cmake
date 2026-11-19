# Lane CHAOS-1 (the Chaos mode: events that change the match, for everyone, every 25 seconds). Included from engine/CMakeLists.txt so the
# lane's file lists stay out of the shared list, the same way Cheat1.cmake does it.

# simulation sources (sim audit manifest): MSG_OPENBFME_CHAOS, the schedule, and the events, all run by every peer on the same frame
list(APPEND OPENBFME_SIM_SOURCES
    src/GameLogic/ChaosMode.cpp
    src/GameLogic/ChaosEvents.cpp
)
set(OPENBFME_CHAOS1_TESTS
    tests/test_chaos1_mode.cpp
)
