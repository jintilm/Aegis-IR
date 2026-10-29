; PHI demotion fixture: the only PHIs in a source-compiled module at -O0 are
; rare, so this hand-written function makes sure flattening handles them.
; phi_loop(10) == 45, which main returns as its exit code.

target triple = "x86_64-unknown-linux-gnu"

define i32 @phi_loop(i32 %n) {
entry:
  br label %head

head:
  %i = phi i32 [ 0, %entry ], [ %i.next, %body ]
  %acc = phi i32 [ 0, %entry ], [ %acc.next, %body ]
  %cmp = icmp slt i32 %i, %n
  br i1 %cmp, label %body, label %exit

body:
  %acc.next = add i32 %acc, %i
  %i.next = add i32 %i, 1
  br label %head

exit:
  ret i32 %acc
}

define i32 @main() {
entry:
  %r = call i32 @phi_loop(i32 10)
  ret i32 %r
}
