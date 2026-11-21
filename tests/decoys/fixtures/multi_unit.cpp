// Compile independently with PROTECTED_NAME=protected_one and protected_two.
// Both translation units intentionally use the same decoy seed and corpus.
#ifndef PROTECTED_NAME
#error PROTECTED_NAME must name this translation unit's entry point
#endif

extern "C" unsigned PROTECTED_NAME(unsigned value) { return value * 3u + 7u; }
