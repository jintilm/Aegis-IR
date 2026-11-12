# Delta ledger

Recover the exact behaviour of `dl_score` and `dl_accept`.

Each input byte is split into a two-bit operation tag and a six-bit payload.
The state combines a signed delta ledger, a rolling byte tag, and a
position-dependent rotation. The acceptance predicate is a low-bit agreement
between the score and the first/last bytes.

Implement `target.cpp` against `include/target.h`. The visible examples are
useful for checking I/O, but hidden cases and seeded fuzz inputs decide the
grade.
