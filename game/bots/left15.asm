; Skip the 272-byte board and "ID ". Read digits of remaining turns.
MOVI R1, 0
MOVI R2, 274
skip:
SYSCALL 2
INC R1
CMP R1, R2
JNZ skip
MOVI R1, 4096
SYSCALL 2
STB [R1], R0
INC R1
SYSCALL 2
STB [R1], R0
INC R1
SYSCALL 2
STB [R1], R0
; Consume the header suffix (3 bytes) and both position lines (16 bytes).
MOVI R1, 0
MOVI R2, 19
tail:
SYSCALL 2
INC R1
CMP R1, R2
JNZ tail
; First fifteen turns have remaining turns 200 or 199..186.
MOVI R1, 4096
LDB R0, [R1]
MOVI R2, 50
CMP R0, R2
JZ left
MOVI R2, 49
CMP R0, R2
JNZ wait
INC R1
LDB R0, [R1]
MOVI R2, 57
CMP R0, R2
JZ left
MOVI R2, 56
CMP R0, R2
JNZ wait
INC R1
LDB R0, [R1]
MOVI R2, 54
check:
CMP R0, R2
JZ left
INC R2
MOVI R3, 58
CMP R2, R3
JNZ check
wait:
MOVI R0, 88
JUMP output
left:
MOVI R0, 65
output:
SYSCALL 0
HALT
