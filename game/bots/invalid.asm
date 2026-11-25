; A valid action followed by a third byte must be rejected.
MOVI R0, 68
SYSCALL 0
MOVI R0, 88
SYSCALL 3
HALT
